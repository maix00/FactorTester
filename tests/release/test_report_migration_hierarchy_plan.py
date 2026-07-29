from __future__ import annotations

from tmp.report_migration.hierarchy_plan import (
    CONTENT_IDS,
    DETOUR_CHILDREN,
    EXISTING_IDS,
    NEW_IDS,
    SECTIONS,
    hierarchy_operations,
)
from tmp.report_migration.detour_entries import SPECIAL_ID, TRANSITIONS


def test_historical_plan_assigns_every_content_once() -> None:
    section_items = [
        component_id
        for section in SECTIONS
        for component_id in section["component_ids"]
    ]

    assert len(EXISTING_IDS) == 63
    assert len(NEW_IDS) == 6
    assert len(section_items) == len(set(section_items))
    assert (
        set(section_items) | set(DETOUR_CHILDREN) | {SPECIAL_ID}
        == CONTENT_IDS
    )
    assert set(section_items).isdisjoint(DETOUR_CHILDREN)
    assert EXISTING_IDS | NEW_IDS == CONTENT_IDS
    assert len(TRANSITIONS) == 5


def test_historical_plan_builds_stable_sections_and_moves() -> None:
    operations = hierarchy_operations()
    adds = [item for item in operations if item["op"] == "add"]
    binds = [item for item in operations if item["op"] == "bind"]
    moves = [item for item in operations if item["op"] == "move"]

    assert len(adds) == 17
    assert len(moves) == 69
    assert sum(item["kind"] == "section" for item in adds) == 11
    assert sum(item["kind"] == "entry" for item in adds) == 6
    assert len(binds) == 1
    assert binds[0]["component_id"] == (
        "profile-screen-alias-capability-resolution"
    )
    assert binds[0]["binding"]["target_ref"] == (
        "capability-detour:2617faa42d3945489aa3cf1381528f85"
    )
    assert binds[0]["binding"]["data"]["role"] == "capability_detour"
    assert all("bindings" not in item for item in operations)
    assert adds[0]["parent_id"] == "chapter-d1879f52260d49e258f652f2"
    assert adds[10]["parent_id"] == "chapter-d1879f52260d49e258f652f2"
    assert adds[-1]["parent_id"] == (
        "profile-screen-alias-capability-resolution"
    )
    assert {
        item["component_id"]: item for item in moves
    }["profile-screen-alias-capability-resolution"] == {
        "op": "move",
        "component_id": "profile-screen-alias-capability-resolution",
        "parent_id": "chapter-d1879f52260d49e258f652f2",
        "after_component_id": "section-gap-entry-evidence",
    }
    assert not any(
        item.get("component_id") == "section-capability-detour"
        for item in operations
    )
    assert moves[-1] == {
        "op": "move",
        "component_id": "capability-detour-current-open-gap",
        "parent_id": "profile-screen-alias-capability-resolution",
        "after_component_id": "capability-detour-transition-5",
    }
