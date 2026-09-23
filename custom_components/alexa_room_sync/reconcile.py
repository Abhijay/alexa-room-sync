"""Pure reconciliation of Home Assistant areas against Alexa groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class AmbiguousMatchError(Exception):
    """A name maps to Home Assistant objects in more than one area."""


class EmptyInventoryError(Exception):
    """Alexa returned no smart-home endpoints."""


@dataclass(frozen=True)
class HAObject:
    """An entity or device as Home Assistant names it, with its area."""

    kind: str
    id: str
    name: str
    area_id: str | None


@dataclass(frozen=True)
class HARooms:
    """Snapshot of the Home Assistant registries the sync cares about."""

    areas: dict[str, str]
    objects: list[HAObject]
    area_aliases: dict[str, list[str]] = field(default_factory=dict)
    floors: dict[str, str] = field(default_factory=dict)
    floor_aliases: dict[str, list[str]] = field(default_factory=dict)
    area_floor: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AlexaEndpoint:
    """A smart-home endpoint as Alexa lists it."""

    appliance_id: str
    name: str
    is_echo: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class AlexaGroup:
    """An Alexa room or device group."""

    id: str
    name: str
    appliance_ids: list[str]


@dataclass
class Mappings:
    """Identity links between the two systems. Never decides membership."""

    appliances: dict[str, dict[str, str]] = field(default_factory=dict)
    groups: dict[str, str] = field(default_factory=dict)  # keyed by area id, or "floor:<floor id>"

    def copy(self) -> Mappings:
        """Return a deep-enough copy for a new plan."""
        return Mappings({k: dict(v) for k, v in self.appliances.items()}, dict(self.groups))

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {"appliances": self.appliances, "groups": self.groups}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Mappings:
        """Deserialize from storage."""
        data = data or {}
        return cls(dict(data.get("appliances", {})), dict(data.get("groups", {})))


FLOOR_PREFIX = "floor:"


def floor_key(floor_id: str) -> str:
    """Mapping key for a floor's group, kept apart from area ids."""
    return f"{FLOOR_PREFIX}{floor_id}"


@dataclass(frozen=True)
class Action:
    """One Alexa write. area_id is the area id or a floor key."""

    type: str
    area_id: str
    name: str
    appliance_ids: list[str]
    group_id: str | None = None
    previous_name: str | None = None
    previous_appliance_ids: list[str] | None = None


@dataclass
class Plan:
    """Everything reconcile decided."""

    actions: list[Action]
    warnings: list[str]
    unmatched: list[AlexaEndpoint]
    matched: dict[str, HAObject]
    mappings: Mappings


def _norm(name: str) -> str:
    return " ".join(name.strip().lower().split())


def reconcile(
    rooms: HARooms,
    endpoints: list[AlexaEndpoint],
    groups: list[AlexaGroup],
    mappings: Mappings,
) -> Plan:
    """Compute the writes needed to make Alexa rooms mirror HA areas.

    Raises on anything ambiguous so a caller never writes on a half-understood picture.
    """
    if not endpoints:
        raise EmptyInventoryError("Alexa returned no smart-home endpoints")

    nxt = mappings.copy()
    object_by_key = {f"{o.kind}:{o.id}": o for o in rooms.objects}
    objects_by_name: dict[str, list[HAObject]] = {}
    for obj in rooms.objects:
        objects_by_name.setdefault(_norm(obj.name), []).append(obj)

    matched: dict[str, HAObject] = {}
    unmatched: list[AlexaEndpoint] = []
    ambiguous: list[str] = []
    for endpoint in endpoints:
        if not endpoint.enabled:
            continue
        mapped = nxt.appliances.get(endpoint.appliance_id)
        existing = object_by_key.get(f"{mapped['kind']}:{mapped['id']}") if mapped else None
        if existing:
            matched[endpoint.appliance_id] = existing
            continue
        candidates = objects_by_name.get(_norm(endpoint.name), [])
        if not candidates:
            unmatched.append(endpoint)
            continue
        if len({c.area_id for c in candidates}) > 1:
            where = ", ".join(f"{c.id} ({rooms.areas.get(c.area_id, 'no area')})" for c in candidates)
            ambiguous.append(f'"{endpoint.name}" matches HA objects in different areas: {where}')
            continue
        pick = next((c for c in candidates if c.kind == "entity"), candidates[0])
        nxt.appliances[endpoint.appliance_id] = {"kind": pick.kind, "id": pick.id, "name": pick.name}
        matched[endpoint.appliance_id] = pick
    if ambiguous:
        raise AmbiguousMatchError("Ambiguous name matches, fix in HA first:\n" + "\n".join(ambiguous))

    managed = set(matched)
    group_by_id = {g.id: g for g in groups}
    groups_by_name: dict[str, list[AlexaGroup]] = {}
    for group in groups:
        groups_by_name.setdefault(_norm(group.name), []).append(group)

    actions: list[Action] = []
    warnings: list[str] = []
    claimed: set[str] = set()

    def plan_group(key: str, name: str, aliases: list[str], members: list[str]) -> None:
        group = group_by_id.get(nxt.groups.get(key, ""))
        if group is None:
            by_name = [g for n in (name, *aliases) for g in groups_by_name.get(_norm(n), []) if g.id not in claimed]
            if len(by_name) > 1:
                raise AmbiguousMatchError(f'Alexa has {len(by_name)} groups named "{name}"; merge them in the Alexa app first')
            if by_name:
                group = by_name[0]
                nxt.groups[key] = group.id
        if group is not None:
            claimed.add(group.id)

        if group is None:
            if members:
                actions.append(Action("create", key, name, members))
            return
        preserved = [aid for aid in group.appliance_ids if aid not in managed]
        desired = sorted(set(preserved) | set(members))
        if group.name == name and desired == sorted(group.appliance_ids):
            return
        actions.append(
            Action(
                "update",
                key,
                name,
                desired,
                group_id=group.id,
                previous_name=group.name,
                previous_appliance_ids=list(group.appliance_ids),
            )
        )

    area_members = {
        area_id: sorted(aid for aid, obj in matched.items() if obj.area_id == area_id) for area_id in rooms.areas
    }
    for area_id, area_name in rooms.areas.items():
        plan_group(area_id, area_name, rooms.area_aliases.get(area_id, []), area_members[area_id])
    for floor_id, floor_name in rooms.floors.items():
        members = sorted({aid for area_id, fid in rooms.area_floor.items() if fid == floor_id for aid in area_members.get(area_id, [])})
        plan_group(floor_key(floor_id), floor_name, rooms.floor_aliases.get(floor_id, []), members)

    live_keys = set(rooms.areas) | {floor_key(f) for f in rooms.floors}
    for key, group_id in list(nxt.groups.items()):
        if key in live_keys:
            continue
        kind = "floor" if key.startswith(FLOOR_PREFIX) else "area"
        group = group_by_id.get(group_id)
        if group is None:
            warnings.append(f"Mapping for deleted {kind} {key} points at a group Alexa no longer has; dropping it")
            del nxt.groups[key]
        else:
            warnings.append(f'HA {kind} {key} was deleted; Alexa group "{group.name}" left in place for manual cleanup')

    return Plan(actions, warnings, unmatched, matched, nxt)
