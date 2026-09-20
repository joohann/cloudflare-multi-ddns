"""The Cloudflare Multi Dynamic DNS integration.

Watches your external IP address and, whenever it changes, updates the
matching A/AAAA DNS records across one or more Cloudflare zones (domains)
via the Cloudflare REST API v4, authenticated with an API Token.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import CloudflareDnsCoordinator

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cloudflare Multi Dynamic DNS from a config entry."""
    coordinator = CloudflareDnsCoordinator(hass, entry)
    await coordinator.async_load_history()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options (records, interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)
