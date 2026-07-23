from __future__ import annotations

import json
from types import SimpleNamespace

from click.testing import CliRunner
import pytest

from cli_anything.factortester_research.commands import cycle as cycle_commands
from cli_anything.factortester_research.core.submission_contract import (
    build_cycle_submission_contract,
    validate_against_cycle_submission_contract,
    validate_contract_for_current_packet,
)
from cli_anything.factortester_research.factortester_research_cli import cli


def _packet() -> dict:
    return {
        "graph": "factor-research@v9",
        "context_ref": "sha256:" + "a" * 64,
        "branch": {"instance_id": "instance-1", "branch_id": "branch-1"},
        "node": {"node_id": "validation_design"},
        "budget_profile": {"ceiling_bytes": 12288},
        "current_obligations": [
            {
                "obligation_id": "sample-boundary",
                "question_summary": "样本边界是否冻结？",
            },
            {
                "obligation_id": "cost-control",
                "question_summary": "成本是否是唯一控制变量？",
            },
        ],
        "changed_refs": ["evidence:data-1"],
        "candidate_trial_frontier": {"current_trial_plan_hash": None},
        "entry_requirements": [
            {
                "requirement_id": "trial_design.control",
                "title_zh": "是否控制变量",
                "mapped_obligation_refs": ["obligation:cost-control"],
            }
        ],
        "candidate_edges": [
            {
                "edge_id": "validation_design__trial_execution",
                "to_node": "trial_execution",
                "required_research_evidence": ["trial_plan_frozen"],
                "required_transition_facts": ["entry_requirements_resolved"],
                "review_requirement": "none",
            }
        ],
    }


def test_contract_exposes_current_refs_and_independent_budgets() -> None:
    contract = build_cycle_submission_contract(
        _packet(), edge_id="validation_design__trial_execution",
    )

    assert contract["transition"] == {
        "edge_id": "validation_design__trial_execution",
        "from_node": "validation_design",
        "to_node": "trial_execution",
        "required_research_evidence": ["trial_plan_frozen"],
        "required_transition_facts": ["entry_requirements_resolved"],
        "review_requirement": "none",
    }
    assert [
        item["obligation_id"]
        for item in contract["reusable_refs"]["obligations"]
    ] == ["sample-boundary", "cost-control"]
    assert contract["budgets"]["agent_context_bytes"] == 12288
    assert contract["budgets"]["transition_evidence_bytes"] == 64 * 1024
    assert contract["budgets"]["report_submission_bytes"] == 16 * 1024


def test_contract_rejects_object_ref_where_trial_plan_needs_id() -> None:
    contract = build_cycle_submission_contract(
        _packet(), edge_id="validation_design__trial_execution",
    )
    evidence = {
        "trial_plan": {
            "primary_obligation_ref": "obligation:sample-boundary",
            "secondary_obligation_refs": [],
            "evidence_actions": [],
        }
    }

    with pytest.raises(
        ValueError, match="require bare obligation_id"
    ):
        validate_against_cycle_submission_contract(evidence, contract)


def test_contract_rejects_unknown_bare_obligation_id() -> None:
    contract = build_cycle_submission_contract(
        _packet(), edge_id="validation_design__trial_execution",
    )
    evidence = {
        "trial_plan": {
            "primary_obligation_ref": "not-current",
            "secondary_obligation_refs": [],
        }
    }

    with pytest.raises(ValueError, match="non-current obligations"):
        validate_against_cycle_submission_contract(evidence, contract)


def test_contract_derives_exact_reviewer_task_ref() -> None:
    proposal_hash = "b" * 64
    evidence = {
        "agent_invocation_ids": ["proposal-invocation"],
        "research_cycle": {
            "schema_version": 1,
            "events": [{
                "event_type": "adjudication_proposed",
                "proposal": {"proposal_hash": proposal_hash},
            }],
        },
    }
    contract = build_cycle_submission_contract(
        _packet(),
        edge_id="validation_design__trial_execution",
        evidence=evidence,
    )

    assert contract["derived_requirements"][
        "required_reviewer_task_refs"
    ] == [f"research-cycle-adjudication:{proposal_hash}"]


def test_contract_does_not_confuse_context_and_transition_budgets() -> None:
    contract = build_cycle_submission_contract(
        _packet(), edge_id="validation_design__trial_execution",
    )
    evidence = {"notes": "研究转换说明" * 2000}

    result = validate_against_cycle_submission_contract(evidence, contract)

    assert result["transition_evidence_bytes"] > 12288
    assert result["contract_valid"] is True


def test_contract_hash_rejects_manual_protocol_edits() -> None:
    contract = build_cycle_submission_contract(
        _packet(), edge_id="validation_design__trial_execution",
    )
    contract["request_schema"]["evidence_required"].append("guessed_field")

    with pytest.raises(ValueError, match="hash mismatch"):
        validate_against_cycle_submission_contract({}, contract)


def test_old_contract_is_rejected_before_submission() -> None:
    contract = build_cycle_submission_contract(
        _packet(), edge_id="validation_design__trial_execution",
    )
    current = _packet()
    current["context_ref"] = "sha256:" + "c" * 64

    with pytest.raises(ValueError, match="stale"):
        validate_contract_for_current_packet(
            contract,
            current,
            edge_id="validation_design__trial_execution",
        )


def test_contract_exposes_report_and_reference_grammar() -> None:
    packet = _packet()
    packet["node_report_requirement_refs"] = [
        "report.factor-semantics",
    ]
    contract = build_cycle_submission_contract(
        packet, edge_id="validation_design__trial_execution",
    )

    schema = contract["request_schema"]
    assert schema["report_requirements"]["node_refs"] == [
        "report.factor-semantics",
    ]
    assert schema["reference_grammar"]["trial_plan_obligation"] == (
        "<bare-obligation-id>"
    )
    assert contract["contract_hash"].startswith("sha256:")


def test_cycle_validate_with_contract_is_pure_local(
    monkeypatch, tmp_path,
) -> None:
    evidence_file = tmp_path / "evidence.json"
    contract_file = tmp_path / "contract.json"
    evidence_file.write_text("{}", encoding="utf-8")
    contract_file.write_text(json.dumps(build_cycle_submission_contract(
        _packet(), edge_id="validation_design__trial_execution",
    )), encoding="utf-8")

    def no_backend(*args, **kwargs):
        raise AssertionError("cycle validate must not contact backend")

    monkeypatch.setattr(cycle_commands, "run_factortester", no_backend)
    result = CliRunner().invoke(cli, [
        "cycle", "validate",
        "--evidence-file", str(evidence_file),
        "--contract-file", str(contract_file),
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["contract_valid"] is True


def test_cycle_advance_rejects_stale_contract_before_mutation(
    monkeypatch, tmp_path,
) -> None:
    evidence_file = tmp_path / "evidence.json"
    contract_file = tmp_path / "contract.json"
    evidence_file.write_text("{}", encoding="utf-8")
    contract_file.write_text(json.dumps(build_cycle_submission_contract(
        _packet(), edge_id="validation_design__trial_execution",
    )), encoding="utf-8")
    current = _packet()
    current["context_ref"] = "sha256:" + "d" * 64
    calls: list[list[str]] = []

    def backend(args: list[str], *, timeout: int):
        calls.append(args)
        if args[:2] == ["research-graph", "next"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(current),
                stderr="",
                argv=args,
            )
        raise AssertionError("mutation must not be called for stale contract")

    monkeypatch.setattr(cycle_commands, "run_factortester", backend)
    result = CliRunner().invoke(cli, [
        "cycle", "advance", "instance-1", "branch-1",
        "--edge-id", "validation_design__trial_execution",
        "--evidence-file", str(evidence_file),
        "--contract-file", str(contract_file),
        "--json",
    ])

    assert result.exit_code != 0
    assert "stale" in result.output
    assert calls == [[
        "research-graph", "next", "instance-1", "branch-1",
    ]]


def test_cycle_contract_help_explains_compatibility_path() -> None:
    result = CliRunner().invoke(cli, ["cycle", "advance", "--help"])

    assert result.exit_code == 0
    assert "--contract-file" in result.output
    assert "省略时保留旧版" in result.output
