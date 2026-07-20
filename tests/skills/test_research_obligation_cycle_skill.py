from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "research-obligation-cycle"
PACKAGED = (
    ROOT
    / "tools/cli/agent-harness/cli_anything/factortester_research/skills"
    / "research-obligation-cycle"
)


def _proposal() -> dict:
    return {
        "schema_version": 1,
        "proposal_id": "proposal-discovery",
        "proposer_invocation_id": "agent-invocation-proposal-discovery",
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "evidence_refs": ["trace:first-principles-review"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": "question is not empirical support",
        "obligation_delta": [{
            "obligation_id": "obligation-delivery",
            "from_state": "absent",
            "to_state": "open",
            "criterion_ref": "methodology:delivery-window",
            "obligation": {
                "schema_version": 1,
                "obligation_id": "obligation-delivery",
                "contract_hash": "1" * 64,
                "claim_ids": ["claim-1"],
                "obligation_kind": "delivery_window_discontinuity",
                "epistemic_question": "Does delivery proximity explain it?",
                "scope": {"delivery_window_days": 10},
                "discharge_criterion": {
                    "method": "predeclared window perturbation"
                },
                "status": "open",
                "materiality": "decision_blocking",
                "methodology_hash": "3" * 64,
                "created_event_ref": "trace:first-principles-review",
            },
        }],
        "decision_warrant": {
            "finding_refs": ["trace:first-principles-review"],
            "rule_refs": ["methodology:obligation-discovery"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "independent_reviewer",
        },
    }


def _run(script: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts" / script),
            "--input",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _synthesis(*, assessment: str, output: dict) -> dict:
    return {
        "schema_version": 1,
        "decision_contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "obligation_assessments": [{
            "obligation_id": "obligation-1",
            "disposition": assessment,
            "reason_ref": "review:actionability-1",
        }],
        "output": output,
    }


def test_skill_routes_to_exactly_one_progressive_reference() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "TODO" not in text
    references = {
        "discover": "obligation-discovery.md",
        "synthesize": "trial-synthesis.md",
        "adjudicate": "evidence-adjudication.md",
        "exhaustion": "search-exhaustion.md",
        "impact": "methodology-impact.md",
    }
    for mode, filename in references.items():
        assert f"`{mode}`" in text
        assert text.count(f"(references/{filename})") == 1
        assert (SKILL / "references" / filename).is_file()
    assert "Do not preload the other modes" in text
    assert (SKILL / "agents" / "openai.yaml").is_file()
    canonical_files = {
        path.relative_to(SKILL): path.read_bytes()
        for path in SKILL.rglob("*")
        if (
            path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        )
    }
    packaged_files = {
        path.relative_to(PACKAGED): path.read_bytes()
        for path in PACKAGED.rglob("*")
        if (
            path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        )
    }
    assert packaged_files == canonical_files


def test_standalone_validators_accept_discovery_and_reject_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(_proposal()), encoding="utf-8")

    obligation = _run("validate-obligation-proposal.py", path)
    adjudication = _run("validate-adjudication-proposal.py", path)

    assert obligation.returncode == 0, obligation.stderr + obligation.stdout
    assert adjudication.returncode == 0
    assert json.loads(obligation.stdout)["valid"] is True

    routed = {
        **_proposal(),
        "schema_version": 2,
        "recommended_action": "research_decision",
    }
    path.write_text(json.dumps(routed), encoding="utf-8")
    routed_result = _run("validate-adjudication-proposal.py", path)
    assert routed_result.returncode == 0, routed_result.stdout

    invalid = {**_proposal(), "skill_name": "must-stay-local"}
    path.write_text(json.dumps(invalid), encoding="utf-8")
    rejected = _run("validate-adjudication-proposal.py", path)
    assert rejected.returncode == 1
    assert "Skill identity" in json.loads(rejected.stdout)["error"]


def test_obligation_validator_requires_full_absent_to_open_body(
    tmp_path: Path,
) -> None:
    proposal = _proposal()
    proposal["obligation_delta"][0].pop("obligation")
    path = tmp_path / "missing-body.json"
    path.write_text(json.dumps(proposal), encoding="utf-8")

    result = _run("validate-obligation-proposal.py", path)

    assert result.returncode == 1
    assert "complete body" in json.loads(result.stdout)["error"]


def test_trial_synthesis_emits_no_plan_for_non_actionable_obligation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthesis.json"
    path.write_text(json.dumps(_synthesis(
        assessment="semantic_resolution",
        output={
            "disposition": "no_actionable_trial",
            "reason_ref": "review:no-empirical-trial",
        },
    )), encoding="utf-8")

    result = _run("validate-trial-synthesis.py", path)

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["disposition"] == (
        "no_actionable_trial"
    )


def test_trial_synthesis_rejects_plan_for_non_actionable_obligation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid-synthesis.json"
    path.write_text(json.dumps(_synthesis(
        assessment="backend_gap",
        output={
            "disposition": "trial_plan",
            "trial_plan": {
                "schema_version": 4,
                "obligation_refs": ["obligation-1"],
            },
        },
    )), encoding="utf-8")

    result = _run("validate-trial-synthesis.py", path)

    assert result.returncode == 1
    assert "non-actionable obligation" in json.loads(result.stdout)["error"]


def test_trial_synthesis_accepts_plan_for_actionable_obligation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "valid-synthesis.json"
    path.write_text(json.dumps(_synthesis(
        assessment="actionable_trial",
        output={
            "disposition": "trial_plan",
            "trial_plan": {
                "schema_version": 4,
                "obligation_refs": ["obligation-1"],
            },
        },
    )), encoding="utf-8")

    result = _run("validate-trial-synthesis.py", path)

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["disposition"] == "trial_plan"
