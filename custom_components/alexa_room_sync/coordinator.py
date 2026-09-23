"""Runs the sync: snapshot HA, plan against Alexa, apply unless dry-run."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er, floor_registry as fr
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .alexa_client import AlexaGroupClient
from .const import (
    ALEXA_DEVICES_DOMAIN,
    DEBOUNCE_SECONDS,
    FALLBACK_INTERVAL_MINUTES,
    LOGGER,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .reconcile import HOME_KEY, AlexaEndpoint, AlexaGroup, HAObject, HARooms, Mappings, Plan, floor_key, reconcile

REGISTRY_EVENTS = (
    EVENT_CORE_CONFIG_UPDATE,
    ar.EVENT_AREA_REGISTRY_UPDATED,
    fr.EVENT_FLOOR_REGISTRY_UPDATED,
    dr.EVENT_DEVICE_REGISTRY_UPDATED,
    er.EVENT_ENTITY_REGISTRY_UPDATED,
)

type AlexaRoomSyncConfigEntry = ConfigEntry[AlexaRoomSync]


def _text(*candidates: Any) -> str | None:
    return next((c for c in candidates if isinstance(c, str) and c), None)


def snapshot_rooms(hass: HomeAssistant) -> HARooms:
    """Read areas, devices and entities the way Alexa will see them: by name."""
    area_entries = ar.async_get(hass).async_list_areas()
    areas = {area.id: area.name for area in area_entries}
    area_aliases = {area.id: sorted(area.aliases) for area in area_entries if area.aliases}
    area_floor = {area.id: area.floor_id for area in area_entries if area.floor_id}
    floor_entries = fr.async_get(hass).async_list_floors()
    floors = {floor.floor_id: floor.name for floor in floor_entries}
    floor_aliases = {floor.floor_id: sorted(floor.aliases) for floor in floor_entries if floor.aliases}
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    objects: list[HAObject] = []

    for entry in entity_registry.entities.values():
        if entry.disabled_by or entry.hidden_by:
            continue
        device = device_registry.async_get(entry.device_id) if entry.device_id else None
        state = hass.states.get(entry.entity_id)
        # Registry names can be a computed-name sentinel rather than text on recent releases.
        name = _text(state and state.attributes.get("friendly_name"), entry.name, entry.original_name)
        if not name:
            continue
        area_id = entry.area_id or (device.area_id if device else None)
        for alias in (name, *(a for a in entry.aliases if isinstance(a, str))):
            objects.append(HAObject("entity", entry.entity_id, alias, area_id))

    # Iterating yields entries since 2026.9; older releases yield ids.
    devices = [d for d in device_registry.devices if isinstance(d, dr.DeviceEntry)] or list(device_registry.devices.values())
    for device in devices:
        if device.disabled_by:
            continue
        name = _text(device.name_by_user, device.name)
        if name:
            objects.append(HAObject("device", device.id, name, device.area_id))

    return HARooms(areas, objects, area_aliases, floors, floor_aliases, area_floor, hass.config.location_name or None)


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
        self.last_rooms: HARooms | None = None
        self.last_endpoints: list[AlexaEndpoint] = []
        self.last_groups: list[AlexaGroup] = []
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
        # Friendly names come from entity states, which only exist once startup finishes.
        if self.hass.is_running:
            self._schedule_initial_run()
        else:
            self._unsubs.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_started))

    @callback
    def _on_started(self, _event: Event) -> None:
        self._schedule_initial_run()

    def _schedule_initial_run(self) -> None:
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
            step = "connecting to the Alexa Devices session"
            client = AlexaGroupClient(_alexa_api(self.hass))
            step = "reading Alexa devices"
            endpoints = await client.endpoints()
            step = "reading Alexa rooms"
            groups = await client.groups()
            step = "planning"
            rooms = snapshot_rooms(self.hass)
            plan = reconcile(rooms, endpoints, groups, self.mappings)
        except Exception as err:  # noqa: BLE001 - any failure must surface on the sensor, never crash HA
            self.status = "error"
            self.last_error = f"{step}: {err!r}"
            LOGGER.warning("Alexa room sync skipped, nothing written: %s", err)
            self._notify()
            return

        self.last_plan = plan
        self.last_rooms = rooms
        self.last_endpoints = endpoints
        self.last_groups = groups
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
        except Exception as err:  # noqa: BLE001
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

    def overview(self) -> dict[str, Any]:
        """Everything the panel shows: each HA area beside its Alexa room, plus what matched nothing."""
        base = {"status": self.status, "dry_run": self.dry_run, "last_run": self.last_run, "last_error": self.last_error}
        plan, rooms = self.last_plan, self.last_rooms
        if plan is None or rooms is None:
            return {**base, "home": None, "floors": [], "areas": [], "unmatched": [], "unmatched_echos": []}
        endpoint_name = {e.appliance_id: e.name for e in self.last_endpoints}
        group_by_id = {g.id: g for g in self.last_groups}
        action_by_area = {a.area_id: a for a in plan.actions}
        areas = []
        for area_id, area_name in rooms.areas.items():
            group = group_by_id.get(plan.mappings.groups.get(area_id, ""))
            action = action_by_area.get(area_id)
            members = [
                {"ha_name": obj.name, "ha_id": obj.id, "alexa_name": endpoint_name.get(aid, aid)}
                for aid, obj in plan.matched.items()
                if obj.area_id == area_id
            ]
            if action:
                state = action.type
            elif group is not None:
                state = "in_sync"
            else:
                state = "no_devices"
            areas.append(
                {
                    "area_id": area_id,
                    "name": area_name,
                    "aliases": rooms.area_aliases.get(area_id, []),
                    "alexa_group": group.name if group else None,
                    "state": state,
                    "members": sorted(members, key=lambda m: m["ha_name"].lower()),
                    "unmanaged": [
                        endpoint_name.get(aid, "unknown device")
                        for aid in (group.appliance_ids if group else [])
                        if aid not in plan.matched
                    ],
                }
            )
        floors = []
        for floor_id, floor_name in rooms.floors.items():
            key = floor_key(floor_id)
            group = group_by_id.get(plan.mappings.groups.get(key, ""))
            action = action_by_area.get(key)
            floor_areas = sorted(a["name"] for a in areas if rooms.area_floor.get(a["area_id"]) == floor_id)
            member_count = sum(len(a["members"]) for a in areas if rooms.area_floor.get(a["area_id"]) == floor_id)
            floors.append(
                {
                    "floor_id": floor_id,
                    "name": floor_name,
                    "aliases": rooms.floor_aliases.get(floor_id, []),
                    "alexa_group": group.name if group else None,
                    "state": action.type if action else "in_sync" if group else "no_devices",
                    "areas": floor_areas,
                    "member_count": member_count,
                    "unmanaged": [
                        endpoint_name.get(aid, "unknown device")
                        for aid in (group.appliance_ids if group else [])
                        if aid not in plan.matched
                    ],
                }
            )
        home = None
        if rooms.home_name:
            group = group_by_id.get(plan.mappings.groups.get(HOME_KEY, ""))
            action = action_by_area.get(HOME_KEY)
            home = {
                "name": rooms.home_name,
                "alexa_group": group.name if group else None,
                "state": action.type if action else "in_sync" if group else "no_devices",
                "member_count": len(plan.matched),
                "unmanaged": [
                    endpoint_name.get(aid, "unknown device")
                    for aid in (group.appliance_ids if group else [])
                    if aid not in plan.matched
                ],
            }
        return {
            **base,
            "home": home,
            "floors": sorted(floors, key=lambda f: f["name"].lower()),
            "areas": sorted(areas, key=lambda a: a["name"].lower()),
            "unmatched": sorted(e.name for e in plan.unmatched if not e.is_echo),
            "unmatched_echos": sorted(e.name for e in plan.unmatched if e.is_echo),
        }
