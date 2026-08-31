from __future__ import annotations

import pytest

from tools.testers.ic_test.analysis_graph import ICAnalysisGraph, ICAnalysisNode
from tools.testers.ic_test.core import ICCoreTest


def _core(horizon: str) -> ICCoreTest:
    return ICCoreTest(
        product_scope_ref="metals",
        factor_ref="factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY",
        horizon=horizon,
        entry_delay_bars=0,
        method="rank",
        return_price_basis="next_open_to_open_adjusted",
    )


def test_cycle_is_rejected_before_analysis_execution() -> None:
    graph = ICAnalysisGraph(
        core_tests=(),
        analyses=(
            ICAnalysisNode("left", "rolling_ic_stability", ("right",)),
            ICAnalysisNode("right", "period_diagnostics", ("left",)),
        ),
    )

    with pytest.raises(ValueError, match="contains a cycle"):
        graph.validate()


def test_unknown_analysis_parameter_is_rejected() -> None:
    core = _core("MIN5")
    graph = ICAnalysisGraph(
        core_tests=(core,),
        analyses=(
            ICAnalysisNode(
                "rolling",
                "rolling_ic_stability",
                (core.core_test_ref,),
                {"unregistered_window": 20},
            ),
        ),
    )

    with pytest.raises(ValueError, match="unknown parameters"):
        graph.validate()


def test_registered_analysis_parameter_constraints_are_enforced() -> None:
    core = _core("MIN5")
    graph = ICAnalysisGraph(
        core_tests=(core,),
        analyses=(
            ICAnalysisNode(
                "autocorrelation",
                "ic_autocorrelation",
                (core.core_test_ref,),
                {"maximum_lag": 0},
            ),
        ),
    )

    with pytest.raises(ValueError, match="invalid_parameter"):
        graph.validate()


def test_combine_analysis_requires_equal_values_on_fixed_axes() -> None:
    core = _core("MIN5")
    other_method = ICCoreTest(
        product_scope_ref=core.product_scope_ref,
        factor_ref=core.factor_ref,
        horizon=core.horizon,
        entry_delay_bars=core.entry_delay_bars,
        method="pearson",
        return_price_basis=core.return_price_basis,
    )
    graph = ICAnalysisGraph(
        core_tests=(core, other_method),
        analyses=(
            ICAnalysisNode(
                "half-life",
                "forward_horizon_half_life",
                (core.core_test_ref, other_method.core_test_ref),
            ),
        ),
    )

    with pytest.raises(ValueError, match="same_axis"):
        graph.validate()


def test_half_life_cannot_mix_return_price_bases() -> None:
    core = _core("MIN5")
    other_basis = ICCoreTest(
        product_scope_ref=core.product_scope_ref,
        factor_ref=core.factor_ref,
        horizon="MIN10",
        entry_delay_bars=core.entry_delay_bars,
        method=core.method,
        return_price_basis="next_close_to_close_adjusted",
    )
    graph = ICAnalysisGraph(
        core_tests=(core, other_basis),
        analyses=(
            ICAnalysisNode(
                "half-life",
                "forward_horizon_half_life",
                (core.core_test_ref, other_basis.core_test_ref),
            ),
        ),
    )

    with pytest.raises(ValueError, match="same_axis"):
        graph.validate()


def test_serialized_execution_graph_is_canonical_not_display_ordered() -> None:
    min5 = _core("MIN5")
    min10 = _core("MIN10")
    first = ICAnalysisNode("z-period", "period_diagnostics", (min5.core_test_ref,))
    second = ICAnalysisNode("a-period", "period_diagnostics", (min10.core_test_ref,))

    left = ICAnalysisGraph((min5, min10), (first, second)).to_dict()
    right = ICAnalysisGraph((min10, min5), (second, first)).to_dict()

    assert left == right
    assert [item["node_id"] for item in left["analyses"]] == [
        "a-period",
        "z-period",
    ]
