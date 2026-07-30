from __future__ import annotations

from tests.release.report_tree_fixtures import carrier, profile
from tests.release.test_entry_resolution_report_events import (
    _event_envelope,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    ensure_node_chapter,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.continuation_narrative import (
    continuation_narrative,
)
from tools.cli.release.research_reporting.publisher.service import (
    publish_research_checkpoint,
)


def test_continuation_narrative_types_compatibility_refs_by_prefix() -> None:
    value = carrier()
    value["latest_transition"]["evidence_refs"] = [
        "report:capability-resolution",
        "trace:" + "a" * 32,
        "evidence:screen-binding",
    ]

    links = continuation_narrative(value)["sections"][0]["links"]

    assert [
        (item["kind"], item["target_ref"]) for item in links[:3]
    ] == [
        ("graph_reference", "report:capability-resolution"),
        ("graph_reference", "trace:" + "a" * 32),
        ("evidence", "evidence:screen-binding"),
    ]


def test_continuation_events_and_receipt_belong_to_upgrade_inside_detour(
    tmp_path,
) -> None:
    profile(tmp_path)
    package = tmp_path / "profile-root" / "research" / "sgccs-review"
    initialize_tree(
        package_root=package, branch_id="branch-sgccs",
        report_id="report-sgccs", title="研究报告",
    )
    chapter = ensure_node_chapter(
        package_root=package, branch_id="branch-sgccs",
        node_id="hypothesis_preregistration", title="假设登记",
    )
    detour_id = "capability-detour-active"
    add_component(
        package_root=package, branch_id="branch-sgccs",
        component_id=detour_id, kind="special", title="能力修复过程",
        parent_id=chapter["component_id"], body="", content={},
        display_kind="capability_detour",
    )
    value = carrier()
    value["latest_transition"].update({
        "edge_ref": "graph-edge:__graph_continuation__",
        "from_node": value["current_node"],
        "to_node": value["current_node"],
    })
    value["latest_transition"]["entry_resolution_event"] = _event_envelope()

    first = publish_research_checkpoint(
        client_root=tmp_path, profile_id="maxa",
        agent_id="research-maxa", carrier=value,
        narrative=continuation_narrative(value),
        report_parent_id=detour_id,
    )
    repeated = publish_research_checkpoint(
        client_root=tmp_path, profile_id="maxa",
        agent_id="research-maxa", carrier=value,
        narrative=continuation_narrative(value),
        report_parent_id=detour_id,
    )

    saved = load_snapshot(
        package_root=package, branch_id="branch-sgccs",
    )
    capability = [
        item for item in saved["components"]
        if item["display_kind"] == "capability_detour"
    ]
    upgrades = [
        item for item in saved["components"]
        if item["display_kind"] == "graph_continuation"
    ]
    assert [item["component_id"] for item in capability] == [detour_id]
    assert len(upgrades) == 1
    upgrade = upgrades[0]
    assert upgrade["parent_id"] == detour_id
    events = [
        item for item in saved["components"]
        if item["parent_id"] == upgrade["component_id"]
        and item["component_id"].startswith("entry-resolution-")
    ]
    assert [item["content"]["ordinal"] for item in events] == list(range(6))
    receipt = next(
        item for item in saved["bindings"]
        if item["target_ref"] == value["checkpoint_ref"]
        and (item.get("data") or {}).get("role") == "checkpoint_receipt"
    )
    assert receipt["component_id"] == upgrade["component_id"]
    assert first["report_changed"] is True
    assert repeated["report_changed"] is False
