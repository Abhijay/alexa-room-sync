"""Sensors describing the last sync run."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import AlexaRoomSync, AlexaRoomSyncConfigEntry
from .entity import AlexaRoomSyncEntity
from .reconcile import Action

STATES = ["idle", "in_sync", "dry_run", "applied", "error"]


async def async_setup_entry(
    hass: HomeAssistant, entry: AlexaRoomSyncConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensors."""
    sync = entry.runtime_data
    async_add_entities([StatusSensor(sync), PendingChangesSensor(sync), UnmatchedSensor(sync), LastRunSensor(sync)])


def describe(action: Action) -> str:
    """One readable line per planned Alexa write."""
    if action.type == "create":
        return f'Create "{action.name}" with {len(action.appliance_ids)} device(s)'
    before = set(action.previous_appliance_ids or [])
    after = set(action.appliance_ids)
    parts = []
    if action.previous_name != action.name:
        parts.append(f'rename "{action.previous_name}" to "{action.name}"')
    if added := len(after - before):
        parts.append(f"add {added}")
    if removed := len(before - after):
        parts.append(f"remove {removed}")
    return f'Update "{action.name}": {", ".join(parts)}'


class StatusSensor(AlexaRoomSyncEntity, SensorEntity):
    """What the last run decided."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATES
    _attr_icon = "mdi:home-group"

    def __init__(self, sync: AlexaRoomSync) -> None:
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


class PendingChangesSensor(AlexaRoomSyncEntity, SensorEntity):
    """How many Alexa writes the last plan wanted, with each spelled out."""

    _attr_icon = "mdi:playlist-edit"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, sync: AlexaRoomSync) -> None:
        """Set up."""
        super().__init__(sync, "pending_changes")

    @property
    def native_value(self) -> int | None:
        """Return the count of planned writes."""
        return len(self.sync.last_plan.actions) if self.sync.last_plan else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List each change in words."""
        plan = self.sync.last_plan
        return {"changes": [describe(a) for a in plan.actions] if plan else []}


class UnmatchedSensor(AlexaRoomSyncEntity, SensorEntity):
    """Alexa devices with no same-named object in Home Assistant."""

    _attr_icon = "mdi:link-off"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, sync: AlexaRoomSync) -> None:
        """Set up."""
        super().__init__(sync, "unmatched_devices")

    @property
    def native_value(self) -> int | None:
        """Return the count of unmatched Alexa devices."""
        return len(self.sync.last_plan.unmatched) if self.sync.last_plan else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Split Echos from everything else so it is clear what to name in HA."""
        plan = self.sync.last_plan
        if not plan:
            return {}
        return {
            "echos": sorted(e.name for e in plan.unmatched if e.is_echo),
            "devices": sorted(e.name for e in plan.unmatched if not e.is_echo),
            "matched": len(plan.matched),
        }


class LastRunSensor(AlexaRoomSyncEntity, SensorEntity):
    """When the last run happened and, if it failed, why."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, sync: AlexaRoomSync) -> None:
        """Set up."""
        super().__init__(sync, "last_run")

    @property
    def native_value(self) -> datetime | None:
        """Return the last run time."""
        return dt_util.parse_datetime(self.sync.last_run) if self.sync.last_run else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Carry the error text."""
        return {"error": self.sync.last_error}
