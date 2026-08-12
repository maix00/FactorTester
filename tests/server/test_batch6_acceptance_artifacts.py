"""Hard-budget checks for the real-factor acceptance fixtures."""

import hashlib
from pathlib import Path
import runpy

import orjson

from server.services.research_graph.protocol import (
    MAX_AGENT_PACKET_BYTES,
    MAX_PERSISTED_TRACE_BYTES,
)


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "docs" / "research-decision-graph" / "acceptance"
GENERATOR = ACCEPTANCE / "generate_batch6_live_artifacts.py"
TOKEN_CONTEXT_RECEIPT = ACCEPTANCE / "batch6-token-context-receipt.json"


def test_batch6_token_context_receipt_is_truthful_and_addressed() -> None:
    receipt = orjson.loads(TOKEN_CONTEXT_RECEIPT.read_bytes())
    declared_hash = receipt.pop("receipt_hash")

    assert hashlib.sha256(
        orjson.dumps(receipt, option=orjson.OPT_SORT_KEYS)
    ).hexdigest() == declared_hash
    assert receipt["assessment"]["status"] == "blocked"
    assert receipt["assessment"]["release_ready"] is False
    assert (
        receipt["assessment"]["actual_provider_token_telemetry_proven"]
        is False
    )
    assert receipt["assessment"]["accepted_job_evidence_proven"] is True
    assert receipt["assessment"]["source_jobs_rerun"] is False
    assert all(
        branch["context_bytes"] <= MAX_AGENT_PACKET_BYTES
        and branch["replay_passed"] is True
        and branch["closure_disposition"] == "blocked"
        for branch in receipt["continuation_branches"]
    )
    assert receipt["database_bounds"]["routine_context_loads_full_graph"] is False


def test_batch6_trial_plan_binding_fits_trace_budget(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(ACCEPTANCE))
    module = runpy.run_path(str(GENERATOR))

    expected_hashes = {
        "sgccs": (
            "4dbf884db5aa2de27ef888838baea7a"
            "7cec9a79e1434bc5c2c0dceb422f0d4ef"
        ),
        "trend": (
            "8da9218b8024f3331f55993e4bfd88ff"
            "f895673cd4a4179183c45180076a3603"
        ),
    }
    for case_name, case in module["CASES"].items():
        result = module["build_case"](
            case_name,
            case,
            planning_invocation_id="planning-fixture",
        )

        assert result["trial_plan_hash"] == expected_hashes[case_name]
        assert result["trial_freeze_trace_bytes"] <= MAX_PERSISTED_TRACE_BYTES
        assert result["trial_plan"]["protocol_ref"] == "runspec-v1"
        assert result["trial_plan"]["criteria"] == {
            "rejection_ref": "id-or-null",
            "revision_ref": "conflict",
            "continuation_ref": "new-plan",
        }
        assert {
            member["run_spec_hash"]
            for comparison in result["trial_plan"]["comparisons"]
            for member in comparison["members"]
        } == set(case["run_spec_hashes"].values())
