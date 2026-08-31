from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.ic_test.analysis_graph import ICAnalysisGraph, ICCoreTest
from tools.testers.ic_test.analysis_graph.attachment import (
    apply_analysis_attachment,
    plan_analysis_attachment,
)
from tools.testers.ic_test.analysis_graph.runtime import (
    ICAnalysisResultStore,
    execute_ic_analysis_nodes,
)


def _graph() -> tuple[ICAnalysisGraph, ICCoreTest, str]:
    core = ICCoreTest(
        product_scope_ref="product-scope:metals",
        factor_ref="factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        horizon="MIN5",
        entry_delay_bars=0,
        method="rank",
        return_price_basis="next_open_to_open_adjusted",
    )
    graph = ICAnalysisGraph((core,))
    attachment = plan_analysis_attachment(
        graph,
        "ic_resample_stability",
        (core.core_test_ref,),
        parameters={"sampling_intervals": [2, 1, 2]},
    )
    graph = apply_analysis_attachment(graph, attachment)
    return graph, core, attachment.nodes[0].node_id


def test_resample_analysis_executes_from_typed_core_output() -> None:
    graph, core, node_id = _graph()
    store = ICAnalysisResultStore()
    store.publish(
        core.core_test_ref,
        "ic_series",
        pd.Series([0.1, None, 0.2, 0.3, 0.4]),
    )

    executed = execute_ic_analysis_nodes(graph, (node_id,), store)

    assert executed == (node_id,)
    result = store.require(node_id, "ic_resample_statistics")
    assert result.to_dict() == {
        "schema_version": 1,
        "sampling_unit": "effective_ic_observations",
        "rows": [
            {
                "sampling_interval": 1,
                "mean": 0.25,
                "std": 0.129099,
                "ir": 1.936492,
                "t_stat": 3.872983,
                "n": 4,
            },
            {
                "sampling_interval": 2,
                "mean": 0.2,
                "std": 0.141421,
                "ir": 1.414214,
                "t_stat": 2.0,
                "n": 2,
            },
        ],
    }


def test_analysis_execution_rejects_a_missing_typed_core_output() -> None:
    graph, _, node_id = _graph()

    with pytest.raises(
        ValueError,
        match="requires output kind ic_series",
    ):
        execute_ic_analysis_nodes(graph, (node_id,), ICAnalysisResultStore())


def test_duplicate_requested_analysis_is_executed_once() -> None:
    graph, core, node_id = _graph()
    store = ICAnalysisResultStore()
    store.publish(
        core.core_test_ref,
        "ic_series",
        pd.Series([0.1, 0.2, 0.3]),
    )

    assert execute_ic_analysis_nodes(graph, (node_id, node_id), store) == (node_id,)


def test_autocorrelation_uses_the_registered_maximum_lag() -> None:
    core = _graph()[1]
    graph = ICAnalysisGraph((core,))
    attachment = plan_analysis_attachment(
        graph,
        "ic_autocorrelation",
        (core.core_test_ref,),
        parameters={"maximum_lag": 2},
    )
    graph = apply_analysis_attachment(graph, attachment)
    node_id = attachment.nodes[0].node_id
    store = ICAnalysisResultStore()
    store.publish(
        core.core_test_ref,
        "ic_series",
        pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
    )

    assert execute_ic_analysis_nodes(graph, (node_id,), store) == (node_id,)
    assert store.require(node_id, "ic_autocorrelation").to_dict() == {
        "schema_version": 1,
        "estimator": "direct_numpy_adjusted_false",
        "n": 6,
        "maximum_lag_requested": 2,
        "maximum_lag_resolved": 2,
        "rows": [
            {"lag": 1, "autocorrelation": 0.5},
            {"lag": 2, "autocorrelation": 0.057143},
        ],
    }
