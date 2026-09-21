"""Manual sync button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AlexaRoomSyncConfigEntry
from .entity import AlexaRoomSyncEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AlexaRoomSyncConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the button."""
    async_add_entities([SyncNowButton(entry.runtime_data)])


class SyncNowButton(AlexaRoomSyncEntity, ButtonEntity):
    """Run a reconcile pass immediately."""

    _attr_icon = "mdi:sync"

    def __init__(self, sync) -> None:
        """Set up."""
        super().__init__(sync, "sync_now")

    async def async_press(self) -> None:
        """Run."""
        await self.sync.run()
