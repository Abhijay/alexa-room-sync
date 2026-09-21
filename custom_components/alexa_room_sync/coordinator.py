"""Runs the sync: snapshot HA, plan against Alexa, apply unless dry-run."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import Any

from aioamazondevices.exceptions import AmazonError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .alexa_client import AlexaGroupClient, UnexpectedResponseError
from .const import (
    ALEXA_DEVICES_DOMAIN,
    DEBOUNCE_SECONDS,
    FALLBACK_INTERVAL_MINUTES,
    LOGGER,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .reconcile import (
    AmbiguousMatchError,
    EmptyInventoryError,
    HAObject,
    HARooms,
    Mappings,
    Plan,
    reconcile,
)

REGISTRY_EVENTS = (
    ar.EVENT_AREA_REGISTRY_UPDATED,
    dr.EVENT_DEVICE_REGISTRY_UPDATED,
    er.EVENT_ENTITY_REGISTRY_UPDATED,
)

type AlexaRoomSyncConfigEntry = ConfigEntry[AlexaRoomSync]


def snapshot_rooms(hass: HomeAssistant) -> HARooms:
    """Read areas, devices and entities the way Alexa will see them: by name."""
    areas = {area.id: area.name for area in ar.async_get(hass).async_list_areas()}
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    objects: list[HAObject] = []

    for entry in entity_registry.entities.values():
        if entry.disabled_by or entry.hidden_by:
            continue
        device = device_registry.async_get(entry.device_id) if entry.device_id else None
        state = hass.states.get(entry.entity_id)
        name = (state and state.attributes.get("friendly_name")) or entry.name or entry.original_name
        if not name:
            continue
        area_id = entry.area_id or (device.area_id if device else None)
        objects.append(HAObject("entity", entry.entity_id, name, area_id))

    for device in device_registry.devices.values():
        if device.disabled_by:
            continue
        name = device.name_by_user or device.name
        if name:
            objects.append(HAObject("device", device.id, name, device.area_id))

    return HARooms(areas, objects)


def _alexa_api(hass: HomeAssistant) -> Any:
    entries = [e for e in hass.config_entries.async_entries(ALEXA_DEVICES_DOMAIN) if getattr(e, "runtime_data", None) is not None]
    if not entries:
        raise ConfigEntryNotReady("The Alexa Devices integration is not loaded yet")
    api = getattr(entries[0].runtime_data, "api", None)
    if api is None or not hasattr(api, "_http_wrapper"):
        raise ConfigEntryNotReady("The Alexa Devices integration no longer exposes a usable Amazon session")
    return api


class AlexaRoomSync:
    """State and scheduling for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up storage and the debounced runner; nothing runs until start()."""
        self.hass = hass
        self.entry = entry
        self.store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.mappings = Mappings()
        self.dry_run = True
        self.status = "idle"
        self.last_plan: Plan | None = None
        self.last_error: str | None = None
        self.last_run: str | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._debouncer = Debouncer(hass, LOGGER, cooldown=DEBOUNCE_SECONDS, immediate=False, function=self.run)

    async def start(self) -> None:
        """Load state, verify the Amazon session exists, and begin watching registries."""
        data = await self.store.async_load() or {}
        self.mappings = Mappings.from_dict(data.get("mappings"))
        self.dry_run = data.get("dry_run", True)
        _alexa_api(self.hass)
        for event_type in REGISTRY_EVENTS:
            self._unsubs.append(self.hass.bus.async_listen(event_type, self._on_registry_event))
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_interval, timedelta(minutes=FALLBACK_INTERVAL_MINUTES))
        )
        self.entry.async_create_background_task(self.hass, self.run(), "alexa_room_sync initial run")

    async def stop(self) -> None:
        """Detach listeners."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._debouncer.async_shutdown()

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Let entities re-render when a run finishes."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    def _notify(self) -> None:
        for update in self._listeners:
            update()

    @callback
    def _on_registry_event(self, _event: Event) -> None:
        self.hass.async_create_task(self._debouncer.async_call())

    async def _on_interval(self, _now: Any) -> None:
        await self.run()

    async def set_dry_run(self, value: bool) -> None:
        """Persist the dry-run switch; a fresh run follows so the plan reflects it."""
        self.dry_run = value
        await self._save()
        self._notify()
        await self.run()

    async def _save(self) -> None:
        await self.store.async_save({"mappings": self.mappings.as_dict(), "dry_run": self.dry_run})

    async def run(self) -> None:
        """One reconcile pass. Any failure leaves Alexa untouched."""
        self.last_run = dt_util.utcnow().isoformat()
        try:
            client = AlexaGroupClient(_alexa_api(self.hass))
            endpoints = await client.endpoints()
            groups = await client.groups()
            plan = reconcile(snapshot_rooms(self.hass), endpoints, groups, self.mappings)
        except (AmbiguousMatchError, EmptyInventoryError, UnexpectedResponseError, AmazonError, ConfigEntryNotReady, ValueError) as err:
            self.status = "error"
            self.last_error = str(err)
            LOGGER.warning("Alexa room sync skipped, nothing written: %s", err)
            self._notify()
            return

        self.last_plan = plan
        self.last_error = None
        for warning in plan.warnings:
            LOGGER.warning("%s", warning)

        if self.dry_run:
            self.status = "dry_run" if plan.actions else "in_sync"
            self._notify()
            return

        try:
            for action in plan.actions:
                if action.type == "create":
                    group_id = await client.create_group(action.name, action.appliance_ids)
                    if group_id:
                        plan.mappings.groups[action.area_id] = group_id
                else:
                    await client.update_group(action.group_id, action.name, action.appliance_ids)
                LOGGER.info("Alexa room %s: %s", action.type, action.name)
        except (AmazonError, ValueError) as err:
            self.status = "error"
            self.last_error = f"Write failed at {action.name}: {err}"
            LOGGER.error("Alexa room sync write failed: %s", err)
        else:
            self.status = "applied" if plan.actions else "in_sync"
        self.mappings = plan.mappings
        await self._save()
        self._notify()

    def plan_attributes(self) -> dict[str, Any]:
        """Attributes for the status sensor."""
        plan = self.last_plan
        attrs: dict[str, Any] = {"dry_run": self.dry_run, "last_run": self.last_run, "last_error": self.last_error}
        if plan is None:
            return attrs
        attrs.update(
            {
                "matched": len(plan.matched),
                "unmatched": [e.name for e in plan.unmatched],
                "unmatched_echos": [e.name for e in plan.unmatched if e.is_echo],
                "warnings": plan.warnings,
                "actions": [asdict(a) for a in plan.actions],
            }
        )
        return attrs
