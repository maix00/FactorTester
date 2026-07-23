from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting import (
    finalize_historical_research_backfill,
    publish_research_checkpoint as _publish_checkpoint,
    stage_historical_research_checkpoint,
)
from tools.cli.release.research_reporting.publisher import (
    publish_current_node_report_checkpoint,
)
from tools.cli.release.research_reporting.report_items import (
    report_fragment_hash,
    report_item_hash,
)
from tools.cli.release.research_reporting.assets import stage_report_asset
from tools.cli.release.research_reporting.presentation_migration import (
    migrate_factor_meta_parameter_markup,
    migrate_trace_evidence_rows,
)
from tools.cli.release.research_reporting.journal import (
    build_fragment,
    content_hash,
    fragment_payload,
    load_fragments,
)
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)


def _carrier() -> dict:
    return {
        "schema_version": 2,
        "workspace_ref": "workspace:workspace-maxa",
        "work_package_ref": "work-package:sgccs-review",
        "branch_ref": "graph-branch:sgccs-review:branch-sgccs",
        "graph_ref": "factor-research@v6",
        "checkpoint_ref": "trace:checkpoint-1",
        "research_cycle_ref": "research-cycle:sha256:" + "4" * 64,
        "title": "SgCCS checkpoint",
        "product_group": "CNFutures",
        "current_node": "job_evidence_ready",
        "status": "running",
        "decision_contract_hash": "2" * 64,
        "methodology_hash": "1" * 64,
        "trial_plan_hash": "3" * 64,
        "evidence_refs": ["evidence:job-attempt-1"],
        "omitted_evidence_count": 0,
        "job_refs": ["job:job-1"],
        "run_refs": ["run:run-1"],
        "claims": [{
            "claim_ref": "claim:predictive-relation",
            "claim_type": "bounded_predictive_relationship",
            "evidence_state": "inconclusive",
        }],
        "open_obligations": [{
            "obligation_ref": "obligation:cost-survival",
            "status": "open",
            "materiality": "decision_blocking",
            "question_summary": "Does the signal survive costs?",
        }],
        "closure": None,
        "report_lineage": {
            "status": "root",
            "predecessor_checkpoint_ref": "",
        },
        "latest_transition": {
            "step_ref": "trace:checkpoint-1",
            "edge_ref": "graph-edge:backtest__job_evidence_ready",
            "from_node": "authoritative_backtest",
            "to_node": "job_evidence_ready",
            "created_at": 2.0,
            "evidence_refs": ["evidence:job-attempt-1"],
            "trial_plan_refs": ["trial-plan:sha256:" + "3" * 64],
            "obligation_refs": ["obligation:cost-survival"],
            "claim_refs": ["claim:predictive-relation"],
            "job_refs": ["job:job-1"],
            "run_refs": ["run:run-1"],
            "delta_refs": [],
            "obligation_changes": [],
            "claim_changes": [],
        },
    }


def _link_after(carrier: dict, predecessor: str) -> None:
    carrier["report_lineage"] = {
        "status": "linked",
        "predecessor_checkpoint_ref": predecessor,
    }


def _narrative(
    carrier: dict,
    *,
    body: str = "本次检验显示信号仍需结合成本证据继续研究。",
) -> dict:
    targets = [
        ("evidence", ref) for ref in carrier["evidence_refs"]
    ] + [
        ("job", ref) for ref in carrier["job_refs"]
    ] + [
        ("run", ref) for ref in carrier["run_refs"]
    ] + [
        ("trial_plan", ref)
        for ref in carrier["latest_transition"]["trial_plan_refs"]
    ] + [
        ("obligation", ref)
        for ref in carrier["latest_transition"]["obligation_refs"]
    ] + [
        ("claim", ref)
        for ref in carrier["latest_transition"]["claim_refs"]
    ] + [
        ("delta", ref)
        for ref in carrier["latest_transition"]["delta_refs"]
    ]
    return {
        "schema_version": 1,
        "language": "zh-Hans",
        "title": "因子研究报告",
        "sections": [{
            "section_id": "research-progress",
            "title": "研究进展",
            "body": body,
            "links": [
                {
                    "link_id": f"checkpoint-{index}",
                    "kind": kind,
                    "target_ref": target_ref,
                }
                for index, (kind, target_ref) in enumerate(targets)
            ],
        }],
    }


def _historical_narrative(
    *, occurred_at: float, text: str = "本阶段完成了历史研究过程补登记。",
) -> dict:
    return {
        "schema_version": 3,
        "language": "zh-Hans",
        "title": "因子研究报告",
        "research_occurred_at": occurred_at,
        "time_basis": "historical_backfill",
        "time_source_refs": ["conversation:maxa-history"],
        "sections": [{
            "section_id": "research-progress",
            "title": "研究进展",
            "blocks": [{"kind": "paragraph", "text": text}],
            "links": [],
        }],
    }


def publish_research_checkpoint(**kwargs):
    carrier = kwargs["carrier"]
    kwargs.setdefault("narrative", _narrative(carrier))
    return _publish_checkpoint(**kwargs)


def test_historical_presentation_migration_rehashes_canonical_objects_only():
    carrier = _carrier()
    checkpoint = {
        "schema_version": 1,
        "contract_hash": "2" * 64,
        "methodology_hash": "1" * 64,
        "trial_plan_hash": "",
        "claims": [],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "sgccs-data-coverage-feasibility",
            "obligation_kind": "data_availability_for_trial_design",
            "epistemic_question": "What exact causal data are available?",
            "scope": {"product_group": "china_futures"},
            "claim_ids": [],
            "materiality": "decision_blocking",
            "status": "open",
            "discharge_criterion": {"rule_ref": "research-rule:data"},
            "contract_hash": "2" * 64,
            "methodology_hash": "1" * 64,
            "created_event_ref": "event:bootstrap",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
        "closure": None,
    }
    checkpoint = validate_research_cycle_checkpoint(checkpoint)
    envelope = validate_agent_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "availability",
        "evidence_kind": "data_availability",
        "source_refs": ["data-profile:test"],
        "identity_refs": {
            "contract_hash": "2" * 64,
            "methodology_hash": "1" * 64,
        },
        "facts": {
            "product_status": [{"product": "LH.DCE", "available": True}],
        },
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    })
    old_ref = "evidence:" + envelope["envelope_hash"]
    rows = [{
        "trace_id": "trace-1",
        "evidence": {
            "evidence_refs": [old_ref],
            "server_evidence": {"availability": envelope},
            "research_cycle": {
                "schema_version": 1,
                "bootstrap_checkpoint": True,
                "checkpoint_before_hash": checkpoint["projection_hash"],
                "parent_trace_ref": "",
                "events": [],
            },
            "research_cycle_checkpoint": checkpoint,
        },
    }]

    migrated, receipt = migrate_trace_evidence_rows(rows)
    after = migrated[0]["evidence"]
    migrated_envelope = after["server_evidence"]["availability"]

    assert migrated_envelope["title"] == "LH.DCE 的历史数据覆盖清单"
    assert "查询范围" in migrated_envelope["claim_summary"]
    assert after["evidence_refs"] == [
        "evidence:" + migrated_envelope["envelope_hash"]
    ]
    assert (
        after["research_cycle_checkpoint"]["obligations"][0]["status"]
        == "open"
    )
    assert "点时数据" in (
        after["research_cycle_checkpoint"]["obligations"][0][
            "epistemic_question"
        ]
    )
    assert receipt["input_hash"] != receipt["output_hash"]
    assert rows[0]["evidence"]["evidence_refs"] == [old_ref]


def test_factor_meta_parameter_markup_migration_is_idempotent(tmp_path: Path):
    sections = [{
        "section_id": "semantics",
        "title": "参数语义",
        "body": "$F 与 $Rev 是元参数；`$F` 已正确标记。",
        "evidence_refs": [],
        "asset_refs": [],
        "links": [],
        "created_at": 1.0,
    }]
    fragment = build_fragment(
        checkpoint_ref="trace:checkpoint-1",
        created_at=1.0,
        carrier_hash="1" * 64,
        narrative_hash="2" * 64,
        sections=sections,
        evidence_refs=[],
        gaps=[],
        lineage={"status": "root", "predecessor_checkpoint_ref": ""},
        graph_ref="factor-research@v9",
        branch_ref="graph-branch:instance:branch",
        edge_ref="graph-edge:factor_semantics",
    )
    root = tmp_path / "package"
    path = root / "branches" / "branch" / "sections"
    path.mkdir(parents=True)
    (path / f"{fragment['section_hash']}.json").write_bytes(
        fragment_payload(fragment)
    )

    changes, count = migrate_factor_meta_parameter_markup(package_root=root)
    replay_changes, replay_count = migrate_factor_meta_parameter_markup(
        package_root=root
    )
    migrated = load_fragments(path)[0]

    assert count == 2
    assert "`$F` 与 `$Rev`" in migrated["sections"][0]["body"]
    assert migrated["sections"][0]["body"].count("`$F`") == 2
    assert changes[0]["before_narrative_hash"] == "2" * 64
    assert changes[0]["after_section_hash"] == migrated["section_hash"]
    assert replay_changes == []
    assert replay_count == 0


def test_ordinary_checkpoint_does_not_require_untouched_cycle_snapshot(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    carrier["evidence_refs"].append("evidence:earlier-checkpoint")
    carrier["latest_transition"]["obligation_refs"] = []
    carrier["latest_transition"]["claim_refs"] = []
    narrative = _narrative(carrier)
    narrative["sections"][0]["links"] = [
        item for item in narrative["sections"][0]["links"]
        if item["target_ref"] != "evidence:earlier-checkpoint"
    ]

    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
        narrative=narrative,
    )


def test_checkpoint_accepts_bounded_entry_resolution_projection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    carrier["latest_transition"]["entry_resolution"] = {
        "reason": "graph_continuation",
        "assessed_requirement_ids": ["data.source_availability"],
        "reused_requirement_ids": ["data.source_availability"],
        "reference_only_requirement_ids": [],
        "unresolved_requirement_ids": [],
        "items": [{
            "requirement_id": "data.source_availability",
            "title_zh": "是否有数据源覆盖目标产品、合约和市场",
            "assessed": True,
            "change_kind": "revised",
            "resolution_status": "reused",
        }],
        "resume_node": "job_evidence_ready",
    }

    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
    )


def _profile(root: Path) -> LocalProfileStore:
    store = LocalProfileStore(root)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=root / "profile-root",
    )
    profile["agents"] = [{
        "agent_id": "research-maxa",
        "role": "research",
        "scope": {
            "instance_id": "sgccs-review",
            "branch_id": "branch-sgccs",
        },
        "status": "ready",
        "next_action": "Resume the authorized research scope.",
    }]
    profile["workspaces"] = [{
        "workspace_id": "workspace-maxa",
        "path": str(root / "user-factor-library"),
        "access_mode": "owner",
        "owner_ref": "18717974771",
        "server_workspace_ref": "workspace:workspace-maxa",
    }]
    profile["research_records"] = [{
        "record_id": "sgccs-review",
        "title": "SgCCS review",
        "status": "pending",
        "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["MaxA:SgCCS@7"],
        "agent_id": "research-maxa",
        "created_at": 1.0,
        "updated_at": 1.0,
        "workspace_ref": "workspace:workspace-maxa",
        "run_ref": "",
        "graph_instance_ref": "work-package:sgccs-review",
        "graph_branch_ref": "graph-branch:sgccs-review:branch-sgccs",
        "checkpoint_ref": "",
        "evidence_refs": [],
        "timeline_refs": [],
        "artifacts": [],
        "provenance": {
            "kind": "owned_research",
            "owner_ref": "maxa",
        },
    }]
    store.save(profile)
    return store


def test_current_node_maxa_projection_updates_real_journal_index_and_report(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
    )
    local_items = []
    for index in range(18):
        binding = {
            "report_requirement_id": f"maxa.requirement.{index + 1}",
            "subject_ref": "factor:SgCPSVol",
        }
        link = {
            "link_id": "fact",
            "kind": "evidence",
            "target_ref": f"evidence:maxa-{index + 1}",
            "label": "研究事实",
        }
        if index == 0:
            content = {
                "kind": "math",
                "latex": (
                    r"\operatorname{SgCPSVol}_{t}"
                    r"=\sigma\!\left(r_{t-19:t}\right)"
                ),
                "fallback": "SgCPSVol 为二十日收益率波动率。",
                "link_ids": ["fact"],
            }
            content_kind = "figure"
        else:
            content = {
                "kind": "list",
                "rows": [{
                    "text": f"第{index + 1}项中文语义已完成核对。",
                    "link_ids": ["fact"],
                }],
            }
            content_kind = "list"
        item_hash = report_item_hash(
            **binding, content_kind=content_kind, content=content,
        )
        local_items.append({
            **binding,
            "title_zh": (
                "因子公式、方向与单位"
                if index == 0 else f"第{index + 1}项语义核对"
            ),
            "content_kind": content_kind,
            "item_hash": item_hash,
            "content": content,
            "content_zh": ["中文语义"],
            "links": [link],
            "report_binding": binding,
        })
    projected = [
        {
            key: item[key] for key in (
                "report_requirement_id", "subject_ref",
                "content_kind", "item_hash",
            )
        }
        for item in local_items
    ]
    result = publish_current_node_report_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
        projection={
            "report_submission": {
                "schema_version": 1,
                "fragment_hash": report_fragment_hash(projected),
                "items": projected,
            },
            "local_report_items": local_items,
        },
    )

    package = root / "profile-root" / "research" / "sgccs-review"
    journal = (package / "branches" / "branch-sgccs" /
               "LOGICAL_JOURNAL.json").read_text(encoding="utf-8")
    index = (package / "INDEX.json").read_text(encoding="utf-8")
    report = (
        package / "branches" / "branch-sgccs" / "REPORT.md"
    ).read_text(encoding="utf-8")
    assert result["checkpoint_ref"].startswith("report-checkpoint:sha256:")
    assert result["journal_artifact_ref"].startswith(
        "journal-artifact:sha256:"
    )
    assert "report-checkpoint:sha256:" in journal
    assert "report-checkpoint:sha256:" in index
    assert r"\operatorname{SgCPSVol}_{t}" in report
    assert "第18项中文语义已完成核对" in report
    assert "有 2 条证据引用未随本次载荷提供" in report
    journal_value = json.loads(journal)
    assert journal_value["checkpoints"][-1]["sections"][0]["title"] == (
        "因子公式、方向与单位"
    )
    assert journal_value["checkpoints"][-1]["sections"][17]["title"] == (
        "第18项语义核对"
    )
    assert len(journal_value["checkpoints"][-1]["sections"]) == 18
    assert {
        link["target_ref"]
        for section in journal_value["checkpoints"][-1]["sections"]
        for link in section["links"]
        if link["kind"] == "evidence"
    } == {f"evidence:maxa-{index + 1}" for index in range(18)}
    assert len(result["report_submission"]["items"]) == 18
    section_ids = [
        section["section_id"]
        for section in journal_value["checkpoints"][-1]["sections"]
    ]
    assert len(section_ids) == len(set(section_ids))
    assert all("-current-node-" in value for value in section_ids)
    assert all("-current-node-report-" not in value for value in section_ids)
    replay = publish_current_node_report_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
        projection={
            "report_submission": {
                "schema_version": 1,
                "fragment_hash": report_fragment_hash(projected),
                "items": projected,
            },
            "local_report_items": local_items,
        },
    )
    assert replay["checkpoint_ref"] == result["checkpoint_ref"]
    assert replay["changed"] is False


def test_stages_content_addressed_passive_report_image_once(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    source = tmp_path / "curve.svg"
    source.write_bytes(
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b"<title>curve</title></svg>"
    )

    first = stage_report_asset(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        work_package_ref="work-package:sgccs-review",
        source_path=source,
        media_type="image/svg+xml",
        caption="净值曲线与回撤",
        alt_text="SgCCS 回测净值曲线",
        provenance_refs=["job:job-1", "evidence:job-attempt-1"],
    )
    second = stage_report_asset(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        work_package_ref="work-package:sgccs-review",
        source_path=source,
        media_type="image/svg+xml",
        caption="净值曲线与回撤",
        alt_text="SgCCS 回测净值曲线",
        provenance_refs=["job:job-1", "evidence:job-attempt-1"],
    )

    first_asset = first["asset"]
    target = (
        Path(store.load("maxa")["workspace_root"])
        / "research" / "sgccs-review" / "assets"
        / first_asset["filename"]
    )
    assert first["changed"] is True
    assert second["changed"] is False
    assert first_asset["asset_ref"] == (
        f"report-asset:sha256:{first_asset['content_hash']}"
    )
    assert target.read_bytes() == source.read_bytes()


def test_rejects_active_or_external_report_svg(tmp_path: Path) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    source = tmp_path / "active.svg"
    source.write_bytes(
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b'<script>alert("x")</script></svg>'
    )

    with pytest.raises(ValueError, match="passive"):
        stage_report_asset(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            work_package_ref="work-package:sgccs-review",
            source_path=source,
            media_type="image/svg+xml",
            caption="不可信图像",
            alt_text="",
            provenance_refs=["job:job-1"],
        )


def test_checkpoint_embeds_staged_curve_in_markdown_and_journal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    source = tmp_path / "curve.svg"
    source.write_bytes(
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b"<title>equity</title><path d=\"M0 0L10 10\"/></svg>"
    )
    staged = stage_report_asset(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        work_package_ref="work-package:sgccs-review",
        source_path=source,
        media_type="image/svg+xml",
        caption="净值曲线与回撤",
        alt_text="SgCCS 回测净值曲线与回撤",
        provenance_refs=["job:job-1", "evidence:job-attempt-1"],
    )
    carrier = _carrier()
    base = _narrative(carrier)
    links = base["sections"][0]["links"]
    result_links = [
        item for item in links
        if item["kind"] in {"evidence", "job", "run"}
    ]
    figure_links = [
        item for item in links
        if item["kind"] not in {"evidence", "job", "run"}
    ]
    narrative = {
        "schema_version": 2,
        "language": "zh-Hans",
        "title": "因子研究报告",
        "sections": [{
            "section_id": "backtest-result",
            "title": "回测结果",
            "blocks": [
                {
                    "kind": "table",
                    "columns": ["对象", "结果"],
                    "rows": [{
                        "cells": [item["kind"], "已生成"],
                        "link_ids": [item["link_id"]],
                    } for item in result_links],
                    "result_kind": "backtest",
                },
                {
                    "kind": "figure",
                    "asset": staged["asset"],
                    "link_ids": [
                        item["link_id"] for item in figure_links
                    ],
                },
            ],
            "links": links,
        }],
    }

    result = publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
        narrative=narrative,
    )

    workspace = Path(store.load("maxa")["workspace_root"])
    report = Path(result["artifact"]["local_ref"].removeprefix("file://"))
    journal = Path(result["artifact"]["journal_ref"].removeprefix("file://"))
    report_text = report.read_text(encoding="utf-8")
    journal_value = json.loads(journal.read_text(encoding="utf-8"))
    assert (
        f"../../assets/{staged['asset']['filename']}" in report_text
    )
    figure = journal_value["checkpoints"][0]["sections"][0]["blocks"][1]
    assert figure["kind"] == "figure"
    assert figure["asset"] == staged["asset"]
    assert (
        workspace / "research" / "sgccs-review" / "assets"
        / staged["asset"]["filename"]
    ).is_file()


def test_historical_backfill_stages_without_moving_local_head_and_finalizes_once(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["research_records"][0].update({
        "checkpoint_ref": "trace:checkpoint-2",
        "updated_at": 3.0,
    })
    store.save(profile)
    record_before_finalize = deepcopy(
        store.load("maxa")["research_records"][0]
    )
    profile_path = root / "profiles" / "maxa.json"
    before_stage = profile_path.read_bytes()

    first = _carrier()
    first.update({
        "current_node": "factor_semantics",
        "evidence_refs": [],
        "job_refs": [],
        "run_refs": [],
        "claims": [],
        "open_obligations": [],
    })
    first["latest_transition"].update({
        "to_node": "factor_semantics",
        "evidence_refs": [],
        "trial_plan_refs": [],
        "obligation_refs": [],
        "claim_refs": [],
        "job_refs": [],
        "run_refs": [],
        "delta_refs": [],
    })
    staged = stage_historical_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        current_branch_id="branch-sgccs",
        carrier=first,
        narrative=_historical_narrative(occurred_at=1.5),
    )

    assert staged["changed"] is True
    assert staged["finalized"] is False
    assert profile_path.read_bytes() == before_stage
    package_root = root / "profile-root" / "research" / "sgccs-review"
    fragments = list((
        package_root / "branches" / "branch-sgccs" / "sections"
    ).glob("*.json"))
    assert len(fragments) == 1
    assert not (package_root / "INDEX.json").exists()
    assert not (package_root / "branches" / "branch-sgccs" / "REPORT.md").exists()

    replay = stage_historical_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        current_branch_id="branch-sgccs",
        carrier=first,
        narrative=_historical_narrative(occurred_at=1.5),
    )
    assert replay["changed"] is False

    current = deepcopy(first)
    current["checkpoint_ref"] = "trace:checkpoint-2"
    current["latest_transition"].update({
        "step_ref": "trace:checkpoint-2",
        "created_at": 3.0,
    })
    _link_after(current, "trace:checkpoint-1")
    finalized = finalize_historical_research_backfill(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=current,
        narrative=_historical_narrative(occurred_at=2.5),
    )

    assert finalized["changed"] is True
    assert finalized["finalized"] is True
    assert (package_root / "INDEX.json").is_file()
    assert (package_root / "branches" / "branch-sgccs" / "REPORT.md").is_file()
    saved = store.load("maxa")["research_records"][0]
    assert saved["checkpoint_ref"] == "trace:checkpoint-2"
    assert saved["updated_at"] == 3.0
    assert saved["created_at"] == 1.0
    assert saved["timeline_refs"]
    assert {
        key: value for key, value in saved.items()
        if key not in {"artifacts", "timeline_refs"}
    } == {
        key: value for key, value in record_before_finalize.items()
        if key not in {"artifacts", "timeline_refs"}
    }
    journal = json.loads((
        package_root / "branches" / "branch-sgccs" / "LOGICAL_JOURNAL.json"
    ).read_text())
    assert [item["checkpoint_ref"] for item in journal["checkpoints"]] == [
        "trace:checkpoint-1", "trace:checkpoint-2",
    ]
    replay_finalize = finalize_historical_research_backfill(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=current,
        narrative=_historical_narrative(occurred_at=2.5),
    )
    assert replay_finalize["changed"] is False
    assert store.load("maxa")["research_records"][0] == saved


def test_historical_backfill_conflict_and_broken_lineage_fail_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["research_records"][0].update({
        "checkpoint_ref": "trace:checkpoint-2",
        "updated_at": 3.0,
    })
    store.save(profile)
    first = _carrier()
    first.update({
        "current_node": "factor_semantics",
        "evidence_refs": [], "job_refs": [], "run_refs": [],
        "claims": [], "open_obligations": [],
    })
    first["latest_transition"].update({
        "to_node": "factor_semantics",
        "evidence_refs": [], "trial_plan_refs": [],
        "obligation_refs": [], "claim_refs": [],
        "job_refs": [], "run_refs": [], "delta_refs": [],
    })
    stage_historical_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        current_branch_id="branch-sgccs",
        carrier=first,
        narrative=_historical_narrative(occurred_at=1.5),
    )
    profile_path = root / "profiles" / "maxa.json"
    before = profile_path.read_bytes()

    with pytest.raises(ValueError, match="conflicting narrative"):
        stage_historical_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            current_branch_id="branch-sgccs",
            carrier=first,
            narrative=_historical_narrative(
                occurred_at=1.5,
                text="本阶段形成了相互冲突的历史叙事。",
            ),
        )

    current = deepcopy(first)
    current["checkpoint_ref"] = "trace:checkpoint-2"
    current["latest_transition"].update({
        "step_ref": "trace:checkpoint-2", "created_at": 3.0,
    })
    _link_after(current, "trace:missing-checkpoint")
    with pytest.raises(ValueError, match="lineage is incomplete"):
        finalize_historical_research_backfill(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=current,
            narrative=_historical_narrative(occurred_at=2.5),
        )

    assert profile_path.read_bytes() == before
    package_root = root / "profile-root" / "research" / "sgccs-review"
    assert not (package_root / "INDEX.json").exists()
    assert len(list((
        package_root / "branches" / "branch-sgccs" / "sections"
    ).glob("*.json"))) == 1


def test_historical_backfill_never_invents_a_legacy_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["research_records"][0].update({
        "checkpoint_ref": "trace:checkpoint-2",
        "updated_at": 3.0,
    })
    store.save(profile)
    carrier = _carrier()
    carrier["report_lineage"] = {
        "status": "history_incomplete",
        "predecessor_checkpoint_ref": "",
    }

    with pytest.raises(ValueError, match="trusted root"):
        stage_historical_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            current_branch_id="branch-sgccs",
            carrier=carrier,
            narrative=_historical_narrative(occurred_at=1.5),
        )


def test_historical_backfill_requires_cross_incarnation_root_before_head(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["agents"][0]["scope"] = {
        "instance_id": "physical-v8", "branch_id": "branch-v8",
    }
    profile["research_records"][0].update({
        "graph_branch_ref": "graph-branch:physical-v8:branch-v8",
        "checkpoint_ref": "trace:checkpoint-v8",
        "updated_at": 3.0,
    })
    store.save(profile)

    root_v7 = _carrier()
    root_v7.update({
        "branch_ref": "graph-branch:physical-v7:branch-v7",
        "current_node": "factor_semantics",
        "evidence_refs": [], "job_refs": [], "run_refs": [],
        "claims": [], "open_obligations": [],
    })
    root_v7["checkpoint_ref"] = "trace:checkpoint-v7"
    root_v7["latest_transition"].update({
        "step_ref": "trace:checkpoint-v7", "to_node": "factor_semantics",
        "evidence_refs": [], "trial_plan_refs": [],
        "obligation_refs": [], "claim_refs": [],
        "job_refs": [], "run_refs": [], "delta_refs": [],
    })
    current_v8 = deepcopy(root_v7)
    current_v8.update({
        "branch_ref": "graph-branch:physical-v8:branch-v8",
        "graph_ref": "factor-research@v8",
        "checkpoint_ref": "trace:checkpoint-v8",
    })
    current_v8["latest_transition"].update({
        "step_ref": "trace:checkpoint-v8",
        "edge_ref": "graph-edge:__graph_continuation__",
        "created_at": 3.0,
    })
    current_v8["report_lineage"] = {
        "status": "linked",
        "predecessor_checkpoint_ref": "trace:checkpoint-v7",
        "source_branch_ref": "graph-branch:physical-v7:branch-v7",
    }

    with pytest.raises(ValueError, match="predecessor is missing"):
        stage_historical_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            current_branch_id="branch-v8",
            carrier=current_v8,
            narrative=_historical_narrative(occurred_at=2.5),
        )
    stage_historical_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        current_branch_id="branch-v8",
        carrier=root_v7,
        narrative=_historical_narrative(occurred_at=1.5),
    )
    finalize_historical_research_backfill(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=current_v8,
        narrative=_historical_narrative(occurred_at=2.5),
    )

    journal = json.loads((
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-v8" / "LOGICAL_JOURNAL.json"
    ).read_text())
    assert [item["branch_ref"] for item in journal["checkpoints"]] == [
        "graph-branch:physical-v7:branch-v7",
        "graph-branch:physical-v8:branch-v8",
    ]
    record = store.load("maxa")["research_records"][0]
    assert record["checkpoint_ref"] == "trace:checkpoint-v8"
    assert record["updated_at"] == 3.0


def test_checkpoint_publish_materializes_report_and_profile_reference(
    tmp_path: Path,
) -> None:
    store = _profile(tmp_path / "client-support")

    result = publish_research_checkpoint(
        client_root=tmp_path / "client-support",
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=_carrier(),
    )

    assert result["changed"] is True
    assert result["report_changed"] is True
    assert result["profile_changed"] is True
    report = (
        tmp_path / "client-support" / "profile-root" / "research"
        / "sgccs-review" / "branches" / "branch-sgccs" / "REPORT.md"
    )
    assert report.is_file()
    report_text = report.read_text(encoding="utf-8")
    assert "evidence:job-attempt-1" not in report_text
    assert "中国期货" in report_text
    assert "计算证据就绪" in report_text
    assert "`已定义`" in report_text
    assert "2" * 64 not in report_text
    journal = json.loads(report.with_name("JOURNAL.json").read_text())
    journal_targets = {
        link["target_ref"]
        for checkpoint in journal["checkpoints"]
        for section in checkpoint["sections"]
        for link in section["links"]
    }
    assert "evidence:job-attempt-1" in journal_targets
    record = store.load("maxa")["research_records"][0]
    assert record["record_id"] == "sgccs-review"
    assert record["agent_id"] == "research-maxa"
    assert record["checkpoint_ref"] == "trace:checkpoint-1"
    assert record["artifacts"][0]["artifact_ref"] == (
        "artifact:research/sgccs-review/branches/branch-sgccs/REPORT.md"
    )
    assert record["artifacts"][0]["content_hash"] == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()
    assert record["artifacts"][0]["journal_ref"].endswith(
        "/LOGICAL_JOURNAL.json"
    )
    assert len(record["artifacts"][0]["journal_hash"]) == 64
    assert len(result["carrier_hash"]) == 64
    assert len(result["narrative_hash"]) == 64
    assert len(result["section_hash"]) == 64
    assert "本次检验显示信号" in report.read_text(encoding="utf-8")


def test_checkpoint_publish_keeps_stable_work_package_across_incarnations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["agents"][0]["scope"] = {
        "instance_id": "physical-v7",
        "branch_id": "branch-v7",
    }
    profile["research_records"][0]["graph_branch_ref"] = (
        "graph-branch:physical-v7:branch-v7"
    )
    store.save(profile)
    carrier = _carrier()
    carrier["branch_ref"] = "graph-branch:physical-v7:branch-v7"

    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
    )

    profile = store.load("maxa")
    assert len(profile["research_records"]) == 1
    assert profile["research_records"][0]["record_id"] == "sgccs-review"
    assert profile["research_records"][0]["graph_instance_ref"] == (
        "work-package:sgccs-review"
    )
    assert (
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-v7" / "JOURNAL.json"
    ).is_file()


def test_idempotent_publish_repairs_missing_report_index_sections(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
    )
    index_path = (
        root / "profile-root" / "research" / "sgccs-review"
        / "INDEX.json"
    )
    index = json.loads(index_path.read_text())
    assert index["sections"]
    index["sections"] = []
    index_path.write_text(json.dumps(index))

    result = publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
    )

    repaired = json.loads(index_path.read_text())
    assert result["report_changed"] is True
    assert repaired["sections"]
    assert repaired["sections"][0]["links"]


def test_checkpoint_publish_accumulates_complete_chinese_narrative(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    first = _carrier()
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=first,
        narrative=_narrative(first, body="第一阶段确认了因子定义与时间对齐。"),
    )
    second = deepcopy(first)
    second["checkpoint_ref"] = "trace:checkpoint-2"
    second["latest_transition"].update({
        "step_ref": "trace:checkpoint-2",
        "created_at": 3.0,
    })
    _link_after(second, first["checkpoint_ref"])
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=second,
        narrative=_narrative(second, body="第二阶段显示交易成本仍是主要不确定性。"),
    )

    branch_root = (
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-sgccs"
    )
    report = (branch_root / "REPORT.md").read_text(encoding="utf-8")
    journal = json.loads((branch_root / "JOURNAL.json").read_text())
    assert report.index("第一阶段") < report.index("第二阶段")
    assert journal["language"] == "zh-Hans"
    assert [item["checkpoint_ref"] for item in journal["checkpoints"]] == [
        "trace:checkpoint-1",
        "trace:checkpoint-2",
    ]
    assert len(list((branch_root / "sections").glob("*.json"))) == 2


def test_checkpoint_publish_keeps_fork_fragments_in_physical_branches(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["agents"].append({
        "agent_id": "research-maxa-fork",
        "role": "research",
        "scope": {
            "instance_id": "sgccs-review",
            "branch_id": "branch-fork",
        },
        "status": "ready",
        "next_action": "Resume the authorized research scope.",
    })
    source_record = profile["research_records"][0]
    target_record = deepcopy(source_record)
    target_record.update({
        "record_id": "sgccs-review-fork",
        "agent_id": "research-maxa-fork",
        "graph_branch_ref": "graph-branch:sgccs-review:branch-fork",
    })
    profile["research_records"].append(target_record)
    store.save(profile)

    source = _carrier()
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=source,
        narrative=_narrative(source, body="源分支首先确认了因子语义与时间对齐。"),
    )
    fork = deepcopy(source)
    fork.update({
        "branch_ref": "graph-branch:sgccs-review:branch-fork",
        "checkpoint_ref": "trace:checkpoint-fork-1",
    })
    fork["latest_transition"].update({
        "step_ref": "trace:checkpoint-fork-1",
        "created_at": 3.0,
        "edge_ref": "graph-edge:fork__cost_review",
    })
    fork["report_lineage"] = {
        "status": "linked",
        "predecessor_checkpoint_ref": "trace:checkpoint-1",
        "source_branch_ref": "graph-branch:sgccs-review:branch-sgccs",
    }
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa-fork",
        carrier=fork,
        narrative=_narrative(fork, body="分支随后检验了交易成本义务是否仍然成立。"),
    )

    branch_root = (
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-fork"
    )
    journal = json.loads((branch_root / "JOURNAL.json").read_text())
    assert [item["checkpoint_ref"] for item in journal["checkpoints"]] == [
        "trace:checkpoint-fork-1",
    ]
    assert journal["journal_kind"] == "physical_branch"
    assert journal["checkpoints"][0]["lineage_relation"] == "branch_fork"
    assert journal["checkpoints"][0]["source_branch_ref"] == (
        "graph-branch:sgccs-review:branch-sgccs"
    )
    logical = json.loads((branch_root / "LOGICAL_JOURNAL.json").read_text())
    assert logical["journal_kind"] == "work_package"
    assert [item["checkpoint_ref"] for item in logical["checkpoints"]] == [
        "trace:checkpoint-1", "trace:checkpoint-fork-1",
    ]
    report = (branch_root / "REPORT.md").read_text(encoding="utf-8")
    assert report.index("源分支首先") < report.index("分支随后")
    assert len(list((branch_root / "sections").glob("*.json"))) == 1
    assert len(list((
        branch_root.parent / "branch-sgccs" / "sections"
    ).glob("*.json"))) == 1


def test_graph_continuation_replaces_physical_branch_in_work_package_index(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    source = _carrier()
    source["graph_ref"] = "factor-research@v7"
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=source,
        narrative=_narrative(source, body="旧图版本已完成可信研究检查点。"),
    )

    profile = store.load("maxa")
    profile["agents"][0]["scope"] = {
        "instance_id": "sgccs-v8",
        "branch_id": "branch-v8",
    }
    profile["research_records"][0]["graph_branch_ref"] = (
        "graph-branch:sgccs-v8:branch-v8"
    )
    store.save(profile)
    continued = deepcopy(source)
    continued.update({
        "branch_ref": "graph-branch:sgccs-v8:branch-v8",
        "graph_ref": "factor-research@v8",
        "checkpoint_ref": "trace:checkpoint-v8",
    })
    continued["latest_transition"].update({
        "step_ref": "trace:checkpoint-v8",
        "edge_ref": "graph-edge:__graph_continuation__",
        "created_at": 3.0,
    })
    continued["report_lineage"] = {
        "status": "linked",
        "predecessor_checkpoint_ref": "trace:checkpoint-1",
        "source_branch_ref": "graph-branch:sgccs-review:branch-sgccs",
    }
    continuation_narrative = _narrative(
        continued, body="同一研究在图 v8 中连续开展。",
    )
    continuation_narrative["title"] = "研究图切换：factor-research@v8"
    continuation_narrative["sections"][0]["title"] = (
        "研究图切换与当前节点重新进入"
    )
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=continued,
        narrative=continuation_narrative,
    )

    package_root = root / "profile-root" / "research" / "sgccs-review"
    index = json.loads((package_root / "INDEX.json").read_text())
    assert index["schema_version"] == 2
    assert [item["branch_id"] for item in index["branches"]] == ["branch-v8"]
    assert [item["checkpoint_ref"] for item in index["sections"]] == [
        "trace:checkpoint-1", "trace:checkpoint-v8",
    ]
    assert [item["branch_ref"] for item in index["sections"]] == [
        "graph-branch:sgccs-review:branch-sgccs",
        "graph-branch:sgccs-v8:branch-v8",
    ]
    assert len({item["section_ref"] for item in index["sections"]}) == 2
    aggregate = (package_root / "REPORT.md").read_text(encoding="utf-8")
    assert "研究分支：1" in aggregate
    continued_report = (
        package_root / "branches" / "branch-v8" / "REPORT.md"
    ).read_text(encoding="utf-8")
    assert continued_report.startswith("# SgCCS review\n")
    assert "# 研究图切换：factor-research@v8" not in continued_report
    assert "## 研究图切换与当前节点重新进入" in continued_report
    assert "旧图版本已完成可信研究检查点" in continued_report
    assert store.load("maxa")["research_records"][0]["title"] == "SgCCS review"
    source_journal = json.loads((
        package_root / "branches" / "branch-sgccs" / "JOURNAL.json"
    ).read_text())
    continued_journal = json.loads((
        package_root / "branches" / "branch-v8" / "JOURNAL.json"
    ).read_text())
    logical_journal = json.loads((
        package_root / "branches" / "branch-v8" / "LOGICAL_JOURNAL.json"
    ).read_text())
    assert [item["checkpoint_ref"] for item in source_journal["checkpoints"]] == [
        "trace:checkpoint-1",
    ]
    assert [item["checkpoint_ref"] for item in continued_journal["checkpoints"]] == [
        "trace:checkpoint-v8",
    ]
    assert logical_journal["branch_refs"] == [
        "graph-branch:sgccs-review:branch-sgccs",
        "graph-branch:sgccs-v8:branch-v8",
    ]
    assert logical_journal["checkpoints"][0]["graph_ref"] == (
        "factor-research@v7"
    )
    assert logical_journal["checkpoints"][1]["graph_ref"] == (
        "factor-research@v8"
    )
    assert logical_journal["checkpoints"][1]["lineage_relation"] == (
        "graph_continuation"
    )
    assert logical_journal["checkpoints"][1]["source_branch_ref"] == (
        "graph-branch:sgccs-review:branch-sgccs"
    )


def test_idempotent_continuation_repairs_missing_historical_index_sections(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    source = _carrier()
    source["graph_ref"] = "factor-research@v7"
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=source,
        narrative=_narrative(source, body="旧图版本已完成可信研究检查点。"),
    )

    profile = store.load("maxa")
    profile["agents"][0]["scope"] = {
        "instance_id": "sgccs-v8",
        "branch_id": "branch-v8",
    }
    profile["research_records"][0]["graph_branch_ref"] = (
        "graph-branch:sgccs-v8:branch-v8"
    )
    store.save(profile)
    continued = deepcopy(source)
    continued.update({
        "branch_ref": "graph-branch:sgccs-v8:branch-v8",
        "graph_ref": "factor-research@v8",
        "checkpoint_ref": "trace:checkpoint-v8",
    })
    continued["latest_transition"].update({
        "step_ref": "trace:checkpoint-v8",
        "edge_ref": "graph-edge:__graph_continuation__",
        "created_at": 3.0,
    })
    continued["report_lineage"] = {
        "status": "linked",
        "predecessor_checkpoint_ref": "trace:checkpoint-1",
        "source_branch_ref": "graph-branch:sgccs-review:branch-sgccs",
    }
    narrative = _narrative(
        continued, body="同一研究在图 v8 中连续开展。",
    )
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=continued,
        narrative=narrative,
    )

    index_path = (
        root / "profile-root" / "research" / "sgccs-review" / "INDEX.json"
    )
    broken = json.loads(index_path.read_text())
    broken["sections"] = [
        item for item in broken["sections"]
        if item["checkpoint_ref"] != "trace:checkpoint-1"
    ]
    index_path.write_text(
        json.dumps(broken, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    repaired = publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=continued,
        narrative=narrative,
    )

    index = json.loads(index_path.read_text())
    assert [item["checkpoint_ref"] for item in index["sections"]] == [
        "trace:checkpoint-1", "trace:checkpoint-v8",
    ]
    assert repaired["report_changed"] is True


def test_checkpoint_publish_rejects_fork_without_source_journal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["agents"][0]["scope"]["branch_id"] = "branch-fork"
    profile["research_records"][0]["graph_branch_ref"] = (
        "graph-branch:sgccs-review:branch-fork"
    )
    store.save(profile)
    carrier = _carrier()
    carrier["branch_ref"] = "graph-branch:sgccs-review:branch-fork"
    carrier["report_lineage"] = {
        "status": "linked",
        "predecessor_checkpoint_ref": "trace:checkpoint-1",
        "source_branch_ref": "graph-branch:sgccs-review:branch-sgccs",
    }
    with pytest.raises(ValueError, match="lineage contains a cycle"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
        )


def test_checkpoint_publish_requires_trusted_root_and_unbroken_lineage(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    incomplete = _carrier()
    incomplete["report_lineage"] = {
        "status": "history_incomplete",
        "predecessor_checkpoint_ref": "",
    }
    with pytest.raises(ValueError, match="restart from a trusted root"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=incomplete,
        )
    assert not (root / "profile-root" / "research").exists()

    first = _carrier()
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=first,
    )
    skipped = deepcopy(first)
    skipped["checkpoint_ref"] = "trace:checkpoint-3"
    skipped["latest_transition"].update({
        "step_ref": "trace:checkpoint-3",
        "created_at": 4.0,
    })
    _link_after(skipped, "trace:checkpoint-2")
    with pytest.raises(ValueError, match="lineage is incomplete"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=skipped,
        )

    journal = json.loads((
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-sgccs" / "JOURNAL.json"
    ).read_text())
    assert journal["schema_version"] == 4
    assert journal["history_status"] == "segment"
    assert journal["root_checkpoint_ref"] == "trace:checkpoint-1"


def test_checkpoint_publish_preserves_structured_list_and_result_table(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    narrative = {
        "schema_version": 2,
        "language": "zh-Hans",
        "title": "因子研究报告",
        "sections": [{
            "section_id": "research-progress",
            "title": "研究进展",
            "body": "本阶段先说明研究判断，再列出支撑判断的结构化结果。",
            "blocks": [{
                "kind": "math",
                "latex": r"S=(2P-H-L)/(H-L+\\epsilon)",
                "fallback": "中心价格相对窗口高低点的位置强度。",
                "link_ids": ["cost-obligation"],
            }, {
                "kind": "paragraph",
                "text": "本段结论由试验计划约束。",
                "link_ids": ["checkpoint-plan"],
            }, {
                "kind": "list",
                "rows": [{
                    "text": "交易成本义务仍未清除。",
                    "link_ids": [
                        "cost-obligation", "checkpoint-job", "checkpoint-run",
                        "checkpoint-claim",
                    ],
                }],
            }, {
                "kind": "table",
                "result_kind": "backtest",
                "columns": ["检验", "指标", "结果"],
                "rows": [{
                    "cells": ["成本后回测", "夏普比率", "0.42"],
                    "link_ids": [
                        "checkpoint-evidence", "checkpoint-job",
                        "checkpoint-run",
                    ],
                }],
            }],
            "links": [{
                "link_id": "cost-obligation",
                "kind": "obligation",
                "target_ref": "obligation:cost-survival",
                "label": "交易成本后仍能存活吗？",
            }, {
                "link_id": "checkpoint-job",
                "kind": "job",
                "target_ref": "job:job-1",
            }, {
                "link_id": "checkpoint-run",
                "kind": "run",
                "target_ref": "run:run-1",
            }, {
                "link_id": "checkpoint-plan",
                "kind": "trial_plan",
                "target_ref": "trial-plan:sha256:" + "3" * 64,
            }, {
                "link_id": "checkpoint-claim",
                "kind": "claim",
                "target_ref": "claim:predictive-relation",
            }, {
                "link_id": "checkpoint-evidence",
                "kind": "evidence",
                "target_ref": "evidence:job-attempt-1",
            }],
        }],
    }

    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
        narrative=narrative,
    )

    journal_path = (
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-sgccs" / "JOURNAL.json"
    )
    journal = json.loads(journal_path.read_text())
    section = journal["checkpoints"][0]["sections"][0]
    assert journal["schema_version"] == 4
    assert [block["kind"] for block in section["blocks"]] == [
        "math", "paragraph", "list", "table",
    ]
    assert section["blocks"][0]["fallback"] == "中心价格相对窗口高低点的位置强度。"
    assert section["blocks"][1]["link_ids"] == ["checkpoint-plan"]
    assert section["blocks"][3]["rows"][0]["cells"][2] == "0.42"
    assert section["blocks"][3]["result_kind"] == "backtest"
    assert section["links"][0]["label"] == "交易成本后仍能存活吗？"
    report = journal_path.with_name("REPORT.md").read_text(encoding="utf-8")
    assert "本阶段先说明研究判断，再列出支撑判断的结构化结果。" in report
    assert "$$\nS=(2P-H-L)/(H-L+\\\\epsilon)\n$$" in report
    assert "- 交易成本义务仍未清除。" in report
    assert "| 检验 | 指标 | 结果 |" in report
    assert "| 成本后回测 | 夏普比率 | 0.42 |" in report


def test_narrative_v3_binds_graph_report_item_and_occurrence_time(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    carrier.update({
        "evidence_refs": [], "job_refs": [], "run_refs": [],
        "claims": [], "open_obligations": [],
    })
    carrier["latest_transition"].update({
        "evidence_refs": [], "trial_plan_refs": [], "obligation_refs": [],
        "claim_refs": [], "job_refs": [], "run_refs": [], "delta_refs": [],
    })
    content = {"kind": "paragraph", "text": "本阶段完成了因子语义逐项审查。"}
    report_id = "report.node.factor_semantics.action"
    subject_ref = "node:factor_semantics"
    item_hash = report_item_hash(
        report_requirement_id=report_id,
        subject_ref=subject_ref,
        content_kind="sentence",
        content=content,
    )
    items = [{
        "report_requirement_id": report_id,
        "subject_ref": subject_ref,
        "content_kind": "sentence",
        "item_hash": item_hash,
    }]
    carrier["latest_transition"].update({
        "report_fragment_ref": (
            f"report-fragment:sha256:{report_fragment_hash(items)}"
        ),
        "report_items": [{
            "report_item_ref": f"report-item:sha256:{item_hash}",
            "report_requirement_id": report_id,
            "subject_ref": subject_ref,
            "content_kind": "sentence",
        }],
    })
    narrative = {
        "schema_version": 3,
        "language": "zh-Hans",
        "title": "因子研究报告",
        "research_occurred_at": 1.5,
        "time_basis": "historical_backfill",
        "time_source_refs": ["conversation:maxa-factor-semantics"],
        "sections": [{
            "section_id": "factor-semantics",
            "title": "因子语义",
            "blocks": [{
                **content,
                "report_binding": {
                    "report_requirement_id": report_id,
                    "subject_ref": subject_ref,
                },
                "report_timing": {
                    "occurred_at": 1.75,
                    "time_basis": "historical_backfill",
                    "time_source_refs": [
                        "conversation:maxa-report",
                        "conversation:maxa-report",
                        "conversation:maxa-factor-semantics",
                    ],
                },
            }],
            "links": [],
        }],
    }

    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
        narrative=narrative,
    )

    journal = json.loads((
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-sgccs" / "JOURNAL.json"
    ).read_text())
    section = journal["checkpoints"][0]["sections"][0]
    assert section["research_occurred_at"] == 1.5
    assert section["time_basis"] == "historical_backfill"
    assert section["blocks"][0]["report_binding"] == {
        "report_requirement_id": report_id,
        "subject_ref": subject_ref,
        "report_item_ref": f"report-item:sha256:{item_hash}",
    }
    assert section["blocks"][0]["report_timing"] == {
        "occurred_at": 1.75,
        "time_basis": "historical_backfill",
        "time_source_refs": [
            "conversation:maxa-factor-semantics",
            "conversation:maxa-report",
        ],
    }

    invalid_transition = deepcopy(narrative)
    invalid_transition.update({
        "research_occurred_at": 1.5,
        "time_basis": "transition",
        "time_source_refs": [],
    })
    with pytest.raises(ValueError, match="must equal the trusted trace"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=invalid_transition,
        )

    invalid_bool = deepcopy(narrative)
    invalid_bool["research_occurred_at"] = True
    with pytest.raises(ValueError, match="research occurred_at"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=invalid_bool,
        )


def test_narrative_v3_rejects_historical_time_without_source(
    tmp_path: Path,
) -> None:
    carrier = _carrier()
    carrier["latest_transition"]["report_fragment_ref"] = (
        "report-fragment:sha256:" + "a" * 64
    )
    carrier["latest_transition"]["report_items"] = [{
        "report_item_ref": "report-item:sha256:" + "b" * 64,
        "report_requirement_id": "report.node.result_audit.action",
        "subject_ref": "node:result_audit",
        "content_kind": "sentence",
    }]
    narrative = {
        "schema_version": 3,
        "language": "zh-Hans",
        "title": "因子研究报告",
        "research_occurred_at": 1.0,
        "time_basis": "historical_backfill",
        "time_source_refs": [],
        "sections": [{
            "section_id": "audit",
            "title": "结果审计",
            "blocks": [{
                "kind": "paragraph",
                "text": "本阶段完成结果审计。",
                "report_binding": {
                    "report_requirement_id": "report.node.result_audit.action",
                    "subject_ref": "node:result_audit",
                },
            }],
            "links": [],
        }],
    }

    with pytest.raises(ValueError, match="requires time_source_refs"):
        publish_research_checkpoint(
            client_root=tmp_path,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=narrative,
        )


def test_structured_narrative_rejects_unbound_row_chip(tmp_path: Path) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    narrative = {
        "schema_version": 2,
        "language": "zh-Hans",
        "title": "因子研究报告",
        "sections": [{
            "section_id": "research-progress",
            "title": "研究进展",
            "blocks": [{
                "kind": "list",
                "rows": [{
                    "text": "交易成本义务仍未清除。",
                    "link_ids": ["missing-link"],
                }],
            }],
            "links": [],
        }],
    }

    with pytest.raises(ValueError, match="declared section link"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=narrative,
        )


def test_result_checkpoint_requires_job_and_run_in_result_table(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    narrative = _narrative(carrier)
    section = narrative["sections"][0]
    links = section["links"]
    evidence_link = next(
        link["link_id"]
        for link in links
        if link["target_ref"] == "evidence:job-attempt-1"
    )
    section["blocks"] = [{
        "kind": "list",
        "rows": [{
            "text": "已记录本次检验对象。",
            "link_ids": [link["link_id"] for link in links],
        }],
    }, {
        "kind": "table",
        "result_kind": "backtest",
        "columns": ["检验", "结果"],
        "rows": [{
            "cells": ["成本后回测", "见证据引用"],
            "link_ids": [evidence_link],
        }],
    }]
    narrative["schema_version"] = 2

    with pytest.raises(ValueError, match="result table must bind"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=narrative,
        )


def test_checkpoint_publish_requires_each_research_object_chip(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    narrative = _narrative(carrier)
    narrative["sections"][0]["links"] = [
        link for link in narrative["sections"][0]["links"]
        if link["target_ref"] != "job:job-1"
    ]

    with pytest.raises(ValueError, match="every checkpoint object"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=narrative,
        )


def test_checkpoint_publish_rejects_unbound_narrative_link_before_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    narrative = _narrative(carrier)
    narrative["sections"][0]["links"][0]["target_ref"] = "job:other-job"

    with pytest.raises(ValueError, match="same checkpoint carrier"):
        _publish_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=narrative,
        )

    assert not (root / "profile-root" / "research").exists()


def test_checkpoint_publish_requires_chinese_narrative(tmp_path: Path) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    narrative = _narrative(carrier, body="English terms only")
    narrative["sections"][0]["title"] = "Research progress"

    with pytest.raises(ValueError, match="Chinese"):
        _publish_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=narrative,
        )


def test_checkpoint_fragment_conflict_and_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    first = _publish_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
        narrative=_narrative(carrier, body="原始中文研究结论。"),
    )
    with pytest.raises(ValueError, match="conflicting narrative"):
        _publish_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=_narrative(carrier, body="冲突的中文研究结论。"),
        )

    fragment = (
        root / "profile-root" / "research" / "sgccs-review" / "branches"
        / "branch-sgccs" / "sections" / f"{first['section_hash']}.json"
    )
    fragment.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="fragment"):
        _publish_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
            narrative=_narrative(carrier, body="原始中文研究结论。"),
        )


def test_checkpoint_publish_is_byte_and_profile_write_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    first = publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=_carrier(),
    )
    paths = [
        root / "profiles" / "maxa.json",
        root / "profile-root" / "research" / "sgccs-review" / "REPORT.md",
        root / "profile-root" / "research" / "sgccs-review" / "INDEX.json",
        root / "profile-root" / "research" / "sgccs-review" / "branches"
        / "branch-sgccs" / "REPORT.md",
    ]
    before = [(path.stat().st_ino, path.stat().st_mtime_ns) for path in paths]

    second = publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=_carrier(),
    )

    assert first["changed"] is True
    assert second["changed"] is False
    assert second["report_changed"] is False
    assert second["profile_changed"] is False
    assert [(path.stat().st_ino, path.stat().st_mtime_ns) for path in paths] == before


def test_distinct_trace_checkpoints_remain_linked_in_chronological_index(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=_carrier(),
    )
    later = deepcopy(_carrier())
    later["checkpoint_ref"] = "trace:checkpoint-2"
    later["evidence_refs"] = ["evidence:job-attempt-2"]
    later["latest_transition"].update({
        "step_ref": "trace:checkpoint-2",
        "created_at": 3.0,
        "evidence_refs": ["evidence:job-attempt-2"],
    })
    _link_after(later, "trace:checkpoint-1")

    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=later,
    )

    index = json.loads((
        root / "profile-root" / "research" / "sgccs-review" / "INDEX.json"
    ).read_text(encoding="utf-8"))
    assert len(index["sections"]) == 2
    assert {
        link["target_ref"]
        for section in index["sections"]
        for link in section["links"]
    }.issuperset({"trace:checkpoint-1", "trace:checkpoint-2"})
    timeline_targets = {
        item["target_ref"]
        for item in store.load("maxa")["research_records"][0][
            "timeline_refs"
        ]
    }
    assert timeline_targets.issuperset({
        "trace:checkpoint-1",
        "trace:checkpoint-2",
    })


def test_checkpoint_publish_locates_distinct_records_for_work_package_branches(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["agents"].append({
        "agent_id": "research-maxa-trend",
        "role": "research",
        "scope": {
            "instance_id": "sgccs-review",
            "branch_id": "branch-trend",
        },
        "status": "ready",
        "next_action": "Resume the authorized research scope.",
    })
    second_record = deepcopy(profile["research_records"][0])
    second_record.update({
        "record_id": "trend-local-record",
        "agent_id": "research-maxa-trend",
        "graph_branch_ref": "graph-branch:sgccs-review:branch-trend",
    })
    profile["research_records"].append(second_record)
    store.save(profile)
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=_carrier(),
    )
    carrier = deepcopy(_carrier())
    carrier["branch_ref"] = "graph-branch:sgccs-review:branch-trend"
    carrier["checkpoint_ref"] = "trace:checkpoint-trend-1"
    carrier["latest_transition"]["step_ref"] = "trace:checkpoint-trend-1"

    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa-trend",
        carrier=carrier,
    )

    saved = store.load("maxa")
    assert {item["record_id"] for item in saved["research_records"]} == {
        "sgccs-review",
        "trend-local-record",
    }
    index = json.loads((
        root / "profile-root" / "research" / "sgccs-review" / "INDEX.json"
    ).read_text(encoding="utf-8"))
    assert [item["branch_id"] for item in index["branches"]] == [
        "branch-sgccs",
        "branch-trend",
    ]
    first_record = next(
        item for item in saved["research_records"]
        if item["record_id"] == "sgccs-review"
    )
    first_report = (
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-sgccs" / "REPORT.md"
    )
    assert first_record["artifacts"][0]["content_hash"] == hashlib.sha256(
        first_report.read_bytes()
    ).hexdigest()


def test_replaying_pruned_branch_checkpoint_is_strictly_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["agents"].append({
        "agent_id": "research-maxa-trend",
        "role": "research",
        "scope": {
            "instance_id": "sgccs-review",
            "branch_id": "branch-trend",
        },
        "status": "ready",
        "next_action": "Resume the authorized research scope.",
    })
    second_record = deepcopy(profile["research_records"][0])
    second_record.update({
        "record_id": "trend-local-record",
        "agent_id": "research-maxa-trend",
        "graph_branch_ref": "graph-branch:sgccs-review:branch-trend",
    })
    profile["research_records"].append(second_record)
    store.save(profile)
    original = _carrier()
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=original,
    )
    trend = deepcopy(_carrier())
    trend["branch_ref"] = "graph-branch:sgccs-review:branch-trend"
    previous_trend_ref = ""
    for index in range(101):
        checkpoint_ref = f"trace:trend-{index:03d}"
        trend["checkpoint_ref"] = checkpoint_ref
        trend["latest_transition"].update({
            "step_ref": checkpoint_ref,
            "created_at": 3.0 + index,
        })
        if previous_trend_ref:
            _link_after(trend, previous_trend_ref)
        else:
            trend["report_lineage"] = {
                "status": "root",
                "predecessor_checkpoint_ref": "",
            }
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa-trend",
            carrier=trend,
        )
        previous_trend_ref = checkpoint_ref
    index_path = (
        root / "profile-root" / "research" / "sgccs-review" / "INDEX.json"
    )
    before = index_path.read_bytes()
    omitted_before = json.loads(before)["omitted_section_count"]

    replay = publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=original,
    )

    assert replay["changed"] is False
    assert index_path.read_bytes() == before
    assert json.loads(index_path.read_bytes())["omitted_section_count"] == (
        omitted_before
    )


def test_older_checkpoint_cannot_replace_newer_local_report(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    newer = deepcopy(_carrier())
    newer["checkpoint_ref"] = "trace:checkpoint-2"
    newer["latest_transition"].update({
        "step_ref": "trace:checkpoint-2",
        "created_at": 3.0,
    })
    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=newer,
    )
    profile_path = root / "profiles" / "maxa.json"
    report_path = (
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-sgccs" / "REPORT.md"
    )
    before = (profile_path.read_bytes(), report_path.read_bytes())

    with pytest.raises(ValueError, match="older"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=_carrier(),
        )

    assert (profile_path.read_bytes(), report_path.read_bytes()) == before
    assert store.load("maxa")["research_records"][0]["checkpoint_ref"] == (
        "trace:checkpoint-2"
    )


@pytest.mark.parametrize("missing", ["record", "scope", "versions"])
def test_checkpoint_publish_fails_closed_without_local_research_identity(
    tmp_path: Path,
    missing: str,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    if missing == "record":
        profile["research_records"] = []
    elif missing == "scope":
        profile["research_records"][0]["scope"] = {}
    else:
        profile["research_records"][0]["factor_family_versions"] = []
    store.save(profile)
    profile_path = root / "profiles" / "maxa.json"
    before = profile_path.read_bytes()

    with pytest.raises(ValueError):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=_carrier(),
        )

    assert profile_path.read_bytes() == before
    assert not (root / "profile-root" / "research").exists()


def test_checkpoint_publish_rejects_prohibited_or_oversized_carrier_before_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    prohibited = deepcopy(_carrier())
    prohibited["closure"] = {"source_code": "factor implementation"}
    oversized = deepcopy(_carrier())
    oversized["closure"] = {"note": "x" * (64 * 1024)}

    for carrier in (prohibited, oversized):
        with pytest.raises(ValueError):
            publish_research_checkpoint(
                client_root=root,
                profile_id="maxa",
                agent_id="research-maxa",
                carrier=carrier,
            )

    assert not (root / "profile-root" / "research").exists()


@pytest.mark.parametrize(
    "unsafe",
    [
        "file:///private/evidence.json",
        "https://user:secret@example.com/evidence",
        "https://example.com/evidence?token=secret",
        "artifact:/Users/max/private.json",
        "artifact:C:/Users/max/private.json",
        "artifact://Users/max/private.json",
        r"artifact:private\\evidence",
    ],
)
def test_checkpoint_publish_rejects_credential_or_path_bearing_reference(
    tmp_path: Path,
    unsafe: str,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    carrier["evidence_refs"] = [unsafe]

    with pytest.raises(ValueError, match="stable reference"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
        )

    assert not (root / "profile-root" / "research").exists()


def test_checkpoint_publish_requires_exact_source_free_closure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    for closure in (
        {"password": "secret"},
        {"proposal_ref": "proposal:1", "disposition": "closed", "note": "x"},
    ):
        carrier = _carrier()
        carrier["closure"] = closure
        with pytest.raises(ValueError):
            publish_research_checkpoint(
                client_root=root,
                profile_id="maxa",
                agent_id="research-maxa",
                carrier=carrier,
            )

    assert not (root / "profile-root" / "research").exists()


def test_checkpoint_publish_records_omitted_evidence_and_allows_no_trial_plan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    carrier["omitted_evidence_count"] = 7
    carrier["trial_plan_hash"] = ""
    carrier["latest_transition"]["trial_plan_refs"] = []

    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
    )

    report = (
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-sgccs" / "REPORT.md"
    ).read_text(encoding="utf-8")
    assert "有 7 条证据引用未随本次载荷提供" in report


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_checkpoint_publish_rejects_invalid_omitted_evidence_count(
    tmp_path: Path,
    count,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    carrier["omitted_evidence_count"] = count

    with pytest.raises(ValueError, match="omitted_evidence_count"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
        )

    assert not (root / "profile-root" / "research").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("decision_contract_hash", ""),
        ("methodology_hash", ""),
        ("research_cycle_ref", "research-cycle:sha256:"),
    ],
)
def test_checkpoint_publish_requires_complete_research_foundations(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    carrier[field] = value

    with pytest.raises(ValueError, match=field):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
        )

    assert not (root / "profile-root" / "research").exists()


def test_checkpoint_publish_enforces_sixteen_item_arrays(tmp_path: Path) -> None:
    root = tmp_path / "client-support"
    _profile(root)
    carrier = _carrier()
    carrier["evidence_refs"] = [f"evidence:{index}" for index in range(17)]

    with pytest.raises(ValueError, match="bounded reference array"):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=carrier,
        )

    assert not (root / "profile-root" / "research").exists()


def test_server_checkpoint_carrier_publishes_without_translation(
    tmp_path: Path,
) -> None:
    from server.services.research_graph.report_checkpoint import (
        report_checkpoint_projection,
    )

    root = tmp_path / "client-support"
    _profile(root)
    carrier = report_checkpoint_projection(
        instance_id="sgccs-review",
        work_package_id="sgccs-review",
        branch_id="branch-sgccs",
        workspace_id="workspace-maxa",
        graph_id="factor-research",
        graph_version=6,
        title="SgCCS checkpoint",
        product_group="CNFutures",
        current_node="job_evidence_ready",
        status="running",
        trace_id="checkpoint-1",
        edge_id="backtest__job_evidence_ready",
        from_node="authoritative_backtest",
        created_at=2.0,
        checkpoint={
            "projection_hash": "4" * 64,
            "contract_hash": "2" * 64,
            "methodology_hash": "1" * 64,
            "claims": [],
            "obligations": [],
        },
        trace_evidence={
            "report_lineage": {
                "status": "root",
                "predecessor_checkpoint_ref": "",
            },
        },
        evidence_refs=[
            "evidence:valid",
            "https://user:secret@example.com/evidence",
            "artifact:/Users/max/private.json",
            "artifact:C:/Users/max/private.json",
            "artifact://Users/max/private.json",
        ],
        omitted_evidence_count=3,
    )

    result = publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=carrier,
    )

    assert result["changed"] is True
    assert carrier["evidence_refs"] == ["evidence:valid"]
    assert carrier["omitted_evidence_count"] == 7
    report = (
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-sgccs" / "REPORT.md"
    ).read_text(encoding="utf-8")
    assert "secret" not in report
    assert "有 7 条证据引用未随本次载荷提供" in report


def test_checkpoint_publish_projects_only_bounded_scope_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["research_records"][0]["scope"] = {
        "factor_families": ["private-scope-marker"],
    }
    store.save(profile)

    publish_research_checkpoint(
        client_root=root,
        profile_id="maxa",
        agent_id="research-maxa",
        carrier=_carrier(),
    )

    report = (
        root / "profile-root" / "research" / "sgccs-review"
        / "branches" / "branch-sgccs" / "REPORT.md"
    ).read_text(encoding="utf-8")
    index = json.loads((
        root / "profile-root" / "research" / "sgccs-review" / "INDEX.json"
    ).read_text())
    assert "scope:sha256:" not in report
    assert any(
        ref.startswith("scope:sha256:")
        for ref in index["branches"][0]["evidence_refs"]
    )
    assert "private-scope-marker" not in report


@pytest.mark.parametrize(
    "scope",
    [
        {"source_code": "secret implementation"},
        {"factor_families": ["/Users/maxdeux/private.py"]},
        {"factor_families": ["x" * 257]},
    ],
)
def test_checkpoint_publish_rejects_unsafe_scope_before_report_write(
    tmp_path: Path,
    scope: dict,
) -> None:
    root = tmp_path / "client-support"
    store = _profile(root)
    profile = store.load("maxa")
    profile["research_records"][0]["scope"] = scope
    store.save(profile)

    with pytest.raises(ValueError):
        publish_research_checkpoint(
            client_root=root,
            profile_id="maxa",
            agent_id="research-maxa",
            carrier=_carrier(),
        )

    assert not (root / "profile-root" / "research").exists()
