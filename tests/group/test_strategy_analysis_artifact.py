import pytest

from tools.factors.tester_calc.single_factor_test.group.strategy_analysis import (
    STRATEGY_ANALYSIS_TABS,
    build_strategy_analysis_bundle,
    build_strategy_analysis_source,
    build_strategy_analysis_tab,
)


def test_strategy_analysis_source_contains_primitives_not_computed_tabs():
    execution = {
        "group_owner": [
            {
                "strategy_id": "strategy-0", "display_name": "第一组",
                "group_index": 0, "product_path_selection_id": "products-a",
                "strategy_configuration_id": "config-a",
            },
            {
                "strategy_id": "strategy-1", "display_name": "第二组",
                "group_index": 1, "product_path_selection_id": "products-a",
                "strategy_configuration_id": "config-a",
            },
        ],
        "engine_result": {"portfolios": {
            "strategy-0": {
                "equity_curve": {
                    "2024-01-01T00:00:00": 100.0,
                    "2024-01-02T00:00:00": 102.0,
                },
                "position_curve": {
                    "2024-01-01T00:00:00": {"CU.SHF": 1.0},
                    "2024-01-02T00:00:00": {"CU.SHF": 1.0},
                },
            },
            "strategy-1": {
                "equity_curve": {
                    "2024-01-01T00:00:00": 100.0,
                    "2024-01-02T00:00:00": 99.0,
                },
                "position_curve": {
                    "2024-01-01T00:00:00": {"AL.SHF": 1.0},
                    "2024-01-02T00:00:00": {"AL.SHF": 1.0},
                },
            },
        }},
    }
    serialized = {
        "groups": [
            {"strategy_id": "strategy-0", "metrics_key": "strategy-0"},
            {"strategy_id": "strategy-1", "metrics_key": "strategy-1"},
        ],
        "metrics": {
            "strategy-0": {"Total Return": 0.02},
            "strategy-1": {"Total Return": -0.01},
        },
    }

    value = build_strategy_analysis_source(execution, serialized)

    assert value["artifact_version"] == 1
    assert set(value["strategies"]) == {"strategy-0", "strategy-1"}
    first = value["strategies"]["strategy-0"]
    assert first["result_group"]["strategy_id"] == "strategy-0"
    assert first["position_curve"]["2024-01-01T00:00:00"] == {"CU.SHF": 1.0}
    assert value["metrics"]["strategy-0"] == {"Total Return": 0.02}
    assert "detail" not in first
    assert "rankings" not in value


def test_strategy_analysis_tab_computes_only_requested_payload():
    source = build_strategy_analysis_source(
        {
            "group_owner": [{
                "strategy_id": "strategy-0",
                "display_name": "第一组",
                "group_index": 0,
                "product_path_selection_id": "products-a",
                "strategy_configuration_id": "config-a",
            }],
            "engine_result": {"portfolios": {"strategy-0": {
                "equity_curve": {
                    "2024-01-01T00:00:00": 100.0,
                    "2024-01-02T00:00:00": 102.0,
                },
                "position_curve": {
                    "2024-01-01T00:00:00": {"CU.SHF": 1.0},
                    "2024-01-02T00:00:00": {"CU.SHF": 1.0},
                },
            }}},
        },
        {
            "groups": [{
                "strategy_id": "strategy-0",
                "metrics_key": "strategy-0",
                "timestamps": [1704067200000, 1704153600000],
                "total_equity": [100.0, 102.0],
            }],
            "metrics": {"strategy-0": {"Total Return": 0.02}},
        },
    )

    result = build_strategy_analysis_tab(source, {
        "analysis_tab": "returns", "strategy_id": "strategy-0",
    })

    assert set(result) == {"return_series"}
    assert result["return_series"][-1]["return"] == pytest.approx(0.02)


def test_strategy_analysis_bundle_fills_every_registered_strategy_tab():
    source = build_strategy_analysis_source(
        {
            "group_owner": [{
                "strategy_id": "strategy-0", "group_index": 0,
                "product_path_selection_id": "products-a",
                "strategy_configuration_id": "config-a",
            }],
            "engine_result": {"portfolios": {"strategy-0": {
                "position_curve": {
                    "2024-01-01T00:00:00+00:00": {"CU.SHF": 1.0},
                    "2024-01-02T00:00:00+00:00": {"CU.SHF": 1.0},
                    "2024-01-03T00:00:00+00:00": {"AL.SHF": 1.0},
                },
                "notional_curve": {
                    "2024-01-01T00:00:00+00:00": {"CU.SHF": 100.0},
                    "2024-01-02T00:00:00+00:00": {"CU.SHF": 100.0},
                    "2024-01-03T00:00:00+00:00": {"AL.SHF": 100.0},
                },
                "fill_turnover": {"average": 0.25, "observations": 2},
            }}},
        },
        {
            "groups": [{
                "strategy_id": "strategy-0", "metrics_key": "strategy-0",
                "timestamps": [1704067200000, 1704153600000, 1704240000000],
                "total_equity": [100.0, 102.0, 101.0],
            }],
            "metrics": {"strategy-0": {"Total Return": 0.01}},
        },
    )

    bundle = build_strategy_analysis_bundle(source, {"strategy_id": "strategy-0"})

    assert set(bundle) == STRATEGY_ANALYSIS_TABS
    assert all(isinstance(bundle[tab], dict) and bundle[tab] for tab in STRATEGY_ANALYSIS_TABS)
    assert bundle["overview"]["summary"]["Total Return"] == 0.01
    assert bundle["returns"]["return_series"][-1]["cumulative_return"] == pytest.approx(1.01)
    assert bundle["membership"]["entry_frequency"]
    assert bundle["products"]["product_analysis"]["rows"]
    assert bundle["tradability"]["tradability_analysis"]["avg_trade_notional_ratio"] == 0.25


def test_strategy_ranking_uses_configuration_and_product_selection():
    source = build_strategy_analysis_source(
        {
            "group_owner": [
                {
                    "strategy_id": "strategy-0", "group_index": 0,
                    "product_path_selection_id": "products-a",
                    "strategy_configuration_id": "config-a",
                },
                {
                    "strategy_id": "strategy-1", "group_index": 1,
                    "product_path_selection_id": "products-a",
                    "strategy_configuration_id": "config-a",
                },
                {
                    "strategy_id": "strategy-other", "group_index": 0,
                    "product_path_selection_id": "products-b",
                    "strategy_configuration_id": "config-a",
                },
            ],
            "engine_result": {"portfolios": {
                "strategy-0": {"equity_curve": {
                    "2024-01-01": 100.0, "2024-01-02": 102.0,
                }},
                "strategy-1": {"equity_curve": {
                    "2024-01-01": 100.0, "2024-01-02": 99.0,
                }},
                "strategy-other": {"equity_curve": {
                    "2024-01-01": 100.0, "2024-01-02": 120.0,
                }},
            }},
        },
        {
            "groups": [
                {"strategy_id": "strategy-0", "timestamps": [1704067200000, 1704153600000], "total_equity": [100.0, 102.0]},
                {"strategy_id": "strategy-1", "timestamps": [1704067200000, 1704153600000], "total_equity": [100.0, 99.0]},
                {"strategy_id": "strategy-other", "timestamps": [1704067200000, 1704153600000], "total_equity": [100.0, 120.0]},
            ],
            "metrics": {},
        },
    )

    result = build_strategy_analysis_tab(source, {
        "analysis_tab": "ranking",
        "strategy_configuration_id": "config-a",
        "product_path_selection_id": "products-a",
    })

    assert result["comparable_period_count"] == 2
    assert result["top_bottom"]["mean_spread"] == pytest.approx(0.015)
