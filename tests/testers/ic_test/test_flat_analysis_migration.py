from __future__ import annotations

from tests.testers.ic_test.configuration_cases import (
    ROC,
    SGCCS,
    flat_settings,
    migrate_and_freeze,
)


def test_flat_analysis_fields_migrate_to_typed_execution_targets() -> None:
    settings = flat_settings(
        factor_selections=[flat_settings()["factor_selections"][0]],
        product_path_selections=[{"product_path_selection_id": "day"}],
        forward_return_horizons={
            "sampling": "explicit",
            "bases": ["signal"],
            "multipliers": [1, 2],
        },
        ic_decay_lags=[5, 1],
        rolling_windows={"signal_counts": [60, 20]},
        rolling_window=None,
        ic_periods=["day", "week"],
        quantile_portfolio_statistics={
            "enabled": True,
            "group_count": 5,
            "modes": ["no_fee"],
        },
    )
    configuration = migrate_and_freeze(settings, {ROC: "1m"})
    by_type: dict[str, list] = {}
    for node in configuration.analysis_graph.analyses:
        by_type.setdefault(node.analysis_type, []).append(node)

    assert len(configuration.analysis_graph.core_tests) == 8
    assert len(by_type["rolling_ic_stability"]) == 8
    assert len(by_type["quantile_portfolio_statistics"]) == 8
    assert len(by_type["ic_resample_stability"]) == 2
    assert len(by_type["period_diagnostics"]) == 2
    assert len(by_type["ic_autocorrelation"]) == 2
    assert len(by_type["forward_horizon_half_life"]) == 4
    assert {
        tuple(node.parameters["sampling_intervals"])
        for node in by_type["ic_resample_stability"]
    } == {(1, 5)}
    assert {
        tuple(item["value"] for item in node.parameters["rolling_windows"])
        for node in by_type["rolling_ic_stability"]
    } == {(20, 60)}
    assert all(
        len(node.target_refs) == 2
        for node in by_type["forward_horizon_half_life"]
    )


def test_output_requests_freeze_separately_from_analysis_nodes() -> None:
    settings = flat_settings()
    plain = migrate_and_freeze(settings, {ROC: "1m", SGCCS: "5m"})
    reports = migrate_and_freeze(
        settings,
        {ROC: "1m", SGCCS: "5m"},
        output_requests=("ic_statistics", "ic_series", "ic_statistics"),
    )

    assert plain.analysis_graph.to_dict() == reports.analysis_graph.to_dict()
    assert reports.output_requests == ("ic_series", "ic_statistics")
    assert plain.configuration_ref != reports.configuration_ref
    assert all(
        node.analysis_type not in reports.output_requests
        for node in reports.analysis_graph.analyses
    )
