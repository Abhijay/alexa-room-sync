"""Dry-run switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AlexaRoomSyncConfigEntry
from .entity import AlexaRoomSyncEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AlexaRoomSyncConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the switch."""
    async_add_entities([DryRunSwitch(entry.runtime_data)])


class DryRunSwitch(AlexaRoomSyncEntity, SwitchEntity):
    """On: plan only. Off: write to Alexa."""

    _attr_icon = "mdi:shield-check"

    def __init__(self, sync) -> None:
        """Set up."""
        super().__init__(sync, "dry_run")

    @property
    def is_on(self) -> bool:
        """Return the persisted flag."""
        return self.sync.dry_run

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Stop writing."""
        await self.sync.set_dry_run(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Start writing."""
        await self.sync.set_dry_run(False)
