"""Alexa Room Sync: Home Assistant areas become Alexa rooms."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import AlexaRoomSync, AlexaRoomSyncConfigEntry
from .panel import async_register_panel, async_remove_panel

PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: AlexaRoomSyncConfigEntry) -> bool:
    """Set up from a config entry."""
    sync = AlexaRoomSync(hass, entry)
    await sync.start()
    entry.runtime_data = sync
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_panel(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AlexaRoomSyncConfigEntry) -> bool:
    """Unload a config entry."""
    async_remove_panel(hass)
    await entry.runtime_data.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
