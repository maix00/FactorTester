from __future__ import annotations

import settings as Settings

from server.services.research_evidence_registry import (
    admit_evidence, admit_evidence_for_graph,
    get_evidence,
    put_evidence,
)
from tests.server.data_contract_fixtures import initialize


_FACTOR_REF = (
    "factor:v1:profile-maxa:cGF0aA:U2dDUFNWb2w:"
    + "a" * 40 + ":" + "b" * 40
)


def _envelope() -> dict:
    hashes = {field: "a" * 64 for field in (
        "contract_hash", "methodology_hash", "trial_plan_hash", "run_spec_hash",
    )}
    return {
        "schema_version": 2,
        "envelope_id": "job-attempt:job-1",
        "evidence_kind": "job_attempt",
        "source_refs": ["research-job:job-1", "research-run:run-1"],
        "identity_refs": hashes,
        "facts": {},
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    }


def test_evidence_reuse_is_scoped_by_admission(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "cache.db"))
    record = put_evidence(
        owner="user-1",
        envelope=_envelope(),
        applicability={
            "product_refs": ["product:si"],
            "run_spec_hash": "a" * 64,
        },
    )
    loaded = get_evidence(owner="user-1", evidence_ref=record["evidence_ref"])
    assert loaded["applicability"]["product_refs"] == ["product:si"]
    admission = admit_evidence(
        owner="user-1",
        evidence_ref=record["evidence_ref"],
        environment_ref="research:2025",
        subject_ref=_FACTOR_REF,
        qualification="eligible",
    )
    assert admission["qualification"] == "eligible"
    updated = admit_evidence(
        owner="user-1",
        evidence_ref=record["evidence_ref"],
        environment_ref="research:2025",
        subject_ref=_FACTOR_REF,
        qualification="limited",
    )
    assert updated["qualification"] == "limited"


def test_graph_admission_derives_workspace_and_branch_scope(monkeypatch, tmp_path) -> None:
    path = tmp_path / "cache.db"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(path))
    initialize(path)
    record = put_evidence(
        owner="alice", envelope=_envelope(),
        applicability={"product_refs": ["product:si"], "run_spec_hash": "a" * 64},
    )
    admission = admit_evidence_for_graph(
        owner="alice", evidence_ref=record["evidence_ref"],
        instance_id="instance-1", branch_id="branch-1", qualification="eligible",
    )
    assert admission["environment_ref"] == "workspace:workspace-1"
    assert admission["subject_ref"] == "graph-branch:instance-1:branch-1"
