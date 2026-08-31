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


def test_half_life_combines_same_axes_horizon_statistics() -> None:
    cores = tuple(
        ICCoreTest(
            product_scope_ref="product-scope:metals",
            factor_ref="factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            horizon=horizon,
            entry_delay_bars=0,
            method="rank",
            return_price_basis="next_open_to_open_adjusted",
        )
        for horizon in ("MIN1", "MIN3", "MIN5")
    )
    graph = ICAnalysisGraph(cores)
    attachment = plan_analysis_attachment(
        graph,
        "forward_horizon_half_life",
        tuple(core.core_test_ref for core in cores),
    )
    graph = apply_analysis_attachment(graph, attachment)
    node_id = attachment.nodes[0].node_id
    store = ICAnalysisResultStore()
    for core, seconds, mean in zip(cores, (60.0, 180.0, 300.0), (0.08, 0.04, 0.02)):
        store.publish(
            core.core_test_ref,
            "ic_statistics",
            pd.Series({
                "horizon_seconds": seconds,
                "horizon": core.horizon,
                "mean_ic": mean,
            }),
        )

    assert execute_ic_analysis_nodes(graph, (node_id,), store) == (node_id,)
    result = store.require(node_id, "forward_horizon_half_life").to_dict()
    assert result["schema_version"] == 1
    assert result["status"] == "estimated"
    assert result["half_life_seconds"] == 120.0
