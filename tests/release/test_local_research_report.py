from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting import (
    publish_research_checkpoint as _publish_checkpoint,
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


def publish_research_checkpoint(**kwargs):
    carrier = kwargs["carrier"]
    kwargs.setdefault("narrative", _narrative(carrier))
    return _publish_checkpoint(**kwargs)


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
    assert "evidence:job-attempt-1" in report.read_text(encoding="utf-8")
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
    assert record["artifacts"][0]["journal_ref"].endswith("/JOURNAL.json")
    assert len(record["artifacts"][0]["journal_hash"]) == 64
    assert len(result["carrier_hash"]) == 64
    assert len(result["narrative_hash"]) == 64
    assert len(result["section_hash"]) == 64
    assert "本次检验显示信号" in report.read_text(encoding="utf-8")


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


def test_checkpoint_publish_materializes_source_prefix_for_fork(
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
        "trace:checkpoint-1",
        "trace:checkpoint-fork-1",
    ]
    assert journal["checkpoints"][0]["lineage_status"] == "root"
    assert journal["checkpoints"][1]["lineage_status"] == "linked"
    report = (branch_root / "REPORT.md").read_text(encoding="utf-8")
    assert report.index("源分支首先") < report.index("分支随后")
    assert len(list((branch_root / "sections").glob("*.json"))) == 2


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
    with pytest.raises(ValueError, match="trusted source journal"):
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
    assert journal["schema_version"] == 3
    assert journal["history_status"] == "complete"
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
                "columns": ["检验", "指标", "结果"],
                "rows": [{
                    "cells": ["成本后回测", "夏普比率", "0.42"],
                    "link_ids": ["checkpoint-evidence"],
                }],
            }],
            "links": [{
                "link_id": "cost-obligation",
                "kind": "obligation",
                "target_ref": "obligation:cost-survival",
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
    assert journal["schema_version"] == 3
    assert [block["kind"] for block in section["blocks"]] == [
        "paragraph", "list", "table",
    ]
    assert section["blocks"][0]["link_ids"] == ["checkpoint-plan"]
    assert section["blocks"][2]["rows"][0]["cells"][2] == "0.42"
    report = journal_path.with_name("REPORT.md").read_text(encoding="utf-8")
    assert "本阶段先说明研究判断，再列出支撑判断的结构化结果。" in report
    assert "- 交易成本义务仍未清除。" in report
    assert "| 检验 | 指标 | 结果 |" in report
    assert "| 成本后回测 | 夏普比率 | 0.42 |" in report


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
    assert "scope:sha256:" in report
    assert "scope:sha256:" in report
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
