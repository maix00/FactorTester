from __future__ import annotations

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    ensure_node_chapter,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.publisher.service import (
    publish_research_checkpoint,
)
from server.services.research_graph.branch.entry_resolution.events import (
    entry_resolution_event_envelope,
)
from server.services.research_graph.branch.entry_resolution.stack_state import (
    canonical_entry_resolution_state,
)

from tests.release.report_tree_fixtures import carrier, profile


EVENTS = ("push", "route", "wait", "resume", "resolve", "abandon")


def _event_envelope():
    return {
        "schema_version": 2,
        "trace_ref": "trace:checkpoint-1",
        "stack_hash_before": "a" * 64,
        "stack_hash_after": "b" * 64,
        "depth_before": 1,
        "depth_after": 1,
        "events": [{
            "event": event,
            "entry_attempt_id": f"attempt-{index}",
            "target_node": "validation_design",
            "ordinal": index,
            "report_item": {
                "kind": f"entry_resolution.{event}",
                "entry_attempt_id": f"attempt-{index}",
                "target_node": "validation_design",
            },
        } for index, event in enumerate(EVENTS)],
    }


def test_server_entry_events_remain_in_graph_timeline_not_report_tree(
    tmp_path,
) -> None:
    store = profile(tmp_path)
    package = (
        tmp_path / "profile-root" / "research" / "sgccs-review"
    )
    initialize_tree(
        package_root=package, branch_id="branch-sgccs",
        report_id="report-sgccs", title="研究报告",
    )
    chapter = ensure_node_chapter(
        package_root=package, branch_id="branch-sgccs",
        node_id="hypothesis_preregistration", title="假设登记",
    )
    parent_id = "special-capability-one"
    add_component(
        package_root=package, branch_id="branch-sgccs",
        component_id=parent_id, kind="special", title="能力修复过程",
        parent_id=chapter["component_id"], body="", content={},
        display_kind="capability_detour",
    )
    value = carrier()
    value["latest_transition"]["entry_resolution_event"] = _event_envelope()

    first = publish_research_checkpoint(
        client_root=tmp_path, profile_id="maxa",
        agent_id="research-maxa", carrier=value, narrative=None,
        report_parent_id=parent_id,
    )
    saved = load_snapshot(
        package_root=package, branch_id="branch-sgccs",
    )
    children = [
        item for item in saved["components"]
        if item["parent_id"] == parent_id
    ]
    assert children == []
    assert [
        item for item in saved["components"]
        if item["kind"] == "special"
    ] == [next(
        item for item in saved["components"]
        if item["component_id"] == parent_id
    )]
    receipt = next(
        item for item in saved["bindings"]
        if item["target_ref"] == "trace:checkpoint-1"
        and (item.get("data") or {}).get("role") == "checkpoint_receipt"
    )
    assert receipt["component_id"] == parent_id

    repeated = publish_research_checkpoint(
        client_root=tmp_path, profile_id="maxa",
        agent_id="research-maxa", carrier=value, narrative=None,
        report_parent_id=parent_id,
    )
    assert first["report_changed"] is True
    assert repeated["changed"] is False
    assert repeated["report_changed"] is False


def test_legacy_attempt_id_passes_carrier_and_publisher_validation(
    tmp_path,
) -> None:
    profile(tmp_path)
    package = tmp_path / "profile-root" / "research" / "sgccs-review"
    initialize_tree(
        package_root=package, branch_id="branch-sgccs",
        report_id="report-sgccs", title="研究报告",
    )
    legacy = canonical_entry_resolution_state({
        "schema_version": 1,
        "resume_node": "validation_design",
        "status": "pending",
        "unresolved_requirement_ids": ["trial_design.scope"],
    })
    event = entry_resolution_event_envelope(
        before_state={},
        departure_state=legacy,
        after_state=legacy,
        trace_ref="trace:checkpoint-1",
    )
    value = carrier()
    value["latest_transition"]["entry_resolution_event"] = event

    published = publish_research_checkpoint(
        client_root=tmp_path,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=value,
        narrative=None,
    )

    assert published["report_changed"] is True
    saved = load_snapshot(
        package_root=package, branch_id="branch-sgccs",
    )
    assert not any(
        item["component_id"].startswith("entry-resolution-")
        for item in saved["components"]
    )
    assert event["events"][0]["entry_attempt_id"].startswith(
        "legacy-entry-"
    )


def test_checkpoint_publish_uses_branch_record_not_mutable_agent_scope(
    tmp_path,
) -> None:
    store = profile(tmp_path)
    local_profile = store.load("maxa")
    local_profile["agents"][0]["scope"] = {
        "instance_id": "another-research",
        "branch_id": "another-branch",
    }
    local_profile["research_records"][0]["factor_family_versions"] = []
    store.save(local_profile)
    package = tmp_path / "profile-root" / "research" / "sgccs-review"
    initialize_tree(
        package_root=package, branch_id="branch-sgccs",
        report_id="report-sgccs", title="研究报告",
    )
    value = carrier()
    value["latest_transition"]["entry_resolution_event"] = _event_envelope()

    published = publish_research_checkpoint(
        client_root=tmp_path,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=value,
        narrative=None,
    )

    assert published["report_changed"] is True
