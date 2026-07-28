"""Small valid inputs shared by current report-tree integration tests."""

from __future__ import annotations

from pathlib import Path

from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.publisher import publish_research_checkpoint as _publish


def carrier() -> dict:
    return {
        "schema_version": 2, "workspace_ref": "workspace:workspace-maxa",
        "work_package_ref": "work-package:sgccs-review",
        "branch_ref": "graph-branch:sgccs-review:branch-sgccs",
        "graph_ref": "factor-research@v6", "checkpoint_ref": "trace:checkpoint-1",
        "research_cycle_ref": "research-cycle:sha256:" + "4" * 64,
        "title": "SgCCS checkpoint", "product_group": "CNFutures",
        "current_node": "job_evidence_ready", "status": "running",
        "decision_contract_hash": "2" * 64, "methodology_hash": "1" * 64,
        "trial_plan_hash": "3" * 64, "evidence_refs": ["evidence:job-attempt-1"],
        "omitted_evidence_count": 0, "job_refs": ["job:job-1"],
        "run_refs": ["run:run-1"],
        "claims": [{"claim_ref": "claim:predictive-relation", "claim_type": "bounded_predictive_relationship", "evidence_state": "inconclusive"}],
        "open_obligations": [{"obligation_ref": "obligation:cost-survival", "status": "open", "materiality": "decision_blocking", "question_summary": "Does the signal survive costs?"}],
        "closure": None,
        "report_lineage": {"status": "root", "predecessor_checkpoint_ref": ""},
        "latest_transition": {
            "step_ref": "trace:checkpoint-1", "edge_ref": "graph-edge:backtest__job_evidence_ready",
            "from_node": "authoritative_backtest", "to_node": "job_evidence_ready",
            "created_at": 2.0, "evidence_refs": ["evidence:job-attempt-1"],
            "trial_plan_refs": ["trial-plan:sha256:" + "3" * 64],
            "obligation_refs": ["obligation:cost-survival"],
            "claim_refs": ["claim:predictive-relation"], "job_refs": ["job:job-1"],
            "run_refs": ["run:run-1"], "delta_refs": [],
            "obligation_changes": [], "claim_changes": [],
        },
    }


def narrative(value: dict) -> dict:
    transition = value["latest_transition"]
    targets = [
        (kind, ref)
        for kind, refs in (
            ("evidence", value["evidence_refs"]),
            ("job", value["job_refs"]),
            ("run", value["run_refs"]),
            ("evidence", transition["evidence_refs"]),
            ("trial_plan", transition["trial_plan_refs"]),
            ("obligation", transition["obligation_refs"]),
            ("claim", transition["claim_refs"]),
            ("job", transition["job_refs"]),
            ("run", transition["run_refs"]),
            ("delta", transition["delta_refs"]),
        )
        for ref in refs
    ]
    targets = list(dict.fromkeys(targets))
    return {
        "schema_version": 1, "language": "zh-Hans", "title": "因子研究报告",
        "sections": [{
            "section_id": "research-progress", "title": "研究进展",
            "body": "本次检验显示信号仍需结合成本证据继续研究。",
            "links": [{"link_id": f"checkpoint-{index}", "kind": kind, "target_ref": ref} for index, (kind, ref) in enumerate(targets)],
        }],
    }


def publish_research_checkpoint(**kwargs):
    value = kwargs["carrier"]
    kwargs.setdefault("narrative", narrative(value))
    return _publish(**kwargs)


def profile(root: Path) -> LocalProfileStore:
    store = LocalProfileStore(root)
    value = new_local_profile(
        profile_id="maxa", display_name="MaxA", server_url="http://127.0.0.1:8141",
        workspace_root=root / "profile-root",
    )
    value["agents"] = [{"agent_id": "research-maxa", "role": "research", "scope": {"instance_id": "sgccs-review", "branch_id": "branch-sgccs"}, "status": "ready", "next_action": "Resume the authorized research scope."}]
    value["workspaces"] = [{"workspace_id": "workspace-maxa", "path": str(root / "user-factor-library"), "access_mode": "owner", "owner_ref": "18717974771", "server_workspace_ref": "workspace:workspace-maxa"}]
    value["research_records"] = [{
        "record_id": "sgccs-review", "title": "SgCCS review", "status": "pending",
        "scope": {"factor_families": ["SgCCS"]}, "factor_family_versions": ["MaxA:SgCCS@7"],
        "agent_id": "research-maxa", "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "workspace:workspace-maxa", "run_ref": "",
        "graph_instance_ref": "work-package:sgccs-review",
        "graph_branch_ref": "graph-branch:sgccs-review:branch-sgccs",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [], "artifacts": [],
        "provenance": {"kind": "owned_research", "owner_ref": "maxa"},
    }]
    store.save(value)
    return store
