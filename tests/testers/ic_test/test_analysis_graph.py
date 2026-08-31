from __future__ import annotations

import pytest

from tools.testers.ic_test.analysis_graph import (
    ICAnalysisGraph,
    ICAnalysisNode,
    ICCoreTest,
)


def _core(
    factor: str,
    horizon: str,
    *,
    delay: int = 0,
    method: str = "rank",
    scope: str = "metals",
) -> ICCoreTest:
    return ICCoreTest(
        product_scope_ref=scope,
        factor_ref=factor,
        horizon=horizon,
        entry_delay_bars=delay,
        method=method,
        return_price_basis="next_open_to_open_adjusted",
    )


def test_core_test_identity_is_deterministic_and_uses_execution_axes() -> None:
    left = _core("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "MIN5")
    right = _core("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "MIN5")
    other = _core("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "MIN10")

    assert left.core_test_ref == right.core_test_ref
    assert left.core_test_ref != other.core_test_ref
    assert left.to_dict() == {
        "core_test_ref": left.core_test_ref,
        "product_scope_ref": "metals",
        "factor_ref": "factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY",
        "horizon": "MIN5",
        "entry_delay_bars": 0,
        "method": "rank",
        "return_price_basis": "next_open_to_open_adjusted",
    }


def test_analysis_graph_accepts_single_core_analyses_and_cross_horizon_reduce() -> None:
    min5 = _core("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "MIN5")
    min10 = _core("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "MIN10")
    graph = ICAnalysisGraph(
        core_tests=(min5, min10),
        analyses=(
            ICAnalysisNode(
                node_id="rolling-min5",
                analysis_type="rolling_ic_stability",
                target_refs=(min5.core_test_ref,),
                parameters={"rolling_windows": [{"unit": "signals", "value": 20}]},
            ),
            ICAnalysisNode(
                node_id="half-life",
                analysis_type="forward_horizon_half_life",
                target_refs=(min5.core_test_ref, min10.core_test_ref),
                parameters={},
            ),
        ),
    )

    assert graph.validate() is graph
    assert graph.output_kind("rolling-min5") == "rolling_ic_statistics"
    assert graph.to_dict()["schema_version"] == 1


def test_analysis_graph_rejects_analysis_target_for_core_only_type() -> None:
    core = _core("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "MIN5")
    graph = ICAnalysisGraph(
        core_tests=(core,),
        analyses=(
            ICAnalysisNode(
                node_id="rolling",
                analysis_type="rolling_ic_stability",
                target_refs=(core.core_test_ref,),
                parameters={"rolling_windows": [{"unit": "signals", "value": 20}]},
            ),
            ICAnalysisNode(
                node_id="period-on-rolling",
                analysis_type="period_diagnostics",
                target_refs=("rolling",),
                parameters={},
            ),
        ),
    )

    with pytest.raises(ValueError, match="target_origin"):
        graph.validate()


def test_analysis_graph_rejects_incompatible_cross_horizon_group() -> None:
    metals = _core("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "MIN5", scope="metals")
    energy = _core("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "MIN10", scope="energy")
    graph = ICAnalysisGraph(
        core_tests=(metals, energy),
        analyses=(
            ICAnalysisNode(
                node_id="half-life",
                analysis_type="forward_horizon_half_life",
                target_refs=(metals.core_test_ref, energy.core_test_ref),
                parameters={},
            ),
        ),
    )

    with pytest.raises(ValueError, match="same_axis"):
        graph.validate()
