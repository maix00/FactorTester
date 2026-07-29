from server.services.research_graph.branch.entry_resolution.stack import (
    active_frame,
    canonical_entry_resolution_state,
    entry_resolution_event_envelope,
    entry_resolution_stack_hash,
    project_target_frame,
    resume_guard_hash,
    resume_guard_matches,
)
import pytest


GRAPH_REF = "factor-research@v10#" + "a" * 64
CHECKPOINT_REF = "research-cycle-checkpoint:" + "b" * 64


def _frame(node: str, attempt: str, *, pending: bool = True) -> dict:
    requirements = [f"{node}.requirement"]
    return {
        "schema_version": 2,
        "entry_attempt_id": attempt,
        "graph_ref": GRAPH_REF,
        "target_node": node,
        "origin_checkpoint_ref": CHECKPOINT_REF,
        "blocking_obligation_refs": [f"obligation:{node}"],
        "entry_requirement_refs": requirements,
        "status": "resolving" if pending else "resolved",
        "resume_guard_hash": resume_guard_hash(
            graph_ref=GRAPH_REF,
            target_node=node,
            origin_checkpoint_ref=CHECKPOINT_REF,
            blocking_obligation_refs=[f"obligation:{node}"],
            entry_requirement_refs=requirements,
        ),
    }


def test_schema1_upgrades_without_duplicating_receipts() -> None:
    legacy = {
        "schema_version": 1,
        "resume_node": "validation_design",
        "status": "pending",
        "unresolved_requirement_ids": ["validation_design.requirement"],
        "assessment_receipts": [{"receipt_hash": "c" * 64}],
    }

    first = canonical_entry_resolution_state(legacy)
    second = canonical_entry_resolution_state(first)

    assert first == second
    assert set(first) == {
        "schema_version", "frames", "assessment_receipts",
    }
    assert first["frames"][0]["target_node"] == "validation_design"
    assert first["frames"][0]["status"] == "resolving"
    assert "assessment_receipts" not in first["frames"][0]
    assert first["assessment_receipts"] == [{"receipt_hash": "c" * 64}]


def test_empty_detour_entry_does_not_push_a_return_frame() -> None:
    outer = canonical_entry_resolution_state(_frame("validation_design", "a"))
    projected = project_target_frame(
        state=outer,
        target_frame=_frame("capability_gap", "b", pending=False),
        current_node="validation_design",
        target_node="capability_gap",
    )

    assert len(projected["frames"]) == 1
    assert active_frame(projected)["target_node"] == "validation_design"


def test_two_nested_entry_diversions_resume_in_lifo_order() -> None:
    state = canonical_entry_resolution_state(
        _frame("validation_design", "outer")
    )
    state = project_target_frame(
        state=state,
        target_frame=_frame("capability_gap", "middle"),
        current_node="validation_design",
        target_node="capability_gap",
    )
    state = project_target_frame(
        state=state,
        target_frame=_frame("skill_candidate_review", "inner"),
        current_node="capability_gap",
        target_node="skill_candidate_review",
    )
    assert [item["target_node"] for item in state["frames"]] == [
        "validation_design", "capability_gap", "skill_candidate_review",
    ]

    state["frames"][-1]["status"] = "resolved"
    state = project_target_frame(
        state=state,
        target_frame=_frame("capability_gap", "return-middle"),
        current_node="skill_candidate_review",
        target_node="capability_gap",
    )
    assert active_frame(state)["target_node"] == "capability_gap"
    assert len(state["frames"]) == 2

    state["frames"][-1]["status"] = "resolved"
    state = project_target_frame(
        state=state,
        target_frame=_frame("validation_design", "return-outer"),
        current_node="capability_gap",
        target_node="validation_design",
    )
    assert active_frame(state)["target_node"] == "validation_design"
    assert len(state["frames"]) == 1


def test_resolved_root_does_not_leave_a_terminal_frame() -> None:
    state = canonical_entry_resolution_state(
        _frame("validation_design", "outer")
    )
    state["frames"][-1]["status"] = "resolved"

    state = project_target_frame(
        state=state,
        target_frame=_frame("factor_semantics", "next", pending=False),
        current_node="validation_design",
        target_node="factor_semantics",
    )

    assert state["frames"] == []


def test_resume_guard_invalidates_when_one_entry_input_changes() -> None:
    frame = _frame("validation_design", "attempt")
    assert resume_guard_matches(
        frame,
        graph_ref=GRAPH_REF,
        target_node="validation_design",
        origin_checkpoint_ref=CHECKPOINT_REF,
        blocking_obligation_refs=["obligation:validation_design"],
        entry_requirement_refs=["validation_design.requirement"],
    )
    assert not resume_guard_matches(
        frame,
        graph_ref=GRAPH_REF,
        target_node="validation_design",
        origin_checkpoint_ref="research-cycle-checkpoint:" + "d" * 64,
        blocking_obligation_refs=["obligation:validation_design"],
        entry_requirement_refs=["validation_design.requirement"],
    )


def test_canonical_frame_rejects_a_tampered_resume_guard() -> None:
    frame = _frame("validation_design", "attempt")
    frame["resume_guard_hash"] = "f" * 64

    with pytest.raises(ValueError, match="resume_guard_hash"):
        canonical_entry_resolution_state(frame)


@pytest.mark.parametrize(
    "field", ["graph_ref", "origin_checkpoint_ref", "resume_guard_hash"],
)
def test_native_v2_frame_cannot_omit_resume_guard_inputs(field: str) -> None:
    frame = _frame("validation_design", "attempt")
    frame.pop(field)

    with pytest.raises(ValueError, match="resume guard"):
        canonical_entry_resolution_state(frame)


def test_return_replaces_stale_outer_frame_instead_of_resuming_it() -> None:
    outer = _frame("validation_design", "outer")
    outer["status"] = "waiting"
    state = canonical_entry_resolution_state(outer)
    state = project_target_frame(
        state=state,
        target_frame=_frame("capability_gap", "inner"),
        current_node="validation_design",
        target_node="capability_gap",
    )
    state["frames"][-1]["status"] = "resolved"
    changed = _frame("validation_design", "recomputed")
    changed["blocking_obligation_refs"] = ["obligation:new"]
    changed["resume_guard_hash"] = resume_guard_hash(
        graph_ref=GRAPH_REF,
        target_node="validation_design",
        origin_checkpoint_ref=CHECKPOINT_REF,
        blocking_obligation_refs=["obligation:new"],
        entry_requirement_refs=["validation_design.requirement"],
    )

    state = project_target_frame(
        state=state,
        target_frame=changed,
        current_node="capability_gap",
        target_node="validation_design",
    )

    assert len(state["frames"]) == 1
    assert active_frame(state)["entry_attempt_id"] == "recomputed"
    assert active_frame(state)["status"] == "resolving"


def test_guard_replacement_emits_abandon_then_push() -> None:
    before = canonical_entry_resolution_state(
        _frame("validation_design", "old")
    )
    after = canonical_entry_resolution_state(
        _frame("validation_design", "new")
    )

    envelope = entry_resolution_event_envelope(
        before_state=before,
        departure_state=before,
        after_state=after,
        trace_ref="trace:guard-recomputed",
    )

    assert [item["event"] for item in envelope["events"]] == [
        "abandon", "push",
    ]
    assert [item["entry_attempt_id"] for item in envelope["events"]] == [
        "old", "new",
    ]


def test_route_wait_and_push_are_one_ordered_trace_envelope() -> None:
    before = canonical_entry_resolution_state(
        _frame("validation_design", "outer")
    )
    departure = canonical_entry_resolution_state(before)
    departure["frames"][-1].update({
        "selected_route": "capability_gap",
        "status": "waiting",
    })
    after = canonical_entry_resolution_state(departure)
    after["frames"].append(_frame("capability_gap", "inner"))

    envelope = entry_resolution_event_envelope(
        before_state=before,
        departure_state=departure,
        after_state=after,
        trace_ref="trace:1",
    )

    assert envelope["schema_version"] == 2
    assert envelope["trace_ref"] == "trace:1"
    assert [item["event"] for item in envelope["events"]] == [
        "route", "wait", "push",
    ]
    assert [item["ordinal"] for item in envelope["events"]] == [0, 1, 2]
    assert envelope["events"][2]["entry_attempt_id"] == "inner"
    assert envelope["events"][2]["report_item"]["kind"] == (
        "entry_resolution.push"
    )


def test_resolve_precedes_lifo_resume_in_one_trace() -> None:
    outer = _frame("validation_design", "outer")
    outer["status"] = "waiting"
    before = canonical_entry_resolution_state(outer)
    before["frames"].append(_frame("capability_gap", "inner"))
    departure = canonical_entry_resolution_state(before)
    departure["frames"][-1]["status"] = "resolved"
    after = canonical_entry_resolution_state(departure)
    after["frames"].pop()
    after["frames"][-1]["status"] = "resumable"

    envelope = entry_resolution_event_envelope(
        before_state=before,
        departure_state=departure,
        after_state=after,
        trace_ref="trace:2",
    )

    assert [item["event"] for item in envelope["events"]] == [
        "resolve", "resume",
    ]
    assert envelope["events"][0]["entry_attempt_id"] == "inner"
    assert envelope["events"][1]["entry_attempt_id"] == "outer"


def test_unchanged_stack_emits_no_entry_event() -> None:
    state = canonical_entry_resolution_state(
        _frame("validation_design", "outer")
    )

    assert entry_resolution_event_envelope(
        before_state=state,
        departure_state=state,
        after_state=state,
        trace_ref="trace:3",
    ) is None


def test_receipt_only_change_does_not_change_stack_hash() -> None:
    before = canonical_entry_resolution_state(
        _frame("validation_design", "outer")
    )
    after = canonical_entry_resolution_state(before)
    after["assessment_receipts"] = [{"receipt_hash": "e" * 64}]

    assert entry_resolution_stack_hash(before) == entry_resolution_stack_hash(
        after
    )
