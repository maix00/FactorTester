from __future__ import annotations

import pytest

from tools.testers.ic_test.configuration import compile_ic_run_configuration
from tools.testers.ic_test.execution import ICRunExecutionBundle


ROC = "factor:v1:profile-maxa:path:roc:commit:blob"


def _bundle() -> ICRunExecutionBundle:
    configuration = compile_ic_run_configuration(
        {
            "factor_selections": [{"factor_ref": ROC}],
            "product_path_selections": [
                {"product_path_selection_id": "day"},
                {"product_path_selection_id": "night"},
            ],
            "forward_return_horizons": {
                "sampling": "explicit",
                "bases": ["signal"],
                "multipliers": [1, 5],
            },
            "ic_lags": [0],
            "ic_correlation": "rank",
            "return_price_basis": "next_open_to_open_adjusted",
        },
        factor_frequencies={ROC: "1m"},
        output_requests=("ic_series",),
    )
    return ICRunExecutionBundle.from_configuration(configuration)


def test_run_bundle_stores_one_configuration_and_referencing_job_plans() -> None:
    bundle = _bundle()
    payload = bundle.to_dict()

    assert payload["configuration"]["resolved_horizons_by_factor"][ROC] == [
        {
            "physical_frequency": "MIN1",
            "origins": [{"base": "signal", "multiplier": 1}],
        },
        {
            "physical_frequency": "MIN5",
            "origins": [{"base": "signal", "multiplier": 5}],
        },
    ]
    assert len(payload["job_plans"]) == 2
    assert all(
        plan["configuration_ref"] == bundle.configuration.configuration_ref
        for plan in payload["job_plans"]
    )
    assert all("configuration" not in plan for plan in payload["job_plans"])


def test_run_bundle_round_trips_and_rejects_a_missing_partition_plan() -> None:
    bundle = _bundle()
    assert ICRunExecutionBundle.from_dict(bundle.to_dict()) == bundle

    payload = bundle.to_dict()
    payload["job_plans"].pop()
    with pytest.raises(ValueError, match="exactly one Job plan per product scope"):
        ICRunExecutionBundle.from_dict(payload)


def test_run_bundle_rejects_a_job_plan_from_another_configuration() -> None:
    payload = _bundle().to_dict()
    payload["job_plans"][0]["configuration_ref"] = "ic-run-configuration:v1:other"

    with pytest.raises(ValueError, match="plan_ref does not match"):
        ICRunExecutionBundle.from_dict(payload)

