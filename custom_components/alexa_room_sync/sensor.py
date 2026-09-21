"""Status sensor with the last plan as attributes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AlexaRoomSyncConfigEntry
from .entity import AlexaRoomSyncEntity

STATES = ["idle", "in_sync", "dry_run", "applied", "error"]


async def async_setup_entry(
    hass: HomeAssistant, entry: AlexaRoomSyncConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor."""
    async_add_entities([StatusSensor(entry.runtime_data)])


class StatusSensor(AlexaRoomSyncEntity, SensorEntity):
    """What the last run decided."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATES
    _attr_icon = "mdi:home-group"

    def __init__(self, sync) -> None:
        """Set up."""
        super().__init__(sync, "status")

    @property
    def native_value(self) -> str:
        """Return the run outcome."""
        return self.sync.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return plan details."""
        return self.sync.plan_attributes()
