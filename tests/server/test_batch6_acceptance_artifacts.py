"""Hard-budget checks for the real-factor acceptance fixtures."""

from pathlib import Path
import runpy

from server.services.research_graph.protocol import MAX_AGENT_PACKET_BYTES


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "docs" / "research-decision-graph" / "acceptance"
GENERATOR = ACCEPTANCE / "generate_batch6_live_artifacts.py"


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
        assert result["trial_freeze_trace_bytes"] <= MAX_AGENT_PACKET_BYTES
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
