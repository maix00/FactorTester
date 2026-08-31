from __future__ import annotations

import pandas as pd

from tools.testers.ic_test.analysis_graph import ICAnalysisGraph, ICCoreTest
from tools.testers.ic_test.analysis_graph.attachment import (
    apply_analysis_attachment,
    plan_analysis_attachment,
)
from tools.testers.ic_test.analysis_graph.runtime import (
    ICAnalysisResultStore,
    execute_ic_analysis_nodes,
)


def test_quantile_analysis_consumes_core_panels_without_ic_series() -> None:
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
        "quantile_portfolio_statistics",
        (core.core_test_ref,),
        parameters={
            "portfolio": {
                "group_count": 2,
                "modes": ["no_fee"],
                "include_return_series": True,
            },
        },
    )
    graph = apply_analysis_attachment(graph, attachment)
    node_id = attachment.nodes[0].node_id
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    store = ICAnalysisResultStore()
    store.publish(core.core_test_ref, "factor_values", pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": [3.0, 2.0, 1.0]}, index=index))
    store.publish(core.core_test_ref, "forward_returns", pd.DataFrame({"A": [0.1, 0.2, 0.3], "B": [0.0, -0.1, -0.2]}, index=index))
    store.publish(core.core_test_ref, "eligibility", pd.DataFrame(True, index=index, columns=["A", "B"]))

    assert execute_ic_analysis_nodes(graph, (node_id,), store) == (node_id,)
    result = store.require(node_id, "quantile_portfolio_statistics").to_dict()
    assert result["artifact_kind"] == "quantile_portfolio_statistics"
    assert result["group_count"] == 2
    assert sorted(result["modes"]) == ["no_fee"]
