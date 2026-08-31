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


def test_period_analysis_groups_series_by_registered_calendar_rule() -> None:
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
        "period_diagnostics",
        (core.core_test_ref,),
        parameters={"periods": [{"label": "day", "rule": "day", "min_signal_observations": 2, "min_periods": 1}]},
    )
    graph = apply_analysis_attachment(graph, attachment)
    node_id = attachment.nodes[0].node_id
    store = ICAnalysisResultStore()
    store.publish(
        core.core_test_ref,
        "ic_series",
        pd.Series(
            [0.1, 0.2, 0.3],
            index=pd.to_datetime([
                "2024-01-01 09:00", "2024-01-01 10:00", "2024-01-02 09:00",
            ]),
        ),
    )

    assert execute_ic_analysis_nodes(graph, (node_id,), store) == (node_id,)
    assert store.require(node_id, "ic_period_diagnostics").to_dict() == {
        "schema_version": 1,
        "periods": {
            "day": {
                "rule": "day",
                "min_signal_observations": 2,
                "min_periods": 1,
                "n_periods_total": 2,
                "n_periods_estimable": 1,
                "period_estimability_status": "estimable",
                "rows": [
                    {
                        "period_start": "2024-01-01T00:00:00",
                        "period_estimable": True,
                        "n": 2,
                        "mean_ic": 0.15,
                        "std_ic": 0.070711,
                        "ir": 2.12132,
                    },
                    {
                        "period_start": "2024-01-02T00:00:00",
                        "period_estimable": False,
                        "n": 1,
                        "mean_ic": 0.3,
                        "std_ic": None,
                        "ir": None,
                    },
                ],
            },
        },
    }
