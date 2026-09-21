"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import AlexaRoomSync


class AlexaRoomSyncEntity(Entity):
    """Entity bound to the sync runner, re-rendered after every run."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, sync: AlexaRoomSync, key: str) -> None:
        """Bind to the runner."""
        self.sync = sync
        self._attr_translation_key = key
        self._attr_unique_id = f"{sync.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sync.entry.entry_id)},
            name="Alexa Room Sync",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to run completions."""
        self.async_on_remove(self.sync.async_add_listener(self.async_write_ha_state))
