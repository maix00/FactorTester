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
            "cadc5f6ea5d308393284a45fdcdfc441"
            "f91acb9406412940c171c7e9e8edfc51"
        ),
        "trend": (
            "fbf4ca1db3c16257d1dca41ac4a6ee"
            "77d6b322fbcc561a0694542cbdd2f78c5c"
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
