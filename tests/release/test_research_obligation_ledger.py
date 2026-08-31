from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tools.cli.release.research_obligations import (
    append_event,
    apply_evidence_use_deltas,
    apply_obligation_deltas,
    canonicalize_ledger,
    inherit_obligation_ledger,
    initialize_ledger,
    ledger_path,
    ledger_from_history,
    load_ledger,
    migrate_ledger_titles,
    migrate_ledger_evidence_v2,
    normalize_evidence_use,
    prepare_obligation_split,
    project_requirement_coverage,
    report_title_operations,
    requirement_title_overrides,
    write_ledger,
)
from tools.cli.commands.research_graph_obligation_evidence_migration import (
    _migrate,
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
    node_exit_operations,
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
from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_markdown_link,
)
from tools.cli.commands.research_graph_obligation_advance import (
    _receipt_for,
    finalize_accepted_advance,
    prepare_obligation_advance,
    record_rejected_advance,
    require_complete_coverage,
)
from tools.cli.commands import research_graph_obligation_advance as advance
from tools.cli.commands import research_graph_obligations as obligation_commands


_FACTOR_REF = "factor:v2:" + "a" * 43


def _ledger():
    return initialize_ledger(
        branch_ref="graph-branch:instance:branch",
        graph_ref="factor-research@v10",
        current_node="factor_semantics",
        context_ref="context:one",
        checkpoint_ref="trace:one",
        obligations=[{
            "obligation_id": "o1",
            "title_zh": "代理可观测性",
            "status": "open",
            "epistemic_question": "问题",
            "requirement_refs": ["mechanism_chain"],
            "scope": {"factor_ref": _FACTOR_REF},
            "claim_scopes": [],
        }],
    )


def _use(
    obligation_id: str,
    requirement_id: str,
    *,
    qualification: str = "eligible",
) -> dict:
    return normalize_evidence_use({
        "evidence_ref": (
            "evidence:diagnostic:sha256:" + obligation_id[0] * 64
        ),
        "evidence_title_zh": "机制验证证据",
        "obligation_ref": f"obligation:{obligation_id}",
        "requirement_refs": [requirement_id],
        "rationale_zh": "该片段直接验证此义务小类",
        "qualification": qualification,
        "scope_match": {
            "scope_compatibility": "compatible",
            "matched_by": ["factor_ref"],
            "conflicts": [],
            "limitations": [],
            "requested_scope": {"factor_refs": [_FACTOR_REF]},
        },
    })


def test_change_reader_rejects_inner_schema_version_on_cycle_envelope(
    tmp_path,
):
    path = tmp_path / "change.json"
    path.write_text(json.dumps({
        "expected_projection_hash": "sha256:projection",
        "research_cycle": {"schema_version": 2, "events": []},
        "obligation_delta": [],
        "evidence_use_delta": [],
        "obligation_presentations": {},
        "reason_markdown": "记录义务变化",
    }), encoding="utf-8")

    with pytest.raises(
        Exception, match="envelope schema_version must be 1",
    ):
        obligation_commands._read_change(path)


def test_change_reader_accepts_v1_envelope_with_v2_proposal(tmp_path):
    path = tmp_path / "change.json"
    path.write_text(json.dumps({
        "expected_projection_hash": "sha256:projection",
        "research_cycle": {
            "schema_version": 1,
            "parent_trace_ref": "trace:checkpoint",
            "events": [{
                "event_type": "adjudication_proposed",
                "proposal": {"schema_version": 2},
            }],
        },
        "obligation_delta": [],
        "evidence_use_delta": [],
        "obligation_presentations": {},
        "reason_markdown": "记录义务变化",
    }), encoding="utf-8")

    assert obligation_commands._read_change(path)["research_cycle"][
        "schema_version"
    ] == 1


def test_edge_scope_revalidation_rejects_factor_evidence_on_wide_obligation():
    use = _use("wide", "mechanism_chain")
    rows = project_requirement_coverage(
        requirements=[{
            "requirement_id": "mechanism_chain",
            "accepted_states": ["bounded"],
            "minimum_qualification": "limited",
            "scope_policy": {
                "required_scope": {
                    "factor_refs": [_FACTOR_REF],
                },
            },
        }],
        obligations=[{
            "obligation_id": "wide",
            "status": "bounded",
            "requirement_refs": ["mechanism_chain"],
            "scope": {},
            "claim_scopes": [],
        }],
        evidence_uses=[use],
        edge_required_ids={"mechanism_chain"},
        enforce_evidence=True,
    )

    assert rows[0]["satisfaction"] == "missing"
    assert rows[0]["scope_revalidation"]["failures"] == [{
        "obligation_ref": "obligation:wide",
        "missing": [],
        "unbound": ["factor_refs"],
    }]


def test_edge_scope_revalidation_accepts_explicit_matching_factor_scope():
    use = _use("narrow", "mechanism_chain")
    rows = project_requirement_coverage(
        requirements=[{
            "requirement_id": "mechanism_chain",
            "accepted_states": ["bounded"],
            "minimum_qualification": "limited",
            "scope_policy": {
                "required_scope": {
                    "factor_refs": [_FACTOR_REF],
                },
            },
        }],
        obligations=[{
            "obligation_id": "narrow",
            "status": "bounded",
            "requirement_refs": ["mechanism_chain"],
            "scope": {"factor_ref": _FACTOR_REF},
            "claim_scopes": [],
        }],
        evidence_uses=[use],
        edge_required_ids={"mechanism_chain"},
        enforce_evidence=True,
    )

    assert rows[0]["satisfaction"] == "limited"
    assert rows[0]["scope_revalidation"]["status"] == "matched"


def test_factor_set_scope_is_not_inferred_from_member_factor():
    set_ref = "factor-set:v2:" + "b" * 43
    obligation = {
        "obligation_id": "portfolio",
        "status": "bounded",
        "requirement_refs": ["mechanism_chain"],
        "scope": {"factor_ref": set_ref},
        "claim_scopes": [],
    }
    member_use = _use("portfolio", "mechanism_chain")
    rows = project_requirement_coverage(
        requirements=[{
            "requirement_id": "mechanism_chain",
            "scope_policy": {
                "required_scope": {
                    "factor_refs": [set_ref],
                },
            },
        }],
        obligations=[obligation],
        evidence_uses=[member_use],
        edge_required_ids={"mechanism_chain"},
        enforce_evidence=True,
    )
    assert rows[0]["satisfaction"] == "missing"

    set_use = normalize_evidence_use({
        **member_use,
        "scope_match": {
            **member_use["scope_match"],
            "requested_scope": {"factor_refs": [set_ref]},
        },
        "use_id": None,
    })
    rows = project_requirement_coverage(
        requirements=[{
            "requirement_id": "mechanism_chain",
            "scope_policy": {
                "required_scope": {
                    "factor_refs": [set_ref],
                },
            },
        }],
        obligations=[obligation],
        evidence_uses=[set_use],
        edge_required_ids={"mechanism_chain"},
        enforce_evidence=True,
    )
    assert rows[0]["satisfaction"] == "limited"


def test_obligation_split_reassigns_requirements_without_copying_evidence():
    parent = {
        "obligation_id": "wide",
        "title_zh": "宽泛义务",
        "status": "bounded",
        "requirement_refs": ["mechanism_chain", "observable_proxy"],
    }
    old_use = _use("wide", "mechanism_chain")
    child_use = _use("mechanism", "mechanism_chain")

    split = prepare_obligation_split(
        obligations=[parent],
        evidence_uses=[old_use],
        parent_obligation_id="wide",
        children=[{
            "obligation_id": "mechanism",
            "title_zh": "机制义务",
            "status": "bounded",
            "requirement_refs": ["mechanism_chain"],
        }, {
            "obligation_id": "proxy",
            "title_zh": "代理义务",
            "status": "open",
            "requirement_refs": ["observable_proxy"],
        }],
        child_evidence_use_delta=[{"op": "add", "use": child_use}],
    )

    assert split["obligation_delta"][0]["to_state"] == "superseded"
    assert split["obligation_delta"][0]["to_requirement_refs"] == []
    assert split["evidence_use_delta"][0] == {
        "op": "remove",
        "use_id": old_use["use_id"],
    }
    assert split["evidence_use_delta"][1]["use"] == child_use


def test_obligation_split_requires_complete_parent_requirement_union():
    with pytest.raises(ValueError, match="collectively retain"):
        prepare_obligation_split(
            obligations=[{
                "obligation_id": "wide",
                "status": "open",
                "requirement_refs": ["one", "two"],
            }],
            evidence_uses=[],
            parent_obligation_id="wide",
            children=[{
                "obligation_id": "left",
                "status": "open",
                "requirement_refs": ["one"],
            }, {
                "obligation_id": "right",
                "status": "open",
                "requirement_refs": ["one"],
            }],
            child_evidence_use_delta=[],
        )


def test_v1_evidence_migration_rewrites_three_tables_and_marks_legacy():
    ledger = _ledger()
    ledger["current_projection"]["requirement_coverage"] = [{
        "requirement_id": "mechanism_chain",
        "description": "机制作用链",
        "obligation_refs": ["obligation:o1"],
        "obligation_statuses": ["open"],
        "changed": True,
        "node_required": True,
        "edge_required": False,
        "satisfaction": "pending",
    }]
    ledger = canonicalize_ledger(ledger)
    ledger = append_event(
        ledger,
        event_type="obligation_change",
        event_id="change-one",
        payload={
            "agent_id": "maxa",
            "node_id": "factor_semantics",
            "report_submission_sequence": 1,
            "reason_markdown": "根据审计调整义务",
            "obligation_delta": [{
                "obligation_id": "o1",
                "from_state": "open",
                "to_state": "open",
            }],
            "research_cycle": {},
            "obligation_presentations": {
                "obligation:o1": "问题",
            },
            "obligations_snapshot": ledger[
                "current_projection"
            ]["obligations"],
            "coverage_snapshot": ledger[
                "current_projection"
            ]["requirement_coverage"],
            "report_components": {
                    "special_id": (
                        "obligation-changes-"
                        "b4d643559a75a9a0e950fdd1"
                    ),
                    "change_table_id": (
                        "obligation-change-table-"
                        "b4d643559a75a9a0e950fdd1"
                    ),
                    "current_table_id": (
                        "current-obligation-table-"
                        "b4d643559a75a9a0e950fdd1"
                    ),
                    "requirement_table_id": (
                        "obligation-requirement-table-"
                        "b4d643559a75a9a0e950fdd1"
                    ),
            },
        },
    )

    migrated, operations = migrate_ledger_evidence_v2(ledger)

    assert migrated["history"][-1]["event_type"] == "evidence_migrated"
    assert migrated["history"][-1]["legacy_evidence_disposition"] == (
        "unverifiable_fragment"
    )
    assert len(operations) == 4
    assert {item["op"] for item in operations} == {"replace"}
    current = next(
        item for item in operations
        if item["component_id"].startswith("current-obligation-table")
    )
    assert current["content"]["columns"][-1] == "证据"


def test_single_atomic_branch_file_round_trip(tmp_path):
    written = write_ledger(tmp_path, "branch", _ledger())
    path = ledger_path(tmp_path, "branch")
    assert path == tmp_path / "branches" / "branch" / "obligations.json"
    assert load_ledger(tmp_path, "branch") == written
    assert not path.with_name("obligations.json.tmp").exists()


def test_evidence_exclusion_removes_uses_and_builds_one_report_episode():
    ledger = _ledger()
    use = _use("o1", "mechanism_chain")
    ledger["current_projection"]["evidence_uses"] = [use]
    remaining, changed = apply_evidence_use_deltas(
        [use],
        [{"op": "remove", "use_id": use["use_id"]}],
        obligations=ledger["current_projection"]["obligations"],
    )
    event = {
        "event_id": "exclude-one",
        "sequence": 1,
        "event_type": "evidence_lifecycle",
        "reason_markdown": "该证据与冻结样本不一致，因此解除其覆盖",
        "obligation_delta": [],
        "evidence_use_delta": [{
            "op": "remove", "use_id": use["use_id"],
        }],
        "evidence_use_changes": [{"op": "remove", "use": use}],
        "obligations_snapshot": ledger[
            "current_projection"
        ]["obligations"],
        "evidence_uses_snapshot": remaining,
        "coverage_snapshot": project_requirement_coverage(
            requirements=[{
                "requirement_id": "mechanism_chain",
                "title_zh": "机制作用链",
            }],
            obligations=ledger["current_projection"]["obligations"],
            evidence_uses=remaining,
            edge_required_ids={"mechanism_chain"},
            enforce_evidence=True,
        ),
        "obligation_presentations": {},
        "evidence_lifecycle": {
            "transition_ref": "evidence-lifecycle:sha256:" + "a" * 64,
            "evidence_ref": use["evidence_ref"],
            "evidence_title_zh": use["evidence_title_zh"],
            "action": "exclude",
            "from_status": "active",
            "to_status": "excluded",
            "reason_zh": "该证据与冻结样本不一致",
            "removed_evidence_use_ids": [use["use_id"]],
        },
    }

    operations, ids = obligation_change_operations(
        event=event, parent_id="chapter",
    )

    assert changed == {use["use_id"]}
    assert remaining == []
    assert len(operations) == 9
    assert operations[0]["title"] == "证据排除与义务变化"
    lifecycle_table = next(
        item for item in operations
        if item["component_id"] == ids["evidence_table_id"]
    )
    assert lifecycle_table["content"]["rows"][0][3] == "1"
    change_table = next(
        item for item in operations
        if item["component_id"] == ids["change_table_id"]
    )
    assert change_table["content"]["rows"][0][7] == typed_markdown_link(
        kind="evidence",
        target_ref=use["evidence_ref"],
        label=use["evidence_title_zh"],
    )
    assert event["coverage_snapshot"][0]["satisfaction"] == "missing"


def test_evidence_lifecycle_is_a_valid_persisted_ledger_event():
    ledger = append_event(
        _ledger(),
        event_type="evidence_lifecycle",
        event_id="exclude-one",
        payload={
            "evidence_lifecycle": {
                "evidence_ref": "evidence:data_contract:sha256:" + "a" * 64,
                "action": "exclude",
                "from_status": "active",
                "to_status": "excluded",
            },
        },
    )

    assert ledger["history"][-1]["event_type"] == "evidence_lifecycle"


def test_evidence_use_changes_freeze_added_and_removed_uses():
    old_use = _use("o1", "mechanism_chain")
    new_use = {
        **old_use,
        "use_id": "evidence-use:sha256:" + "n" * 64,
        "evidence_ref": "evidence:diagnostic:sha256:" + "n" * 64,
        "evidence_title_zh": "替代证据",
    }

    changes = obligation_commands._describe_evidence_use_changes(
        [old_use],
        [
            {"op": "remove", "use_id": old_use["use_id"]},
            {"op": "add", "use": new_use},
        ],
    )

    assert changes == [
        {"op": "remove", "use": old_use},
        {"op": "add", "use": new_use},
    ]


def test_empty_obligation_change_table_is_not_emitted():
    event = {
        "event_id": "lifecycle-without-coverage-change",
        "sequence": 1,
        "reason_markdown": "仅更新证据目录状态",
        "obligation_delta": [],
        "evidence_use_delta": [],
        "evidence_use_changes": [],
        "obligations_snapshot": _ledger()[
            "current_projection"
        ]["obligations"],
        "evidence_uses_snapshot": [],
        "coverage_snapshot": [],
        "requirement_titles": {"mechanism_chain": "机制作用链"},
        "obligation_presentations": {},
        "evidence_lifecycle": {
            "transition_ref": "evidence-lifecycle:sha256:" + "a" * 64,
            "evidence_ref": "evidence:diagnostic:sha256:" + "b" * 64,
            "evidence_title_zh": "未绑定证据",
            "action": "exclude",
            "from_status": "active",
            "to_status": "excluded",
            "reason_zh": "没有义务覆盖关系",
            "removed_evidence_use_ids": [],
        },
    }

    operations, ids = obligation_change_operations(
        event=event, parent_id="chapter",
    )

    assert not any(
        item["component_id"] == ids["change_table_id"]
        for item in operations
    )
    assert not any(item.get("title") == "义务变化" for item in operations)
    assert operations[0]["content"] is None


def test_obligation_report_uses_historical_requirement_title_snapshot():
    event = {
        "event_id": "exclude-historical-reference",
        "sequence": 1,
        "reason_markdown": "排除旧证据但保留历史义务语义",
        "obligation_delta": [],
        "evidence_use_delta": [],
        "obligations_snapshot": [{
            "obligation_id": "o1",
            "title_zh": "历史机制义务",
            "epistemic_question": "历史机制是否成立",
            "status": "bounded",
            "requirement_refs": ["hypothesis_validity.mechanism_chain"],
        }],
        "evidence_uses_snapshot": [],
        "coverage_snapshot": [{
            "requirement_id": "data.temporal_coverage",
            "description": "时间覆盖",
            "obligation_refs": [],
            "obligation_statuses": [],
            "evidence_uses": [],
            "changed": False,
            "node_required": True,
            "edge_required": True,
            "accepted_states": ["bounded"],
            "minimum_qualification": "limited",
            "satisfaction": "missing",
        }],
        "requirement_titles": {
            "hypothesis_validity.mechanism_chain": "机制作用链",
            "data.temporal_coverage": "时间覆盖",
        },
        "obligation_presentations": {},
    }

    operations, _ = obligation_change_operations(
        event=event, parent_id="chapter",
    )
    current = next(
        item for item in operations
        if item["component_id"].startswith("current-obligation-table")
    )

    assert "机制作用链" in current["content"]["rows"][0][3]


def test_obligation_report_allows_event_specific_question_presentation():
    event = {
        "event_id": "definition-conflict",
        "sequence": 1,
        "reason_markdown": "状态变化不应改写义务定义",
        "obligation_delta": [{
            "obligation_id": "o1",
            "from_state": "open",
            "to_state": "bounded",
        }],
        "obligations_snapshot": [{
            "obligation_id": "o1",
            "title_zh": "机制义务",
            "epistemic_question": "首次问题",
            "status": "bounded",
            "requirement_refs": [],
        }],
        "evidence_uses_snapshot": [],
        "coverage_snapshot": [],
        "obligation_presentations": {
            "obligation:o1": "后续改写的问题",
        },
    }

    operations, _identities = obligation_change_operations(
        event=event, parent_id="chapter",
    )

    change_table = next(
        item for item in operations
        if item["component_id"].startswith("obligation-change-table")
    )
    assert change_table["content"]["rows"][0][1] == "后续改写的问题"


def test_accepted_receipt_supersedes_rejected_receipt(monkeypatch, tmp_path):
    ledger = _ledger()
    ledger = append_event(
        ledger,
        event_type="advance_prepared",
        event_id="attempt-1",
        payload={"attempt_id": "attempt-1"},
    )
    ledger = append_event(
        ledger,
        event_type="advance_receipt",
        event_id="rejected-1",
        payload={
            "attempt_id": "attempt-1",
            "status": "server_rejected",
            "error_code": "server_transition_rejected",
            "message": "old report coverage",
            "prepared_git_commit": "commit-1",
            "trace_ref": "",
            "checkpoint_ref": "",
        },
    )
    write_ledger(tmp_path, "branch", ledger)

    monkeypatch.setattr(
        advance, "node_exit_operations",
        lambda **_kwargs: ([], {"special_id": "special", "table_id": "table"}),
    )
    monkeypatch.setattr(
        advance, "target_container_operations",
        lambda **_kwargs: ([], {"chapter_id": "chapter"}),
    )
    monkeypatch.setattr(
        advance, "report_container",
        lambda _packet: {"kind": "chapter", "anchor_node": "target"},
    )
    monkeypatch.setattr(advance, "packet_obligations", lambda _packet: [])
    monkeypatch.setattr(advance, "packet_requirements", lambda _packet: [])
    monkeypatch.setattr(
        advance, "project_requirement_coverage", lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        advance, "requirement_title_overrides", lambda _ledger: {},
    )
    monkeypatch.setattr(
        advance, "begin_submission",
        lambda **_kwargs: SimpleNamespace(phase="finalized"),
    )
    monkeypatch.setattr(
        advance, "finalize_report_command",
        lambda **_kwargs: {"git": {"commit": "commit-accepted"}},
    )

    result = finalize_accepted_advance(
        scope=SimpleNamespace(
            package_root=tmp_path,
            branch_id="branch",
            client_root=tmp_path,
            profile_id="maxa",
            profile={},
            record={"record_id": "work-package"},
            instance_id="instance",
        ),
        next_packet={
            "graph": "factor-research@v10",
            "node": {"node_id": "target"},
            "context_ref": "context:target",
            "checkpoint_ref": "trace:accepted",
        },
        reconciliation={
            "attempt_id": "attempt-1",
            "prepared_git_commit": "commit-1",
            "source_report_parent_id": "chapter-source",
            "branch_result": {},
        },
        submission_sequence=None,
    )

    assert result["receipt"]["status"] == "accepted"
    assert result["receipt"]["supersedes_receipt_id"] == "rejected-1"
    repaired = load_ledger(tmp_path, "branch")
    assert _receipt_for(repaired, "attempt-1")["status"] == "accepted"
    assert [
        item["status"] for item in repaired["history"]
        if item.get("event_type") == "advance_receipt"
    ] == ["server_rejected", "accepted"]


def test_title_migration_is_audited_and_preserved_on_reprojection():
    ledger = _ledger()
    ledger["current_projection"]["obligations"][0]["title_zh"] = ""
    ledger["current_projection"]["requirement_coverage"] = [{
        "requirement_id": "mechanism_chain",
        "description": "",
        "obligation_refs": ["obligation:o1"],
        "obligation_statuses": ["open"],
        "changed": False,
        "node_required": True,
        "edge_required": False,
        "satisfaction": "pending",
    }]
    ledger = canonicalize_ledger(ledger)

    migrated = migrate_ledger_titles(
        ledger,
        obligation_titles={"o1": "机制代理可验证性"},
        requirement_titles={"mechanism_chain": "机制作用链"},
    )

    assert migrated["generation"] == 1
    assert migrated["history"][-1]["event_type"] == "title_migrated"
    assert set(migrated["history"][-1]) >= {
        "title_map_hash",
        "obligation_title_count",
        "requirement_title_count",
    }
    assert "obligation_titles" not in migrated["history"][-1]
    assert migrated["current_projection"]["obligations"][0]["title_zh"] == (
        "机制代理可验证性"
    )
    overrides = requirement_title_overrides(migrated)
    assert overrides == {"mechanism_chain": "机制作用链"}
    coverage = project_requirement_coverage(
        requirements=[{
            "requirement_id": "mechanism_chain",
            "title_zh": "这是旧图中不应覆盖迁移结果的长标题",
        }],
        obligations=migrated["current_projection"]["obligations"],
        title_overrides=overrides,
    )
    assert coverage[0]["description"] == "机制作用链"


def test_title_migration_cannot_overwrite_an_existing_obligation_title():
    with pytest.raises(
        ValueError,
        match=r"immutable definition conflict: o1\.title_zh",
    ):
        migrate_ledger_titles(
            _ledger(),
            obligation_titles={"o1": "后续改写的标题"},
            requirement_titles={},
        )


def test_report_title_migration_rewrites_only_typed_object_labels():
    obligation_link = typed_markdown_link(
        kind="obligation",
        target_ref="obligation:o1",
        label="o1",
    )
    requirement_link = typed_markdown_link(
        kind="entry_requirement",
        target_ref="requirement:mechanism_chain",
        label="旧长标题",
    )
    snapshot = {
        "components": [{
            "component_id": "special-one",
            "kind": "special",
            "title": obligation_link,
            "body": f"{requirement_link} [外部资料](https://example.com)",
            "content": {"rows": [[obligation_link, requirement_link]]},
            "display_kind": "obligation_changes",
        }],
        "bindings": [{
            "component_id": "special-one",
            "binding_id": "obligation-o1",
            "kind": "obligation",
            "target_ref": "obligation:o1",
            "label": "o1",
            "data": {},
        }, {
            "component_id": "special-one",
            "binding_id": "requirement-mechanism",
            "kind": "entry_requirement",
            "target_ref": "requirement:mechanism_chain",
            "label": "旧长标题",
            "data": {},
        }],
    }

    operations = report_title_operations(
        snapshot,
        obligation_titles={"o1": "机制代理可验证性"},
        requirement_titles={"mechanism_chain": "机制作用链"},
    )

    assert len(operations) == 1
    replacement = operations[0]
    assert "[机制代理可验证性](factortester://obligation/" in (
        replacement["title"]
    )
    assert "[机制作用链](factortester://entry_requirement/" in (
        replacement["body"]
    )
    assert "[外部资料](https://example.com)" in replacement["body"]
    assert [item["label"] for item in replacement["bindings"]] == [
        "机制代理可验证性", "机制作用链",
    ]
    assert [item["data"]["title_zh"] for item in replacement["bindings"]] == [
        "机制代理可验证性", "机制作用链",
    ]


def test_report_title_migration_can_retarget_reviewed_binding(tmp_path):
    initialize_tree(
        package_root=tmp_path,
        branch_id="branch",
        report_id="report-one",
        title="研究",
    )
    source_link = typed_markdown_link(
        kind="obligation",
        target_ref="obligation:obsolete-lifecycle",
        label="obsolete-lifecycle",
    )
    apply_batch(
        package_root=tmp_path,
        branch_id="branch",
        operations=[{
            "op": "add",
            "component_id": "chapter",
            "kind": "chapter",
            "title": "能力修复",
            "parent_id": None,
            "body": "",
            "content": None,
            "display_kind": "",
            "bindings": [],
        }, {
            "op": "add",
            "component_id": "reviewed",
            "kind": "special",
            "title": "历史能力项",
            "parent_id": "chapter",
            "body": source_link,
            "content": None,
            "display_kind": "capability_resolution",
            "bindings": [{
                "binding_id": "reviewed-ref",
                "kind": "obligation",
                "target_ref": "obligation:obsolete-lifecycle",
                "label": "obsolete-lifecycle",
                "data": {
                    "related_ref": "obligation:obsolete-lifecycle",
                },
            }],
        }],
    )
    snapshot = load_snapshot(package_root=tmp_path, branch_id="branch")

    operations = report_title_operations(
        snapshot,
        obligation_titles={},
        requirement_titles={
            "market_execution_accounting.contract_lifecycle": "合约生命周期",
        },
        reference_rewrites={
            "obligation|obligation:obsolete-lifecycle": {
                "kind": "entry_requirement",
                "target_ref": (
                    "requirement:"
                    "market_execution_accounting.contract_lifecycle"
                ),
                "title_zh": "合约生命周期",
            },
        },
    )

    assert operations[0]["_trusted_binding_retarget"] is True
    migrated = apply_batch(
        package_root=tmp_path,
        branch_id="branch",
        operations=operations,
    )
    binding = migrated["bindings"][0]
    assert binding["binding_id"] == "reviewed-ref"
    assert binding["kind"] == "entry_requirement"
    assert binding["target_ref"] == (
        "requirement:market_execution_accounting.contract_lifecycle"
    )
    assert binding["label"] == "合约生命周期"
    assert binding["data"]["related_ref"] == (
        "requirement:market_execution_accounting.contract_lifecycle"
    )
    assert "migrated_from_kind" not in binding["data"]
    assert "migrated_from_target_ref" not in binding["data"]
    assert "[合约生命周期](factortester://entry_requirement/" in (
        next(
            item for item in migrated["components"]
            if item["component_id"] == "reviewed"
        )["body"]
    )


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
                "title_zh": "代理可观测性",
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


def test_history_migration_rejects_later_obligation_definition_change():
    packet = {
        "graph": "factor-research@v10",
        "node": {"node_id": "validation_design"},
        "context_ref": "context:current",
        "checkpoint_ref": "trace:current",
        "entry_requirements": [],
        "current_obligations": [{
            "obligation_id": "o1",
            "title_zh": "首次标题",
            "status": "discharged",
            "question_summary": "首次问题",
            "requirement_refs": [],
        }],
    }
    contexts = [{
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
            "to_requirement_refs": [],
        }],
        "obligation_presentations": [{
            "obligation_ref": "obligation:o1",
            "title_zh": "首次标题",
            "question_summary": "首次问题",
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
            "from_requirement_refs": [],
            "to_requirement_refs": [],
        }],
        "obligation_presentations": [{
            "obligation_ref": "obligation:o1",
            "title_zh": "后续改写标题",
            "question_summary": "首次问题",
        }],
    }]

    with pytest.raises(
        ValueError,
        match=r"immutable definition conflict: o1\.title_zh.*trace:second",
    ):
        ledger_from_history(
            branch_ref="graph-branch:instance:branch",
            packet=packet,
            contexts=contexts,
        )


def test_history_migration_rejects_current_projection_definition_drift():
    packet = {
        "graph": "factor-research@v10",
        "node": {"node_id": "validation_design"},
        "context_ref": "context:current",
        "checkpoint_ref": "trace:current",
        "entry_requirements": [],
        "current_obligations": [{
            "obligation_id": "o1",
            "title_zh": "被当前投影改写的标题",
            "status": "open",
            "question_summary": "首次问题",
            "requirement_refs": [],
        }],
    }
    contexts = [{
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
            "to_requirement_refs": [],
        }],
        "obligation_presentations": [{
            "obligation_ref": "obligation:o1",
            "title_zh": "首次标题",
            "question_summary": "首次问题",
        }],
    }]

    with pytest.raises(
        ValueError,
        match=(
            r"immutable definition conflict: o1\.title_zh.*"
            r"current projection"
        ),
    ):
        ledger_from_history(
            branch_ref="graph-branch:instance:branch",
            packet=packet,
            contexts=contexts,
        )


def test_history_migration_completes_legacy_creation_from_current_projection():
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
                "obligation_id": "legacy-created",
                "status": "open",
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
                "obligation_id": "legacy-created",
                "from_state": "absent",
                "to_state": "open",
            }],
            "obligation_presentations": [{
                "obligation_ref": "obligation:legacy-created",
                "question_summary": "代理是否可观测",
            }],
        }],
    )

    event = ledger["history"][0]
    assert event["obligation_delta"][0]["to_requirement_refs"] == [
        "observable_proxy",
    ]
    assert event["server_obligation_delta"][0].get(
        "to_requirement_refs",
    ) is None
    assert event["obligations_snapshot"][0]["requirement_refs"] == [
        "observable_proxy",
    ]


def test_history_migration_keeps_obligations_predating_available_timeline():
    ledger = ledger_from_history(
        branch_ref="graph-branch:instance:branch",
        packet={
            "graph": "factor-research@v10",
            "node": {"node_id": "validation_design"},
            "context_ref": "context:current",
            "checkpoint_ref": "trace:current",
            "entry_requirements": [],
            "current_obligations": [{
                "obligation_id": "prehistory",
                "status": "bounded",
                "question_summary": "早期数据覆盖",
                "requirement_refs": [],
            }, {
                "obligation_id": "changed",
                "status": "open",
                "question_summary": "当前问题",
                "requirement_refs": [],
            }],
        },
        contexts=[{
            "side": "target",
            "step_ref": "trace:first",
            "from_node": "factor_semantics",
            "to_node": "validation_design",
            "created_at": 1,
            "obligation_changes": [{
                "obligation_id": "changed",
                "from_state": "absent",
                "to_state": "open",
                "from_requirement_refs": [],
                "to_requirement_refs": [],
            }],
            "obligation_presentations": [],
        }],
    )

    assert {
        item["obligation_id"]
        for item in ledger["history"][0]["obligations_snapshot"]
    } == {"prehistory", "changed"}


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
    for row in rows:
        row.pop("scope_revalidation")
    assert rows == [
        {
            "requirement_id": "mechanism_chain",
            "description": "机制链",
            "obligation_refs": [],
            "obligation_statuses": [],
            "evidence_uses": [],
            "changed": False,
            "node_required": True,
            "edge_required": False,
            "accepted_states": ["bounded", "discharged", "serviced"],
            "minimum_qualification": "limited",
            "satisfaction": "pending",
        },
        {
            "requirement_id": "observable_proxy",
            "description": "代理变量",
            "obligation_refs": ["obligation:o1"],
            "obligation_statuses": ["open"],
            "evidence_uses": [],
            "changed": True,
            "node_required": True,
            "edge_required": True,
            "accepted_states": ["bounded", "discharged", "serviced"],
            "minimum_qualification": "limited",
            "satisfaction": "missing",
        },
        {
            "requirement_id": "boundary_conditions",
            "description": "边界",
            "obligation_refs": [],
            "obligation_statuses": [],
            "evidence_uses": [],
            "changed": False,
            "node_required": True,
            "edge_required": True,
            "accepted_states": ["bounded", "discharged", "serviced"],
            "minimum_qualification": "limited",
            "satisfaction": "missing",
        },
    ]


def test_existing_obligation_definition_cannot_be_rewritten_by_delta():
    with pytest.raises(
        ValueError,
        match=r"immutable definition conflict: o1\.title_zh",
    ):
        apply_obligation_deltas(
            _ledger()["current_projection"]["obligations"],
            [{
                "obligation_id": "o1",
                "from_state": "open",
                "to_state": "bounded",
                "obligation": {
                    "obligation_id": "o1",
                    "title_zh": "被后续状态变化改写的标题",
                    "epistemic_question": "问题",
                },
            }],
        )


def test_existing_obligation_definition_survives_state_and_mapping_change():
    obligations, _ = apply_obligation_deltas(
        _ledger()["current_projection"]["obligations"],
        [{
            "obligation_id": "o1",
            "from_state": "open",
            "to_state": "bounded",
            "from_requirement_refs": ["mechanism_chain"],
            "to_requirement_refs": ["observable_proxy"],
        }],
    )

    assert obligations[0]["title_zh"] == "代理可观测性"
    assert obligations[0]["epistemic_question"] == "问题"


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
    for row in rows:
        row.pop("scope_revalidation")
    assert rows == [{
        "requirement_id": "observable_proxy",
        "description": "代理变量",
        "obligation_refs": ["obligation:o1", "obligation:o2"],
        "obligation_statuses": ["serviced", "discharged"],
        "evidence_uses": [],
        "changed": True,
        "node_required": True,
        "edge_required": True,
        "accepted_states": ["bounded", "discharged", "serviced"],
        "minimum_qualification": "limited",
        "satisfaction": "satisfied",
    }]


def test_evidence_use_is_many_to_many_and_required_for_new_edge_advance():
    obligations = [{
        "obligation_id": "o1",
        "status": "discharged",
        "requirement_refs": ["mechanism_chain", "observable_proxy"],
        "scope": {"factor_ref": _FACTOR_REF},
        "claim_scopes": [],
    }]
    uses, changed = apply_evidence_use_deltas(
        [],
        [{"op": "add", "use": {
            **_use("o1", "mechanism_chain"),
            "requirement_refs": ["mechanism_chain", "observable_proxy"],
            "use_id": None,
        }}],
        obligations=obligations,
    )
    assert len(changed) == 1
    rows = project_requirement_coverage(
        requirements=[
            {"requirement_id": "mechanism_chain"},
            {"requirement_id": "observable_proxy"},
        ],
        obligations=obligations,
        evidence_uses=uses,
        edge_required_ids={"mechanism_chain", "observable_proxy"},
        enforce_evidence=True,
    )
    assert [item["satisfaction"] for item in rows] == [
        "satisfied", "satisfied",
    ]
    assert all(item["evidence_uses"] == uses for item in rows)


def test_new_edge_advance_rejects_state_only_coverage_without_evidence_use():
    rows = project_requirement_coverage(
        requirements=[{"requirement_id": "mechanism_chain"}],
        obligations=[{
            "obligation_id": "o1",
            "status": "discharged",
            "requirement_refs": ["mechanism_chain"],
        }],
        evidence_uses=[],
        edge_required_ids={"mechanism_chain"},
        enforce_evidence=True,
    )
    assert rows[0]["satisfaction"] == "missing"


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


def test_ledger_rejects_definition_drift_between_history_and_projection():
    ledger = append_event(
        _ledger(),
        event_type="advance_prepared",
        event_id="attempt-definition-freeze",
        payload={
            "obligations_snapshot": deepcopy(
                _ledger()["current_projection"]["obligations"]
            ),
        },
    )
    ledger["current_projection"]["obligations"][0][
        "epistemic_question"
    ] = "目标节点投影试图改写问题"

    with pytest.raises(
        ValueError,
        match=r"immutable definition conflict: o1\.epistemic_question",
    ):
        canonicalize_ledger(ledger)


def test_ledger_backfills_a_missing_definition_from_first_snapshot():
    ledger = append_event(
        _ledger(),
        event_type="advance_prepared",
        event_id="attempt-definition-backfill",
        payload={
            "obligations_snapshot": deepcopy(
                _ledger()["current_projection"]["obligations"]
            ),
        },
    )
    ledger["current_projection"]["obligations"][0][
        "epistemic_question"
    ] = ""

    normalized = canonicalize_ledger(ledger)

    assert normalized["current_projection"]["obligations"][0][
        "epistemic_question"
    ] == "问题"


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


def test_evidence_migration_retry_is_idempotent_for_schema_v2(tmp_path):
    write_ledger(tmp_path, "branch", _ledger())

    result = _migrate(
        scope=SimpleNamespace(package_root=tmp_path),
        branch_id="branch",
        report_scope_resolver=lambda _scope: (_ for _ in ()).throw(
            AssertionError("already-migrated retry must not resolve report")
        ),
        apply_migration=True,
    )

    assert result["status"] == "already_migrated"
    assert result["state_changed"] is False
    assert result["from_schema_version"] == 2
    assert result["to_schema_version"] == 2


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


def test_fork_rejects_server_obligation_definition_drift(tmp_path):
    source_root = tmp_path / "source"
    write_ledger(source_root, "source-branch", _ledger())

    with pytest.raises(
        ValueError,
        match=r"immutable definition conflict: o1\.epistemic_question",
    ):
        inherit_obligation_ledger(
            source_package_root=source_root,
            target_package_root=tmp_path / "target",
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
                    "title_zh": "代理可观测性",
                    "status": "open",
                    "question_summary": "被 continuation 改写的问题",
                    "requirement_refs": ["mechanism_chain"],
                }],
                "entry_requirements": [],
            },
            inheritance_kind="branch_fork",
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
                "title_zh": "代理可观测性",
                "epistemic_question": "代理变量是否可观测",
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
            }, {
                "requirement_id": "mechanism_chain",
                "description": "机制作用链",
                "obligation_refs": [],
                "obligation_statuses": [],
                "changed": True,
                "node_required": False,
                "edge_required": False,
                "satisfaction": "pending",
            }],
        },
    )
    assert [item["kind"] for item in operations] == [
        "special", "section", "table", "section", "table", "section", "table",
    ]
    assert operations[1]["parent_id"] == ids["special_id"]
    assert operations[2]["parent_id"] == operations[1]["component_id"]
    assert operations[3]["parent_id"] == ids["special_id"]
    assert operations[4]["parent_id"] == operations[3]["component_id"]
    assert operations[5]["parent_id"] == ids["special_id"]
    assert operations[6]["parent_id"] == operations[5]["component_id"]
    assert operations[2]["content"]["columns"][4:6] == [
        "新增覆盖小类", "移除覆盖小类",
    ]
    assert operations[2]["content"]["columns"][6:] == [
        "新增证据", "移除证据", "证据使用理由",
    ]
    assert operations[3]["display_kind"] == "current_obligations"
    assert operations[5]["display_kind"] == (
        "obligation_requirement_coverage"
    )
    assert operations[6]["content"]["columns"][-1] == "满足状态"
    assert "[代理可观测性](factortester://obligation/" in (
        operations[2]["content"]["rows"][0][0]
    )
    assert "[可观测代理](factortester://entry_requirement/" in (
        operations[6]["content"]["rows"][0][0]
    )
    assert {item["kind"] for item in operations[2]["bindings"]} == {
        "obligation",
    }
    assert {item["kind"] for item in operations[6]["bindings"]} == {
        "entry_requirement",
        "obligation",
    }


def test_edge_coverage_table_regenerates_typed_link_bindings():
    operation, component_id = edge_coverage_operation(
        event_id="event-one",
        obligations=[
            {"obligation_id": "o1", "title_zh": "代理可观测性"},
            {"obligation_id": "o2", "title_zh": "代理验证结论"},
        ],
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
    assert operation["title"] == ""
    assert operation["display_kind"] == ""
    assert component_id.startswith("obligation-requirement-table-")
    assert {item["kind"] for item in operation["bindings"]} == {
        "entry_requirement",
        "obligation",
    }
    assert all(
        item["binding_id"].startswith("reference-")
        for item in operation["bindings"]
    )


def test_node_exit_coverage_uses_an_ordinary_section_and_untitled_table():
    operations, component_ids = node_exit_operations(
        parent_id="chapter-factor-semantics",
        event={
            "event_id": "advance-one",
            "edge_id": "factor_semantics__validation_design",
            "target_node": "validation_design",
            "coverage_hash": "sha256:coverage",
            "receipt": {
                "trace_ref": "trace:next",
                "checkpoint_ref": "trace:next",
            },
            "coverage_snapshot": [],
            "obligations_snapshot": [],
        },
    )

    assert [item["kind"] for item in operations] == [
        "special", "section", "table",
    ]
    assert operations[1]["title"] == "精确提交的覆盖清单"
    assert operations[1]["parent_id"] == component_ids["special_id"]
    assert operations[2]["title"] == ""
    assert operations[2]["parent_id"] == operations[1]["component_id"]


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


def test_reading_reserved_submission_does_not_materialize_sidecar(tmp_path):
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

    reconciled = reconcile_pending(paths, load_head(paths))

    assert reconciled["phase"] == "reserved"
    assert not (tmp_path / "branches" / "branch" / "obligations.json").exists()


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
    ledger["current_projection"]["evidence_uses"] = [
        _use("o1", "mechanism_chain"),
    ]
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
                    "scope_policy": {
                        "required_scope": {
                            "factor_refs": [_FACTOR_REF],
                        },
                    },
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


def test_prepare_advance_submits_evidence_used_by_obligation_coverage(tmp_path):
    fixture = _prepared_package(tmp_path)
    fixture["evidence"]["evidence_refs"] = [
        "evidence:diagnostic:sha256:" + "f" * 64,
    ]

    prepared = prepare_obligation_advance(
        package_root=tmp_path,
        branch_id="branch",
        edge_id="factor_semantics__validation_design",
        source_report_parent_id="chapter-factor-semantics",
        **fixture,
    )

    assert prepared.evidence["evidence_refs"] == [
        "evidence:diagnostic:sha256:" + "f" * 64,
        "evidence:diagnostic:sha256:" + "o" * 64,
    ]


def test_prepare_advance_applies_edge_scope_to_all_coverage_rows(tmp_path):
    fixture = _prepared_package(tmp_path)
    fixture["node_packet"]["entry_requirements"].append({
        "requirement_id": "node_only",
        "title_zh": "仅节点要求",
    })
    fixture["evidence"]["entry_requirement_assessments"].append({
        "requirement_id": "node_only",
        "applicability": {},
        "coverage": {
            "decision": "create_new",
            "obligation_refs": ["obligation:wrong"],
        },
        "resolution": {},
        "entry_effect": {},
    })
    ledger = load_ledger(tmp_path, "branch")
    ledger["current_projection"]["obligations"].append({
        "obligation_id": "o2",
        "status": "discharged",
        "epistemic_question": "节点要求是否满足",
        "requirement_refs": ["node_only"],
        "scope": {"factor_ref": _FACTOR_REF},
        "claim_scopes": [],
    })
    ledger["current_projection"]["evidence_uses"].append(
        _use("o2", "node_only")
    )
    write_ledger(tmp_path, "branch", canonicalize_ledger(ledger))

    prepared = prepare_obligation_advance(
        package_root=tmp_path,
        branch_id="branch",
        edge_id="factor_semantics__validation_design",
        source_report_parent_id="chapter-factor-semantics",
        **fixture,
    )

    assert {
        row["requirement_id"]: row["scope_revalidation"]["required_scope"]
        for row in prepared.coverage_submission["coverage"]
    } == {
        "mechanism_chain": {"factor_refs": [_FACTOR_REF]},
        "node_only": {"factor_refs": [_FACTOR_REF]},
    }


def test_prepare_advance_uses_fresh_packet_context(tmp_path):
    fixture = _prepared_package(tmp_path)
    prepared = prepare_obligation_advance(
        package_root=tmp_path,
        branch_id="branch",
        edge_id="factor_semantics__validation_design",
        source_report_parent_id="chapter-factor-semantics",
        **fixture,
    )

    expected = fixture["node_packet"]["context_ref"]
    assert prepared.coverage_submission["context_ref"] == expected
    assert load_ledger(tmp_path, "branch")["branch"]["context_ref"] == expected


def test_prepare_advance_reconciles_compact_server_coverage_scope(tmp_path):
    fixture = _prepared_package(tmp_path)
    ledger = load_ledger(tmp_path, "branch")
    ledger["current_projection"]["obligations"][0]["scope"] = {}
    write_ledger(tmp_path, "branch", canonicalize_ledger(ledger))
    fixture["node_packet"]["current_obligations"] = [{
        "obligation_id": "o1",
        "status": "discharged",
        "requirement_refs": ["mechanism_chain"],
        "coverage_scope": {"factor_refs": [_FACTOR_REF]},
    }]

    prepared = prepare_obligation_advance(
        package_root=tmp_path,
        branch_id="branch",
        edge_id="factor_semantics__validation_design",
        source_report_parent_id="chapter-factor-semantics",
        **fixture,
    )

    row = prepared.coverage_submission["coverage"][0]
    assert row["scope_revalidation"]["status"] == "matched"
    assert row["scope_revalidation"]["failures"] == []


def test_edge_only_requirement_does_not_become_node_entry_assessment(tmp_path):
    fixture = _prepared_package(tmp_path)
    ledger = load_ledger(tmp_path, "branch")
    ledger["current_projection"]["obligations"].append({
        "obligation_id": "o2",
        "status": "discharged",
        "epistemic_question": "边约束是否满足",
        "requirement_refs": ["edge_only"],
        "scope": {"factor_ref": _FACTOR_REF},
        "claim_scopes": [],
    })
    ledger["current_projection"]["evidence_uses"].append(
        _use("o2", "edge_only")
    )
    ledger["current_projection"]["selected_edge"][
        "required_requirement_ids"
    ] = ["mechanism_chain", "edge_only"]
    write_ledger(tmp_path, "branch", canonicalize_ledger(ledger))
    fixture["edge_packet"]["edge"]["obligation_requirements"].append({
        "requirement_id": "edge_only",
        "title_zh": "仅边要求",
        "scope_policy": {
            "required_scope": {"factor_refs": [_FACTOR_REF]},
        },
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
