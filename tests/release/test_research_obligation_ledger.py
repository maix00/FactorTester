from __future__ import annotations

from copy import deepcopy
import json

import pytest

from tools.cli.release.research_obligations import (
    append_event,
    apply_obligation_deltas,
    canonicalize_ledger,
    inherit_obligation_ledger,
    initialize_ledger,
    ledger_path,
    ledger_from_history,
    load_ledger,
    project_requirement_coverage,
    write_ledger,
)
from tools.cli.release.research_reporting.authoring.submission_begin import (
    begin_submission,
)
from tools.cli.release.research_reporting.authoring.submission_pending import (
    digest,
    reconcile_pending,
)
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)
from tools.cli.release.research_reporting.authoring.tree_store import (
    load_head,
    write_head,
)
from tools.cli.release.research_obligations.reporting import (
    edge_coverage_operation,
    edge_selection_operation,
    obligation_change_operations,
)
from tools.cli.release.research_obligations.transition_report import (
    target_container_operations,
)
from tools.cli.release.research_reporting.authoring.tree_chapters import (
    ensure_node_chapter,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    apply_batch,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.git import commit_work_package
from tools.cli.commands.research_graph_obligation_advance import (
    prepare_obligation_advance,
    record_rejected_advance,
    require_complete_coverage,
)


def _ledger():
    return initialize_ledger(
        branch_ref="graph-branch:instance:branch",
        graph_ref="factor-research@v10",
        current_node="factor_semantics",
        context_ref="context:one",
        checkpoint_ref="trace:one",
        obligations=[{
            "obligation_id": "o1",
            "status": "open",
            "epistemic_question": "问题",
            "requirement_refs": ["mechanism_chain"],
        }],
    )


def test_single_atomic_branch_file_round_trip(tmp_path):
    written = write_ledger(tmp_path, "branch", _ledger())
    path = ledger_path(tmp_path, "branch")
    assert path == tmp_path / "branches" / "branch" / "obligations.json"
    assert load_ledger(tmp_path, "branch") == written
    assert not path.with_name("obligations.json.tmp").exists()


def test_initial_branch_ledger_allows_no_predecessor_checkpoint():
    ledger = initialize_ledger(
        branch_ref="graph-branch:instance:branch",
        graph_ref="factor-research@v10",
        current_node="hypothesis_preregistration",
        context_ref="sha256:" + "1" * 64,
        checkpoint_ref="",
    )
    assert ledger["branch"]["checkpoint_ref"] == ""


def test_history_migration_replays_changes_without_extra_files():
    ledger = ledger_from_history(
        branch_ref="graph-branch:instance:branch",
        packet={
            "graph": "factor-research@v10",
            "node": {"node_id": "validation_design"},
            "context_ref": "context:current",
            "checkpoint_ref": "trace:current",
            "entry_requirements": [{
                "requirement_id": "observable_proxy",
            }],
            "current_obligations": [{
                "obligation_id": "o1",
                "status": "discharged",
                "question_summary": "代理是否可观测",
                "requirement_refs": ["observable_proxy"],
            }],
        },
        contexts=[{
            "side": "target",
            "step_ref": "trace:first",
            "from_node": "factor_semantics",
            "to_node": "validation_design",
            "created_at": 1,
            "obligation_changes": [{
                "obligation_id": "o1",
                "from_state": "absent",
                "to_state": "open",
                "from_requirement_refs": [],
                "to_requirement_refs": ["observable_proxy"],
            }],
            "obligation_presentations": [{
                "obligation_ref": "obligation:o1",
                "question_summary": "代理是否可观测",
            }],
        }, {
            "side": "target",
            "step_ref": "trace:second",
            "from_node": "validation_design",
            "to_node": "validation_design",
            "created_at": 2,
            "obligation_changes": [{
                "obligation_id": "o1",
                "from_state": "open",
                "to_state": "discharged",
                "from_requirement_refs": ["observable_proxy"],
                "to_requirement_refs": ["observable_proxy"],
            }],
            "obligation_presentations": [{
                "obligation_ref": "obligation:o1",
                "question_summary": "代理是否可观测",
            }],
        }],
    )

    assert ledger["generation"] == 2
    assert [item["migration_source"] for item in ledger["history"]] == [
        "trace:first",
        "trace:second",
    ]
    assert ledger["current_projection"]["obligations"][0]["status"] == (
        "discharged"
    )


def test_mapping_only_delta_and_full_coverage_snapshot():
    obligations, changed = apply_obligation_deltas(
        _ledger()["current_projection"]["obligations"],
        [{
            "obligation_id": "o1",
            "from_state": "open",
            "to_state": "open",
            "from_requirement_refs": ["mechanism_chain"],
            "to_requirement_refs": ["observable_proxy"],
        }],
    )
    rows = project_requirement_coverage(
        requirements=[
            {"requirement_id": "mechanism_chain", "title_zh": "机制链"},
            {"requirement_id": "observable_proxy", "title_zh": "代理变量"},
            {"requirement_id": "boundary_conditions", "title_zh": "边界"},
        ],
        obligations=obligations,
        changed_obligation_refs=changed,
        edge_required_ids={"observable_proxy", "boundary_conditions"},
    )
    assert rows == [
        {
            "requirement_id": "mechanism_chain",
            "description": "机制链",
            "obligation_refs": [],
                "obligation_statuses": [],
                "changed": False,
                "node_required": True,
                "edge_required": False,
            "satisfaction": "pending",
        },
        {
            "requirement_id": "observable_proxy",
            "description": "代理变量",
            "obligation_refs": ["obligation:o1"],
                "obligation_statuses": ["open"],
                "changed": True,
                "node_required": True,
                "edge_required": True,
            "satisfaction": "missing",
        },
        {
            "requirement_id": "boundary_conditions",
            "description": "边界",
            "obligation_refs": [],
                "obligation_statuses": [],
                "changed": False,
                "node_required": True,
                "edge_required": True,
            "satisfaction": "missing",
        },
    ]


def test_one_obligation_can_cover_multiple_requirement_categories():
    obligations, changed = apply_obligation_deltas(
        _ledger()["current_projection"]["obligations"],
        [{
            "obligation_id": "o1",
            "from_state": "open",
            "to_state": "discharged",
            "from_requirement_refs": ["mechanism_chain"],
            "to_requirement_refs": [
                "mechanism_chain",
                "observable_proxy",
                "boundary_conditions",
            ],
        }],
    )
    rows = project_requirement_coverage(
        requirements=[
            {"requirement_id": "mechanism_chain"},
            {"requirement_id": "observable_proxy"},
            {"requirement_id": "boundary_conditions"},
        ],
        obligations=obligations,
        changed_obligation_refs=changed,
        edge_required_ids={
            "mechanism_chain",
            "observable_proxy",
            "boundary_conditions",
        },
    )
    assert obligations[0]["requirement_refs"] == [
        "mechanism_chain",
        "observable_proxy",
        "boundary_conditions",
    ]
    assert [row["obligation_refs"] for row in rows] == [
        ["obligation:o1"],
        ["obligation:o1"],
        ["obligation:o1"],
    ]
    assert [row["satisfaction"] for row in rows] == [
        "satisfied",
        "satisfied",
        "satisfied",
    ]


def test_one_requirement_category_can_be_covered_by_multiple_obligations():
    rows = project_requirement_coverage(
        requirements=[{
            "requirement_id": "observable_proxy",
            "title_zh": "代理变量",
        }],
        obligations=[
            {
                "obligation_id": "o1",
                "status": "serviced",
                "requirement_refs": ["observable_proxy"],
            },
            {
                "obligation_id": "o2",
                "status": "discharged",
                "requirement_refs": [
                    "observable_proxy",
                    "boundary_conditions",
                ],
            },
        ],
        changed_obligation_refs={"obligation:o2"},
        edge_required_ids={"observable_proxy"},
    )
    assert rows == [{
        "requirement_id": "observable_proxy",
        "description": "代理变量",
        "obligation_refs": ["obligation:o1", "obligation:o2"],
            "obligation_statuses": ["serviced", "discharged"],
            "changed": True,
            "node_required": True,
            "edge_required": True,
        "satisfaction": "satisfied",
    }]


def test_event_generation_and_projection_hash_change():
    before = _ledger()
    after = append_event(
        before,
        event_type="edge_selected",
        payload={"edge_id": "factor_semantics__validation_design"},
        created_at=1,
    )
    assert before["generation"] == 0
    assert after["generation"] == 1
    assert after["history"][0]["sequence"] == 1
    assert after["history"][0]["event_type"] == "edge_selected"
    assert after["current_projection"]["projection_hash"].startswith("sha256:")


def test_stale_delta_does_not_mutate_input():
    source = _ledger()["current_projection"]["obligations"]
    before = deepcopy(source)
    with pytest.raises(ValueError, match="from_state is stale"):
        apply_obligation_deltas(source, [{
            "obligation_id": "o1",
            "from_state": "discharged",
            "to_state": "open",
        }])
    assert source == before


def test_invalid_hash_and_oversized_file_fail_closed(tmp_path):
    path = ledger_path(tmp_path, "branch")
    path.parent.mkdir(parents=True)
    value = _ledger()
    value["current_projection"]["projection_hash"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="projection_hash mismatch"):
        load_ledger(tmp_path, "branch")
    path.write_bytes(b" " * (16 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="16 MiB"):
        load_ledger(tmp_path, "branch")


def test_fork_inherits_projection_with_new_branch_identity(tmp_path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source = _ledger()
    source["current_projection"]["requirement_coverage"] = (
        project_requirement_coverage(
            requirements=[{"requirement_id": "mechanism_chain"}],
            obligations=source["current_projection"]["obligations"],
        )
    )
    source = write_ledger(
        source_root, "source-branch", canonicalize_ledger(source),
    )
    inherited = inherit_obligation_ledger(
        source_package_root=source_root,
        target_package_root=target_root,
        source_branch_id="source-branch",
        target_branch_id="target-branch",
        target_instance_id="target-instance",
        target_packet={
            "graph": "factor-research@v10",
            "node": {"node_id": "factor_semantics"},
            "context_ref": "sha256:" + "2" * 64,
            "checkpoint_ref": "trace:two",
            "current_obligations": [{
                "obligation_id": "o1",
                "status": "open",
                "requirement_refs": ["mechanism_chain"],
            }],
            "entry_requirements": [{
                "requirement_id": "mechanism_chain",
            }],
        },
        inheritance_kind="branch_fork",
    )
    target = inherited["ledger"]
    assert target["branch"] == {
        "branch_ref": "graph-branch:target-instance:target-branch",
        "graph_ref": "factor-research@v10",
        "current_node": "factor_semantics",
        "context_ref": "sha256:" + "2" * 64,
        "checkpoint_ref": "trace:two",
    }
    assert target["current_projection"]["obligations"] == (
        source["current_projection"]["obligations"]
    )
    assert target["current_projection"]["selected_edge"] is None
    assert target["history"][0]["event_type"] == "forked"
    assert target["history"][0]["source_projection_hash"] == (
        source["current_projection"]["projection_hash"]
    )


def test_fork_preserves_explicit_empty_checkpoint(tmp_path):
    inherited = inherit_obligation_ledger(
        source_package_root=tmp_path / "missing-source",
        target_package_root=tmp_path / "target",
        source_branch_id="source-branch",
        target_branch_id="target-branch",
        target_instance_id="target-instance",
        target_packet={
            "graph": "factor-research@v10",
            "node": {"node_id": "hypothesis_preregistration"},
            "context_ref": "sha256:" + "2" * 64,
            "checkpoint_ref": "",
            "changed_refs": ["trace:historical-transition"],
            "current_obligations": [],
            "entry_requirements": [],
        },
        inheritance_kind="branch_fork",
    )

    assert inherited["ledger"]["branch"]["checkpoint_ref"] == ""


def test_obligation_change_report_has_change_current_and_requirement_tables():
    operations, ids = obligation_change_operations(
        parent_id="chapter-factor-semantics",
        event={
            "event_id": "event-one",
            "sequence": 1,
            "obligation_delta": [{
                "obligation_id": "o1",
                "from_state": "open",
                "to_state": "serviced",
                "from_requirement_refs": ["mechanism_chain"],
                "to_requirement_refs": ["observable_proxy"],
            }],
            "obligation_presentations": {
                "obligation:o1": "代理变量是否可观测",
            },
            "obligations_snapshot": [{
                "obligation_id": "o1",
                "status": "serviced",
                "requirement_refs": ["observable_proxy"],
            }],
            "coverage_snapshot": [{
                "requirement_id": "observable_proxy",
                "description": "可观测代理",
                "obligation_refs": ["obligation:o1"],
                "obligation_statuses": ["serviced"],
                "changed": True,
                "node_required": True,
                "edge_required": True,
                "satisfaction": "limited",
            }],
        },
    )
    assert [item["kind"] for item in operations] == [
        "special", "table", "table", "table",
    ]
    assert operations[1]["parent_id"] == ids["special_id"]
    assert operations[2]["parent_id"] == ids["special_id"]
    assert operations[3]["parent_id"] == ids["special_id"]
    assert operations[1]["content"]["columns"][-2:] == [
        "新增覆盖小类", "移除覆盖小类",
    ]
    assert operations[2]["display_kind"] == "current_obligations"
    assert operations[3]["display_kind"] == (
        "obligation_requirement_coverage"
    )
    assert operations[3]["content"]["columns"][-1] == "满足状态"
    assert "[o1](factortester://obligation/" in (
        operations[1]["content"]["rows"][0][0]
    )
    assert "[observable_proxy](factortester://entry_requirement/" in (
        operations[3]["content"]["rows"][0][0]
    )
    assert {item["kind"] for item in operations[1]["bindings"]} == {
        "obligation",
    }
    assert {item["kind"] for item in operations[3]["bindings"]} == {
        "entry_requirement",
        "obligation",
    }


def test_edge_coverage_table_regenerates_typed_link_bindings():
    operation, component_id = edge_coverage_operation(
        event_id="event-one",
        parent_id="obligation-changes-one",
        replace=True,
        coverage=[{
            "requirement_id": "observable_proxy",
            "description": "可观测代理",
            "obligation_refs": ["obligation:o1", "obligation:o2"],
            "obligation_statuses": ["serviced", "discharged"],
            "changed": True,
            "node_required": True,
            "edge_required": True,
            "satisfaction": "satisfied",
        }],
    )

    assert operation["op"] == "replace"
    assert component_id.startswith("obligation-requirement-table-")
    assert {item["kind"] for item in operation["bindings"]} == {
        "entry_requirement",
        "obligation",
    }
    assert all(
        item["binding_id"].startswith("reference-")
        for item in operation["bindings"]
    )


def test_report_pending_requires_exact_ledger_sidecar_before_publish(tmp_path):
    initialize_tree(
        package_root=tmp_path,
        branch_id="branch",
        report_id="report-one",
        title="研究",
    )
    ledger = append_event(
        _ledger(),
        event_type="obligation_change",
        event_id="event-one",
        created_at=1,
        payload={"obligation_delta": [], "coverage_snapshot": []},
    )
    sidecar = {
        "path": "obligations.json",
        "base_generation": 0,
        "next_generation": 1,
        "next_hash": digest(ledger),
        "next_value": ledger,
    }
    begin_submission(
        package_root=tmp_path,
        branch_id="branch",
        requested_sequence=None,
        logical_identity={"kind": "obligation_change", "event_id": "event-one"},
        payload={"event_id": "event-one"},
        sidecars=[sidecar],
    )
    paths = report_tree_paths(tmp_path, "branch")
    head = load_head(paths)
    write_head(paths, {**head, "generation": 1})
    reconciled = reconcile_pending(paths, load_head(paths))
    assert reconciled["phase"] == "published"
    assert load_ledger(tmp_path, "branch") == ledger


def _prepared_package(tmp_path, *, obligation_status="discharged"):
    initialize_tree(
        package_root=tmp_path,
        branch_id="branch",
        report_id="report-one",
        title="研究",
    )
    ledger = _ledger()
    ledger["current_projection"]["obligations"][0]["status"] = (
        obligation_status
    )
    ledger["current_projection"]["selected_edge"] = {
        "edge_id": "factor_semantics__validation_design",
        "target_node": "validation_design",
        "state_ref": "trace:one",
        "transition_contract": {
            "edge_id": "factor_semantics__validation_design",
            "to_node": "validation_design",
        },
        "required_requirement_ids": ["mechanism_chain"],
    }
    write_ledger(tmp_path, "branch", canonicalize_ledger(ledger))
    commit_work_package(tmp_path, message="Initialize obligation test package")
    return {
        "node_packet": {
            "graph": "factor-research@v10",
            "node": {"node_id": "factor_semantics"},
            "context_ref": "sha256:" + "1" * 64,
            "checkpoint_ref": "trace:one",
            "entry_requirements": [{
                "requirement_id": "mechanism_chain",
                "title_zh": "机制链",
            }],
        },
        "edge_packet": {
            "state_ref": "trace:one",
            "edge": {
                "edge_id": "factor_semantics__validation_design",
                "to_node": "validation_design",
                "obligation_requirements": [{
                    "requirement_id": "mechanism_chain",
                    "title_zh": "机制链",
                }],
            },
        },
        "evidence": {
            "entry_requirement_assessments": [{
                "requirement_id": "mechanism_chain",
                "applicability": {},
                "coverage": {
                    "decision": "create_new",
                    "obligation_refs": ["obligation:wrong"],
                },
                "resolution": {},
                "entry_effect": {},
            }],
        },
    }


def test_prepare_advance_freezes_git_and_replaces_coverage(tmp_path):
    fixture = _prepared_package(tmp_path)
    prepared = prepare_obligation_advance(
        package_root=tmp_path,
        branch_id="branch",
        edge_id="factor_semantics__validation_design",
        source_report_parent_id="chapter-factor-semantics",
        **fixture,
    )
    require_complete_coverage(prepared)
    coverage = prepared.evidence[
        "entry_requirement_assessments"
    ][0]["coverage"]
    assert coverage == {
        "decision": "map_existing",
        "obligation_refs": ["obligation:o1"],
    }
    assert prepared.coverage_submission["prepared_git_commit"] == (
        prepared.prepared_git_commit
    )
    assert load_ledger(tmp_path, "branch")["history"][-1][
        "event_type"
    ] == "advance_prepared"


def test_edge_only_requirement_does_not_become_node_entry_assessment(tmp_path):
    fixture = _prepared_package(tmp_path)
    ledger = load_ledger(tmp_path, "branch")
    ledger["current_projection"]["obligations"].append({
        "obligation_id": "o2",
        "status": "discharged",
        "epistemic_question": "边约束是否满足",
        "requirement_refs": ["edge_only"],
    })
    ledger["current_projection"]["selected_edge"][
        "required_requirement_ids"
    ] = ["mechanism_chain", "edge_only"]
    write_ledger(tmp_path, "branch", canonicalize_ledger(ledger))
    fixture["edge_packet"]["edge"]["obligation_requirements"].append({
        "requirement_id": "edge_only",
        "title_zh": "仅边要求",
    })
    prepared = prepare_obligation_advance(
        package_root=tmp_path,
        branch_id="branch",
        edge_id="factor_semantics__validation_design",
        source_report_parent_id="chapter-factor-semantics",
        **fixture,
    )
    assert [
        item["requirement_id"]
        for item in prepared.evidence["entry_requirement_assessments"]
    ] == ["mechanism_chain"]
    require_complete_coverage(prepared)


def test_rejected_advance_is_a_separate_immutable_event(tmp_path):
    fixture = _prepared_package(tmp_path, obligation_status="open")
    prepared = prepare_obligation_advance(
        package_root=tmp_path,
        branch_id="branch",
        edge_id="factor_semantics__validation_design",
        source_report_parent_id="chapter-factor-semantics",
        **fixture,
    )
    with pytest.raises(ValueError, match="missing obligation coverage"):
        require_complete_coverage(prepared)
    saved = record_rejected_advance(
        package_root=tmp_path,
        branch_id="branch",
        prepared=prepared,
        status="local_rejected",
        error_code="obligation_coverage",
        message="missing",
    )
    assert saved["receipt"]["status"] == "local_rejected"
    events = load_ledger(tmp_path, "branch")["history"]
    assert [item["event_type"] for item in events] == [
        "advance_prepared", "advance_receipt",
    ]


def test_edge_selection_report_is_one_rich_special():
    operation, component_id = edge_selection_operation(
        parent_id="chapter-factor-semantics",
        event={
            "event_id": "edge-event",
            "sequence": 2,
            "edge_id": "factor_semantics__validation_design",
            "target_node": "validation_design",
            "state_ref": "trace:one",
            "reason_markdown": "根据已解除的机制义务选择该路径",
        },
    )
    assert component_id.startswith("path-selection-")
    assert operation["kind"] == "special"
    assert operation["display_kind"] == "path_selection"
    assert operation["body"] == "根据已解除的机制义务选择该路径"


def test_target_chapter_and_requirement_overview_share_receipt_batch(tmp_path):
    initialize_tree(
        package_root=tmp_path,
        branch_id="branch",
        report_id="report-one",
        title="研究",
    )
    ensure_node_chapter(
        package_root=tmp_path,
        branch_id="branch",
        node_id="factor_semantics",
        title="因子语义",
    )
    operations, ids = target_container_operations(
        package_root=tmp_path,
        branch_id="branch",
        container={
            "kind": "chapter",
            "anchor_node": "validation_design",
            "current_node": "validation_design",
            "graph_ref": "factor-research@v10",
            "entry_requirements": [{
                "requirement_id": "validation.sample",
                "title_zh": "样本设计",
            }],
        },
    )

    assert [item["kind"] for item in operations] == [
        "chapter",
        "special",
    ]
    apply_batch(
        package_root=tmp_path,
        branch_id="branch",
        operations=operations,
    )
    snapshot = load_snapshot(package_root=tmp_path, branch_id="branch")
    by_id = {
        item["component_id"]: item for item in snapshot["components"]
    }
    assert by_id[ids["chapter_id"]]["title"] == "验证设计"
    assert by_id[ids["requirements_summary_id"]]["parent_id"] == (
        ids["chapter_id"]
    )
