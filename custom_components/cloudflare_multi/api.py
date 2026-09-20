"""Minimal async Cloudflare REST API (v4) client.

Only implements what this integration needs: verifying an API token,
listing zones (domains) and reading/updating DNS records.

Authentication uses a Cloudflare API Token (Bearer). Create one in the
Cloudflare dashboard under My Profile > API Tokens with permissions
Zone > DNS > Edit (and Zone > Zone > Read) for the zones you want to manage.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant

from .const import (
    API_BASE_URL,
    API_DNS_PATH,
    API_DNS_RECORD_PATH,
    API_VERIFY_PATH,
    API_ZONES_PATH,
)

_LOGGER = logging.getLogger(__name__)


class CloudflareApiError(Exception):
    """Raised when the Cloudflare API returns an error response."""


class CloudflareAuthError(CloudflareApiError):
    """Raised when authentication with Cloudflare fails."""


class CloudflareClient:
    """Thin async wrapper around the Cloudflare REST API v4."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        api_token: str,
    ) -> None:
        self._hass = hass
        self._session = session
        self._api_token = api_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, *, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Perform a request and return the parsed JSON, raising on errors."""
        url = f"{API_BASE_URL}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        try:
            async with self._session.request(
                method, url, data=data, headers=self._headers()
            ) as resp:
                text = await resp.text()
                payload = json.loads(text) if text else {}
                if resp.status in (401, 403):
                    raise CloudflareAuthError(
                        f"Authentication failed ({resp.status}): "
                        f"{_error_detail(payload) or text}"
                    )
                if resp.status < 200 or resp.status >= 300 or not payload.get(
                    "success", False
                ):
                    raise CloudflareApiError(
                        f"Cloudflare API error ({resp.status}) on {method} {path}: "
                        f"{_error_detail(payload) or text}"
                    )
                return payload
        except aiohttp.ClientError as err:
            raise CloudflareApiError(
                f"Error contacting Cloudflare API: {err}"
            ) from err

    async def async_verify_token(self) -> str:
        """Verify the API token is valid and active.

        Returns the token id (usable as a stable unique id). Raises
        CloudflareAuthError when the token is not active.
        """
        payload = await self._request("GET", API_VERIFY_PATH)
        result = payload.get("result") or {}
        if result.get("status") != "active":
            raise CloudflareAuthError(
                f"API token is not active (status: {result.get('status')})"
            )
        return str(result.get("id") or "")

    async def async_list_zones(self) -> list[dict[str, str]]:
        """Return all zones (domains) the token can see: [{id, name}]."""
        zones: list[dict[str, str]] = []
        page = 1
        while True:
            payload = await self._request(
                "GET", f"{API_ZONES_PATH}?per_page=50&page={page}"
            )
            for zone in payload.get("result", []):
                if "id" in zone and "name" in zone:
                    zones.append({"id": zone["id"], "name": zone["name"]})
            info = payload.get("result_info") or {}
            total_pages = info.get("total_pages", 1) or 1
            if page >= total_pages:
                break
            page += 1
        return zones

    async def async_list_dns_records(
        self,
        zone_id: str,
        name: str | None = None,
        rtype: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return DNS records for a zone, optionally filtered by name/type."""
        query = ["per_page=100"]
        if name:
            query.append(f"name={name}")
        if rtype:
            query.append(f"type={rtype}")
        path = API_DNS_PATH.format(zone_id=zone_id) + "?" + "&".join(query)
        payload = await self._request("GET", path)
        return payload.get("result", [])

    async def async_update_dns_record(
        self, zone_id: str, record_id: str, content: str
    ) -> None:
        """Update the content (IP) of a single existing DNS record.

        Uses PATCH so that other properties (ttl, proxied, comment) are left
        untouched.
        """
        path = API_DNS_RECORD_PATH.format(zone_id=zone_id, record_id=record_id)
        await self._request("PATCH", path, body={"content": content})


def _error_detail(payload: dict[str, Any]) -> str:
    """Extract a human-readable message from a Cloudflare error payload."""
    errors = payload.get("errors") or []
    parts = []
    for err in errors:
        code = err.get("code")
        message = err.get("message")
        if code and message:
            parts.append(f"{message} (code {code})")
        elif message:
            parts.append(str(message))
    return "; ".join(parts)
