from __future__ import annotations

import pytest

from tools.testers.ic_test.analysis_graph import (
    ICAnalysisGraph,
    apply_analysis_attachment,
    plan_analysis_attachment,
)
from tools.testers.ic_test.core import ICCoreTest


def _core(horizon: str, *, scope: str = "metals") -> ICCoreTest:
    return ICCoreTest(
        product_scope_ref=scope,
        factor_ref="factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        horizon=horizon,
        entry_delay_bars=0,
        method="rank",
        return_price_basis="next_open_to_open_adjusted",
    )


def test_map_each_attachment_builds_one_node_per_selected_core() -> None:
    min5 = _core("MIN5")
    min10 = _core("MIN10")
    graph = ICAnalysisGraph((min5, min10))

    plan = plan_analysis_attachment(
        graph,
        "rolling_ic_stability",
        (min10.core_test_ref, min5.core_test_ref),
        parameters={"rolling_windows": [{"unit": "signals", "value": 20}]},
    )
    updated = apply_analysis_attachment(graph, plan)

    assert plan.compatible is True
    assert plan.mapping == "map_each"
    assert plan.new_node_count == 2
    assert len(updated.analyses) == 2
    assert {node.target_refs for node in updated.analyses} == {
        (min5.core_test_ref,), (min10.core_test_ref,),
    }


def test_combine_attachment_builds_one_node_from_all_selected_cores() -> None:
    min5 = _core("MIN5")
    min10 = _core("MIN10")
    graph = ICAnalysisGraph((min5, min10))

    plan = plan_analysis_attachment(
        graph,
        "forward_horizon_half_life",
        (min10.core_test_ref, min5.core_test_ref),
    )
    updated = apply_analysis_attachment(graph, plan)

    assert plan.compatible is True
    assert plan.mapping == "combine"
    assert plan.new_node_count == 1
    assert updated.analyses[0].target_refs == tuple(sorted((
        min5.core_test_ref, min10.core_test_ref,
    )))


def test_attachment_is_idempotent_and_reports_duplicate_selection() -> None:
    core = _core("MIN5")
    graph = ICAnalysisGraph((core,))
    first = plan_analysis_attachment(
        graph,
        "rolling_ic_stability",
        (core.core_test_ref, core.core_test_ref),
        parameters={"rolling_windows": [{"unit": "signals", "value": 20}]},
    )
    updated = apply_analysis_attachment(graph, first)
    repeated = plan_analysis_attachment(
        updated,
        "rolling_ic_stability",
        (core.core_test_ref,),
        parameters={"rolling_windows": [{"unit": "signals", "value": 20}]},
    )

    assert first.duplicate_target_count == 1
    assert repeated.compatible is True
    assert repeated.new_node_count == 0
    assert len(repeated.existing_node_ids) == 1
    assert apply_analysis_attachment(updated, repeated) == updated


def test_batch_attachment_rejects_all_targets_when_one_is_incompatible() -> None:
    min5 = _core("MIN5")
    energy = _core("MIN10", scope="energy")
    graph = ICAnalysisGraph((min5, energy))

    plan = plan_analysis_attachment(
        graph,
        "forward_horizon_half_life",
        (min5.core_test_ref, energy.core_test_ref),
    )

    assert plan.compatible is False
    assert plan.new_node_count == 0
    assert {issue.code for issue in plan.issues} == {"same_axis"}
    with pytest.raises(ValueError, match="cannot apply incompatible"):
        apply_analysis_attachment(graph, plan)


def test_attachment_freezes_registered_defaults_and_rejects_unknown_parameters() -> None:
    core = _core("MIN5")
    graph = ICAnalysisGraph((core,))

    defaulted = plan_analysis_attachment(
        graph, "rolling_ic_stability", (core.core_test_ref,),
    )
    rejected = plan_analysis_attachment(
        graph,
        "rolling_ic_stability",
        (core.core_test_ref,),
        parameters={"unregistered_window": 20},
    )

    assert defaulted.parameters == {
        "rolling_windows": [{"unit": "signals", "value": 20}],
    }
    assert rejected.compatible is False
    assert {issue.code for issue in rejected.issues} == {"unknown_parameter"}


def test_attachment_rejects_empty_selection_and_invalid_registered_value() -> None:
    core = _core("MIN5")
    graph = ICAnalysisGraph((core,))

    empty = plan_analysis_attachment(graph, "rolling_ic_stability", ())
    invalid = plan_analysis_attachment(
        graph,
        "ic_autocorrelation",
        (core.core_test_ref,),
        parameters={"maximum_lag": 0},
    )

    assert empty.compatible is False
    assert {issue.code for issue in empty.issues} == {"target_count"}
    assert invalid.compatible is False
    assert {issue.code for issue in invalid.issues} == {"invalid_parameter"}
