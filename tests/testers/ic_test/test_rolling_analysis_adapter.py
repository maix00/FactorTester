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


def test_rolling_analysis_summarizes_each_signal_count_window() -> None:
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
        "rolling_ic_stability",
        (core.core_test_ref,),
        parameters={"rolling_windows": [3]},
    )
    graph = apply_analysis_attachment(graph, attachment)
    node_id = attachment.nodes[0].node_id
    store = ICAnalysisResultStore()
    store.publish(core.core_test_ref, "ic_series", pd.Series([0.1, 0.2, 0.3, 0.4, 0.5]))

    assert execute_ic_analysis_nodes(graph, (node_id,), store) == (node_id,)
    assert store.require(node_id, "rolling_ic_statistics").to_dict() == {
        "schema_version": 1,
        "window_unit": "signal_count",
        "rows": [{
            "requested_signal_count": 3,
            "rolling_windows_count": 3,
            "estimable": True,
            "detail_status": "summary_only",
            "mean_ic_p10": 0.22,
            "mean_ic_p50": 0.3,
            "mean_ic_p90": 0.38,
            "icir_p10": 2.2,
            "icir_p50": 3.0,
            "icir_p90": 3.8,
        }],
    }
