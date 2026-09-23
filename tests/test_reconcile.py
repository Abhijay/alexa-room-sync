import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "alexa_room_sync"))

from reconcile import (  # noqa: E402
    floor_key,
    Action,
    AlexaEndpoint,
    AlexaGroup,
    AmbiguousMatchError,
    EmptyInventoryError,
    HAObject,
    HARooms,
    Mappings,
    reconcile,
)

AREAS = {"living": "Living Room", "bed": "Bedroom"}
OBJECTS = [
    HAObject("entity", "light.ceiling", "Ceiling", "living"),
    HAObject("entity", "light.lamp", "Floor Lamp", "bed"),
    HAObject("device", "d1", "Ceiling", "living"),
    HAObject("device", "echo1", "Living Room Echo", "living"),
]
ROOMS = HARooms(AREAS, OBJECTS)


def test_creates_rooms_and_adopts_existing_groups_by_name():
    endpoints = [
        AlexaEndpoint("A1", "Ceiling"),
        AlexaEndpoint("A2", "Floor Lamp"),
        AlexaEndpoint("E1", "Living Room Echo", is_echo=True),
        AlexaEndpoint("X", "Unknown Plug"),
    ]
    groups = [AlexaGroup("G-bed", "Bedroom", ["OTHER"])]
    plan = reconcile(ROOMS, endpoints, groups, Mappings())
    assert plan.actions == [
        Action("create", "living", "Living Room", ["A1", "E1"]),
        Action("update", "bed", "Bedroom", ["A2", "OTHER"], group_id="G-bed", previous_name="Bedroom", previous_appliance_ids=["OTHER"]),
    ]
    assert [e.name for e in plan.unmatched] == ["Unknown Plug"]
    assert plan.mappings.groups["bed"] == "G-bed"
    assert plan.mappings.appliances["A1"] == {"kind": "entity", "id": "light.ceiling", "name": "Ceiling"}


def test_noop_when_alexa_matches():
    endpoints = [AlexaEndpoint("A1", "Ceiling"), AlexaEndpoint("A2", "Floor Lamp")]
    groups = [AlexaGroup("G1", "Living Room", ["A1"]), AlexaGroup("G2", "Bedroom", ["A2"])]
    assert reconcile(ROOMS, endpoints, groups, Mappings()).actions == []


def test_follows_rename_and_move_through_mappings():
    rooms = HARooms(
        {"living": "Lounge", "bed": "Bedroom"},
        [HAObject("entity", "light.ceiling", "Ceiling", "bed"), HAObject("entity", "light.lamp", "Floor Lamp", "bed")],
    )
    endpoints = [AlexaEndpoint("A1", "Renamed In Alexa"), AlexaEndpoint("A2", "Floor Lamp")]
    groups = [AlexaGroup("G1", "Living Room", ["A1"]), AlexaGroup("G2", "Bedroom", ["A2"])]
    mappings = Mappings({"A1": {"kind": "entity", "id": "light.ceiling"}}, {"living": "G1", "bed": "G2"})
    plan = reconcile(rooms, endpoints, groups, mappings)
    assert [(a.group_id, a.name, a.appliance_ids) for a in plan.actions] == [
        ("G1", "Lounge", []),
        ("G2", "Bedroom", ["A1", "A2"]),
    ]


def test_refuses_ambiguous_names_and_empty_inventory():
    rooms = HARooms(AREAS, [*OBJECTS, HAObject("entity", "light.ceiling2", "Ceiling", "bed")])
    with pytest.raises(AmbiguousMatchError):
        reconcile(rooms, [AlexaEndpoint("A1", "Ceiling")], [], Mappings())
    with pytest.raises(EmptyInventoryError):
        reconcile(ROOMS, [], [], Mappings())


def test_warns_instead_of_deleting_when_area_disappears():
    rooms = HARooms({"bed": "Bedroom"}, OBJECTS)
    groups = [AlexaGroup("G1", "Living Room", ["A1"])]
    plan = reconcile(rooms, [AlexaEndpoint("A1", "Ceiling")], groups, Mappings(groups={"living": "G1"}))
    assert "left in place" in plan.warnings[0]
    assert plan.mappings.groups["living"] == "G1"


def test_does_not_touch_members_it_does_not_manage():
    groups = [AlexaGroup("G1", "Living Room", ["A1", "NATIVE"])]
    plan = reconcile(ROOMS, [AlexaEndpoint("A1", "Ceiling"), AlexaEndpoint("A2", "Floor Lamp")], groups, Mappings())
    create_bed, = [a for a in plan.actions if a.type == "create"]
    assert create_bed.appliance_ids == ["A2"]
    assert not [a for a in plan.actions if a.group_id == "G1"]


def test_entity_alias_and_area_alias_match():
    rooms = HARooms(
        {"a1": "Lounge"},
        [HAObject("entity", "light.x", "Big Lamp", "a1"), HAObject("entity", "light.x", "Floor Lamp", "a1")],
        {"a1": ["Living Room"]},
    )
    endpoints = [AlexaEndpoint("app1", "Floor Lamp")]
    groups = [AlexaGroup("g1", "Living Room", ["app1"])]
    plan = reconcile(rooms, endpoints, groups, Mappings())
    assert plan.matched["app1"].id == "light.x"
    assert plan.mappings.groups["a1"] == "g1"
    assert [a.type for a in plan.actions] == ["update"]
    assert plan.actions[0].name == "Lounge"


def test_floor_groups_union_their_areas():
    rooms = HARooms(
        {"a1": "Kitchen", "a2": "Den", "a3": "Attic"},
        [
            HAObject("entity", "light.k", "K Light", "a1"),
            HAObject("entity", "light.d", "D Light", "a2"),
            HAObject("entity", "light.a", "A Light", "a3"),
        ],
        floors={"f1": "Common Spaces"},
        area_floor={"a1": "f1", "a2": "f1"},
    )
    endpoints = [AlexaEndpoint("k", "K Light"), AlexaEndpoint("d", "D Light"), AlexaEndpoint("a", "A Light")]
    plan = reconcile(rooms, endpoints, [], Mappings())
    floor = next(a for a in plan.actions if a.area_id == floor_key("f1"))
    assert floor.type == "create"
    assert floor.name == "Common Spaces"
    assert floor.appliance_ids == ["d", "k"]
    assert len(plan.actions) == 4
