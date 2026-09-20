"""Data update coordinator for the Cloudflare Multi Dynamic DNS integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import CloudflareApiError, CloudflareAuthError, CloudflareClient
from .const import (
    CONF_API_TOKEN,
    CONF_DOMAIN_NAME,
    CONF_NOTIFY_EVENT,
    CONF_NOTIFY_PERSISTENT,
    CONF_NOTIFY_TARGETS,
    CONF_RECORD_NAME,
    CONF_RECORD_TYPE,
    CONF_RECORDS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_NOTIFY_EVENT,
    DEFAULT_NOTIFY_PERSISTENT,
    DEFAULT_NOTIFY_TARGETS,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    EVENT_DNS_UPDATED,
    IPV4_LOOKUP_URLS,
    IPV6_LOOKUP_URLS,
    STATUS_ERROR,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_UPDATED,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _record_key(domain: str, name: str, record_type: str) -> str:
    return f"{domain}|{name}|{record_type}"


def _fqdn(domain: str, name: str) -> str:
    """Build the full record name Cloudflare uses (@/empty means the zone root)."""
    name = (name or "").strip()
    if name in ("", "@"):
        return domain
    return f"{name}.{domain}"


class CloudflareDnsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that checks the external IP and updates Cloudflare DNS records."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        minutes = entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self._session = async_get_clientsession(hass)
        self.client = CloudflareClient(
            hass,
            self._session,
            entry.data[CONF_API_TOKEN],
        )
        # History of external IPs and per-record IPs, kept across restarts.
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )
        self._ip_history: dict[str, dict[str, str | None]] = {}
        self._record_history: dict[str, dict[str, str | None]] = {}

    @property
    def records(self) -> list[dict[str, str]]:
        """Return the configured records (domain / name / record_type)."""
        return self.entry.options.get(CONF_RECORDS, [])

    async def async_load_history(self) -> None:
        """Load the stored IP history; call once before the first refresh."""
        stored = await self._store.async_load() or {}
        self._ip_history = stored.get("ip_history", {})
        self._record_history = stored.get("record_history", {})

    async def _async_save_history(self) -> None:
        await self._store.async_save(
            {"ip_history": self._ip_history, "record_history": self._record_history}
        )

    def _track_ip(self, ip_type: str, ip: str | None, now: str) -> bool:
        """Remember the current IP and move the old one to 'previous'.

        Returns True when the address changed, so the caller can persist it.
        """
        if ip is None:
            return False
        entry = self._ip_history.setdefault(ip_type, {})
        if entry.get("current") == ip:
            return False
        if entry.get("current"):
            entry["previous"] = entry["current"]
            entry["changed_at"] = now
        entry["current"] = ip
        return True

    def _track_record(self, key: str, old_ip: str | None, now: str) -> None:
        """Remember the IP a record held before it was updated."""
        if not old_ip:
            return
        self._record_history[key] = {"previous": old_ip, "changed_at": now}

    async def _notify_updated(
        self, domain: str, name: str, rtype: str, old_ip: str | None, new_ip: str
    ) -> None:
        """Notify the user that a DNS record was updated, per options."""
        options = self.entry.options
        record_label = f"{name}.{domain}" if name not in ("", "@") else domain
        message = (
            f"{record_label} ({rtype}) is bijgewerkt naar {new_ip}"
            + (f" (was {old_ip})" if old_ip else "")
        )

        if options.get(CONF_NOTIFY_EVENT, DEFAULT_NOTIFY_EVENT):
            self.hass.bus.async_fire(
                EVENT_DNS_UPDATED,
                {
                    "domain": domain,
                    "name": name,
                    "type": rtype,
                    "old_ip": old_ip,
                    "new_ip": new_ip,
                },
            )

        if options.get(CONF_NOTIFY_PERSISTENT, DEFAULT_NOTIFY_PERSISTENT):
            persistent_notification.async_create(
                self.hass,
                message,
                title="Cloudflare DNS bijgewerkt",
                notification_id=f"{DOMAIN}_{_record_key(domain, name, rtype)}",
            )

        for target in options.get(CONF_NOTIFY_TARGETS, DEFAULT_NOTIFY_TARGETS):
            try:
                await self.hass.services.async_call(
                    "notify",
                    target,
                    {"message": message, "title": "Cloudflare DNS bijgewerkt"},
                    blocking=False,
                )
            except Exception as err:  # noqa: BLE001 - one bad target shouldn't break the rest
                _LOGGER.warning(
                    "Kon geen notificatie sturen via notify.%s: %s", target, err
                )

    async def _async_lookup_ip(self, urls: list[str]) -> str | None:
        for url in urls:
            try:
                async with self._session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    ip = data.get("ip")
                    if ip:
                        return ip
            except Exception as err:  # noqa: BLE001 - best effort, try next url
                _LOGGER.debug("IP lookup via %s failed: %s", url, err)
        return None

    def _with_history(
        self, ipv4: str | None, ipv6: str | None, results: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge the tracked history into the data exposed to the entities."""
        for key, record in results.items():
            history = self._record_history.get(key, {})
            record["previous_ip"] = history.get("previous")
            record["previous_changed_at"] = history.get("changed_at")

        data: dict[str, Any] = {"ipv4": ipv4, "ipv6": ipv6, "records": results}
        for ip_type in ("ipv4", "ipv6"):
            history = self._ip_history.get(ip_type, {})
            data[f"{ip_type}_previous"] = history.get("previous")
            data[f"{ip_type}_changed_at"] = history.get("changed_at")
        return data

    async def _async_update_data(self) -> dict[str, Any]:
        records = self.records
        now = dt_util.utcnow().isoformat()

        if not records:
            # Without records we still report the external IP, so the sensors
            # stay useful for anyone who only wants to watch their IP.
            ipv4 = await self._async_lookup_ip(IPV4_LOOKUP_URLS)
            ipv6 = await self._async_lookup_ip(IPV6_LOOKUP_URLS)
            if self._track_ip("ipv4", ipv4, now) | self._track_ip("ipv6", ipv6, now):
                await self._async_save_history()
            return self._with_history(ipv4, ipv6, {})

        needs_v4 = any(r[CONF_RECORD_TYPE] == "A" for r in records)
        needs_v6 = any(r[CONF_RECORD_TYPE] == "AAAA" for r in records)

        ipv4 = await self._async_lookup_ip(IPV4_LOOKUP_URLS) if needs_v4 else None
        ipv6 = await self._async_lookup_ip(IPV6_LOOKUP_URLS) if needs_v6 else None

        if needs_v4 and not ipv4:
            raise UpdateFailed("Could not determine external IPv4 address")
        if needs_v6 and not ipv6:
            raise UpdateFailed("Could not determine external IPv6 address")

        if self._track_ip("ipv4", ipv4, now) | self._track_ip("ipv6", ipv6, now):
            await self._async_save_history()

        # Resolve zone names -> zone ids once per cycle.
        try:
            zones = await self.client.async_list_zones()
        except CloudflareAuthError as err:
            raise UpdateFailed(f"Cloudflare authentication failed: {err}") from err
        except CloudflareApiError as err:
            raise UpdateFailed(f"Could not fetch Cloudflare zones: {err}") from err
        zone_ids = {z["name"]: z["id"] for z in zones}

        # Group requested records by domain (zone) to minimise GET calls.
        domains: dict[str, list[dict[str, str]]] = {}
        for rec in records:
            domains.setdefault(rec[CONF_DOMAIN_NAME], []).append(rec)

        results: dict[str, Any] = {}
        records_changed = False

        for domain, recs in domains.items():
            zone_id = zone_ids.get(domain)
            if zone_id is None:
                _LOGGER.warning(
                    "Zone '%s' not found in this Cloudflare account (or the API "
                    "token has no access to it)",
                    domain,
                )
                for rec in recs:
                    key = _record_key(
                        domain, rec[CONF_RECORD_NAME], rec[CONF_RECORD_TYPE]
                    )
                    results[key] = {
                        "domain": domain,
                        "name": rec[CONF_RECORD_NAME],
                        "type": rec[CONF_RECORD_TYPE],
                        "ip": None,
                        "status": STATUS_ERROR,
                        "error": "zone not found or not accessible",
                    }
                continue

            try:
                entries = await self.client.async_list_dns_records(zone_id)
            except CloudflareApiError as err:
                for rec in recs:
                    key = _record_key(
                        domain, rec[CONF_RECORD_NAME], rec[CONF_RECORD_TYPE]
                    )
                    results[key] = {
                        "domain": domain,
                        "name": rec[CONF_RECORD_NAME],
                        "type": rec[CONF_RECORD_TYPE],
                        "ip": None,
                        "status": STATUS_ERROR,
                        "error": str(err),
                    }
                continue

            for rec in recs:
                name = rec[CONF_RECORD_NAME]
                rtype = rec[CONF_RECORD_TYPE]
                key = _record_key(domain, name, rtype)
                fqdn = _fqdn(domain, name)
                desired_ip = ipv4 if rtype == "A" else ipv6

                match = next(
                    (
                        e
                        for e in entries
                        if e.get("name") == fqdn and e.get("type") == rtype
                    ),
                    None,
                )

                if match is None:
                    _LOGGER.warning(
                        "No existing %s record named '%s' found in Cloudflare zone "
                        "'%s' - create it once in the Cloudflare dashboard, it will "
                        "then be kept up to date automatically",
                        rtype,
                        fqdn,
                        domain,
                    )
                    results[key] = {
                        "domain": domain,
                        "name": name,
                        "type": rtype,
                        "ip": desired_ip,
                        "status": STATUS_NOT_FOUND,
                    }
                    continue

                if match.get("content") == desired_ip:
                    results[key] = {
                        "domain": domain,
                        "name": name,
                        "type": rtype,
                        "ip": desired_ip,
                        "status": STATUS_OK,
                    }
                    continue

                try:
                    await self.client.async_update_dns_record(
                        zone_id, match["id"], desired_ip
                    )
                except CloudflareApiError as err:
                    _LOGGER.error(
                        "Failed to update %s record '%s' in zone '%s': %s",
                        rtype,
                        fqdn,
                        domain,
                        err,
                    )
                    results[key] = {
                        "domain": domain,
                        "name": name,
                        "type": rtype,
                        "ip": match.get("content"),
                        "status": STATUS_ERROR,
                        "error": str(err),
                    }
                else:
                    _LOGGER.info(
                        "Updated %s record '%s' in zone '%s' to %s",
                        rtype,
                        fqdn,
                        domain,
                        desired_ip,
                    )
                    await self._notify_updated(
                        domain, name, rtype, match.get("content"), desired_ip
                    )
                    self._track_record(key, match.get("content"), now)
                    records_changed = True
                    results[key] = {
                        "domain": domain,
                        "name": name,
                        "type": rtype,
                        "ip": desired_ip,
                        "status": STATUS_UPDATED,
                        "last_updated": now,
                    }

        if records_changed:
            await self._async_save_history()

        return self._with_history(ipv4, ipv6, results)
