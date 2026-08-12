from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli_anything.factortester_research.factortester_research_cli import cli
from cli_anything.factortester_research.core.trial_plan_fixture import (
    validate_trial_plan_fixture,
)
from server.services.research_graph.trial_plan import canonical_trial_plan


FIXTURE = Path(__file__).with_name("fixtures") / (
    "factor_research_trial_sequence.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_factor_research_sequence_preserves_dependencies_and_controls() -> None:
    document = _fixture()
    plan = canonical_trial_plan(document["trial_plan"])

    result = validate_trial_plan_fixture(
        plan,
        validation_contract=document["validation_contract"],
        action_input_summaries=document["action_input_summaries"],
        run_spec_summaries=document["run_spec_summaries"],
    )

    assert result == {
        "passed": True,
        "ordered_action_ids": [
            "action:full-product-eligibility",
            "action:session-cohort-partition",
            "action:in-sample-ic",
            "action:gross-backtest",
            "action:net-backtest",
        ],
        "declared_action_roles": [
            "gross_backtest",
            "in_sample_ic",
            "net_backtest",
            "product_eligibility",
            "session_partition",
        ],
        "required_dependencies": [
            ["product_eligibility", "session_partition"],
            ["session_partition", "in_sample_ic"],
            ["in_sample_ic", "gross_backtest"],
            ["gross_backtest", "net_backtest"],
        ],
        "control_pairs": [
            "control:ic-day-to-gross-day",
            "control:ic-night-to-gross-night",
            "comparison:day-cost",
            "comparison:night-cost",
        ],
    }


def test_factor_research_sequence_is_available_through_public_cli() -> None:
    result = CliRunner().invoke(
        cli,
        ["graph", "trial-plan-check", str(FIXTURE), "--json"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["passed"] is True


def test_fixture_validator_does_not_impose_one_global_action_order() -> None:
    document = _fixture()
    document["trial_plan"]["evidence_actions"].reverse()

    result = validate_trial_plan_fixture(
        document["trial_plan"],
        validation_contract=document["validation_contract"],
        action_input_summaries=document["action_input_summaries"],
        run_spec_summaries=document["run_spec_summaries"],
    )

    assert result["passed"] is True
    assert result["ordered_action_ids"][0] == "action:net-backtest"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda doc: doc["action_input_summaries"][
                "action:full-product-eligibility"
            ].update({"candidate_scope": "core8"}),
            "candidate scope",
        ),
        (
            lambda doc: doc["trial_plan"]["evidence_actions"][2].update({
                "prerequisite_action_ids": [
                    "action:full-product-eligibility"
                ]
            }),
            "required predecessor",
        ),
        (
            lambda doc: doc["run_spec_summaries"][
                "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
            ].update({"session_cohort": "day"}),
            "declared session cohorts",
        ),
        (
            lambda doc: doc["run_spec_summaries"][
                "9999999999999999999999999999999999999999999999999999999999999999"
            ].update({"scope_ref": "scope:core8"}),
            "invariant control fields",
        ),
        (
            lambda doc: doc["run_spec_summaries"][
                "9999999999999999999999999999999999999999999999999999999999999999"
            ].update({"sample_ref": "sample:holdout"}),
            "invariant control fields",
        ),
    ],
)
def test_factor_research_sequence_rejects_scope_or_dependency_drift(
    mutation,
    message: str,
) -> None:
    document = deepcopy(_fixture())
    mutation(document)
    plan = canonical_trial_plan(document["trial_plan"])

    with pytest.raises(ValueError, match=message):
        validate_trial_plan_fixture(
            plan,
            validation_contract=document["validation_contract"],
            action_input_summaries=document["action_input_summaries"],
            run_spec_summaries=document["run_spec_summaries"],
        )
