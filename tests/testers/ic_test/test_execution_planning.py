from __future__ import annotations

from dataclasses import replace

import pytest

from tools.testers.ic_test.configuration import (
    freeze_ic_run_configuration,
    migrate_flat_ic_settings,
)
from tools.testers.ic_test.execution import plan_ic_jobs, validate_ic_job_plan


ROC = "factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SGCCS = "factor:v2:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _configuration():
    frequencies = {ROC: "1m", SGCCS: "5m"}
    authoring = migrate_flat_ic_settings({
            "factor_selections": [
                {"factor_ref": ROC, "factor_alias": "ROC|$F:1m"},
                {"factor_ref": SGCCS, "factor_alias": "SgCCS|$F:5m"},
            ],
            "product_path_selections": [
                {"product_path_selection_id": "night"},
                {"product_path_selection_id": "day"},
            ],
            "forward_return_horizons": {
                "sampling": "explicit",
                "bases": ["signal"],
                "multipliers": [1, 2],
            },
            "ic_lags": [0, 1],
            "ic_correlation": "both",
            "return_price_basis": "next_open_to_open_adjusted",
            "rolling_window": 20,
            "ic_decay_lags": [1, 5],
        }, factor_frequencies=frequencies,
        output_requests=("ic_series", "ic_statistics"),
    )
    return freeze_ic_run_configuration(authoring, factor_frequencies=frequencies)


def test_planner_builds_one_deterministic_job_per_product_scope() -> None:
    configuration = _configuration()

    plans = plan_ic_jobs(configuration)

    assert tuple(plan.product_scope_ref for plan in plans) == ("day", "night")
    assert all(plan.configuration_ref == configuration.configuration_ref for plan in plans)
    assert all(plan.output_requests == ("ic_series", "ic_statistics") for plan in plans)
    assert {
        ref for plan in plans for ref in plan.core_test_refs
    } == {
        core.core_test_ref for core in configuration.analysis_graph.core_tests
    }
    assert sum(len(plan.core_test_refs) for plan in plans) == len(
        configuration.analysis_graph.core_tests
    )
    assert len({plan.plan_ref for plan in plans}) == 2
    assert plan_ic_jobs(configuration) == plans


def test_planner_keeps_only_analysis_nodes_owned_by_each_partition() -> None:
    configuration = _configuration()
    plans = plan_ic_jobs(configuration)
    cores = {
        core.core_test_ref: core for core in configuration.analysis_graph.core_tests
    }
    nodes = {
        node.node_id: node for node in configuration.analysis_graph.analyses
    }

    def target_scopes(ref: str) -> set[str]:
        if ref in cores:
            return {cores[ref].product_scope_ref}
        return {
            scope
            for target in nodes[ref].target_refs
            for scope in target_scopes(target)
        }

    for plan in plans:
        assert len(plan.analysis_node_ids) == len(set(plan.analysis_node_ids))
        positions = {
            node_id: index for index, node_id in enumerate(plan.analysis_node_ids)
        }
        for node_id in plan.analysis_node_ids:
            assert target_scopes(node_id) == {plan.product_scope_ref}
            assert all(
                target not in nodes or positions[target] < positions[node_id]
                for target in nodes[node_id].target_refs
            )


def test_planner_rejects_a_partition_that_does_not_match_the_frozen_graph() -> None:
    configuration = _configuration()
    day_refs = configuration.job_partitions["day"]
    night_refs = configuration.job_partitions["night"]
    tampered = replace(
        configuration,
        job_partitions={"day": (*day_refs, night_refs[0]), "night": night_refs[1:]},
    )

    with pytest.raises(ValueError, match="partition scope does not match"):
        plan_ic_jobs(tampered)


def test_execution_plan_round_trips_with_a_content_addressed_identity() -> None:
    plan = plan_ic_jobs(_configuration())[0]

    restored = type(plan).from_dict(plan.to_dict())

    assert restored == plan
    assert restored.plan_ref == plan.plan_ref


def test_job_plan_must_match_the_product_subset_derived_from_run_configuration() -> None:
    configuration = _configuration()
    plan = plan_ic_jobs(configuration)[0]

    assert validate_ic_job_plan(configuration, plan) == plan

    tampered = replace(plan, analysis_node_ids=())
    with pytest.raises(ValueError, match="does not match frozen IC configuration"):
        validate_ic_job_plan(configuration, tampered)
