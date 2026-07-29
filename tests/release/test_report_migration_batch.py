from __future__ import annotations

from tmp.report_migration import build_operations
from tmp.report_migration.hierarchy_plan import (
    EXISTING_IDS,
    HYPOTHESIS_CHAPTER,
)
from tmp.report_migration.part_a_ids import PART_A_IDS


def _component(component_id: str) -> dict[str, object]:
    return {
        "component_id": component_id, "title": component_id,
        "body": "", "content": None, "display_kind": "",
    }


def test_builder_preserves_system_chapter_and_emits_one_atomic_batch(
    monkeypatch,
) -> None:
    remaining = sorted(EXISTING_IDS - set(PART_A_IDS))
    payload = {
        "components": [
            *[_component(item) for item in PART_A_IDS],
            *[_component(item) for item in remaining],
        ],
    }
    monkeypatch.setattr(build_operations, "migrate_a", dict)
    monkeypatch.setattr(build_operations, "migrate_b", dict)

    result = build_operations.build(payload)
    operations = result["operations"]
    replacements = [item for item in operations if item["op"] == "replace"]

    assert len(payload["components"]) == 64
    assert len(operations) == 150
    assert len(replacements) == 63
    assert {item["component_id"] for item in replacements} == EXISTING_IDS
    assert all(item["component_id"] != HYPOTHESIS_CHAPTER for item in replacements)
    assert all("bindings" not in item for item in operations)
    assert result["resume_node_chapter"] == {
        "node_id": "hypothesis_preregistration",
        "component_id": HYPOTHESIS_CHAPTER,
        "title": "假设登记",
    }
