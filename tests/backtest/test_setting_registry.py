from __future__ import annotations

import pytest
from flask import Flask
import pandas as pd

from server.modules.single_factor_test import sft_bp
from tools.backtest.settings import backtest_setting_registry, resolve_group_settings


def test_setting_manifest_loads_tabs_before_tab_controls() -> None:
    application = backtest_setting_registry.get("group_test")

    index = application.manifest()
    engine_tab = application.tab_manifest("engine")

    assert "settings" not in index
    assert [tab["key"] for tab in index["tab_lists"]["local-settings"]] == [
        "engine", "factor", "time", "capital", "target_allocation", "rebalance_trigger", "position_policy", "cost",
        "order", "liquidity", "margin", "market_rules", "accounting", "calendar", "evaluation",
    ]
    assert index["default_mounted_tabs"] == {
        "local-settings": ["engine"],
        "group-settings": [],
    }
    assert [tab["key"] for tab in index["tab_lists"]["group-settings"]] == [
        "capital", "target_allocation", "rebalance_trigger", "position_policy", "cost", "order", "liquidity", "margin",
    ]
    assert index["defaults"]["engine"]["value"] == "native"
    assert index["defaults"]["engine"]["tab_key"] == "engine"
    assert index["defaults"]["engine"]["scope_policy"] == "local_only"
    assert index["defaults"]["engine"]["chip_template"] == "引擎: {value}"
    assert index["defaults"]["engine"]["options"][0] == {
        "value": "native",
        "label": "Native 事件驱动回测工具",
    }
    assert index["defaults"]["order_type"]["value"] == "market"
    assert index["defaults"]["matching_model"]["value"] == "next_bar_full_fill"
    assert index["defaults"]["quantity_rounding_policy"]["value"] == "floor_to_lot"
    assert index["defaults"]["volatility_lookback"]["visible_when"] == {
        "allocation_policy": ["inverse_volatility"],
    }
    assert index["defaults"]["volatility_warmup"]["visible_when"] == {
        "allocation_policy": ["inverse_volatility"],
    }
    assert index["defaults"]["custom_fee_rate"]["visible_when"] == {
        "fee_mode": ["custom"],
    }
    assert index["defaults"]["slippage_bps"]["visible_when"] == {
        "slippage_mode": ["fixed_bps"],
    }
    assert index["defaults"]["participation_rate"]["visible_when"] == {
        "liquidity_mode": ["volume_participation"],
    }
    assert index["defaults"]["collateral_fraction"]["visible_when"] == {
        "margin_mode": ["market"],
    }
    assert index["defaults"]["money_unit_policy"]["value"] == "minor_units"
    assert index["defaults"]["money_unit_policy"]["engine_defaults"] == {
        "qlib": "engine_native",
        "rqalpha": "engine_native",
    }
    assert index["defaults"]["money_unit_policy"]["disabled_values_by_engine"] == {
        "qlib": ["minor_units"],
        "rqalpha": ["minor_units"],
    }
    assert all(item.get("module") for item in index["defaults"].values())
    assert all(chip.get("module") for chip in index["chip_fields"])
    assert {
        chip["module"] for chip in index["chip_fields"]
    } >= {"factor_execution", "product_selection", "group_strategy"}
    assert {chip["key"] for chip in index["chip_fields"]} >= {
        "factor_alias",
        "tester",
        "group_index",
        "product_mask",
    }
    assert [setting["key"] for setting in engine_tab["settings"]] == [
        "engine",
    ]


def test_setting_routes_reject_unknown_tabs_instead_of_falling_back() -> None:
    app = Flask(__name__)
    app.register_blueprint(sft_bp)
    client = app.test_client()

    index = client.get("/api/backtest/settings/group_test")
    tab = client.get("/api/backtest/settings/group_test/tabs/engine")
    missing = client.get("/api/backtest/settings/group_test/tabs/legacy")

    assert index.status_code == 200
    assert "settings" not in index.get_json()
    assert tab.status_code == 200
    assert len(tab.get_json()["settings"]) == 1
    assert missing.status_code == 404


def test_setting_manifest_uses_page_exact_time_as_run_default(monkeypatch) -> None:
    from server.modules.single_factor_test import backtest_settings as routes
    from tools.data.types import DataTime

    app = Flask(__name__)
    app.register_blueprint(sft_bp)
    monkeypatch.setattr(
        routes.page_runtime,
        "get_current_time",
        lambda page_uuid: (
            DataTime(pd.Timestamp("2024-01-02 09:01", tz="Asia/Shanghai")),
            DataTime(pd.Timestamp("2026-05-31 15:00", tz="Asia/Shanghai")),
            None,
        ),
    )

    payload = app.test_client().get(
        "/api/backtest/settings/group_test?page_uuid=page-1"
    ).get_json()

    assert payload["defaults"]["start_date"]["value"] == "2024-01-02"
    assert payload["defaults"]["start_time"]["value"] == "09:01"
    assert payload["defaults"]["end_date"]["value"] == "2026-05-31"
    assert payload["defaults"]["end_time"]["value"] == "15:00"


def test_setting_index_is_a_real_lazy_loading_boundary() -> None:
    app = Flask(__name__)
    app.register_blueprint(sft_bp)
    payload = app.test_client().get("/api/backtest/settings/group_test").get_json()

    assert payload["tab_url_template"].endswith("/tabs/{tab_key}")
    assert all(
        "settings" not in tab
        for tabs in payload["tab_lists"].values()
        for tab in tabs
    )
    assert "settings" not in payload


def test_group_settings_override_local_values_for_each_combination() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={
            "engine": "native",
            "factor_mode": "auto",
            "initial_capital": 1_000_000.0,
            "allocation_policy": "inverse_volatility",
            "volatility_lookback": 20,
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
            "fee_mode": "market",
            "liquidity_mode": "volume_participation",
            "participation_rate": 0.1,
            "market_rule_fallback": "latest_available",
        },
        group_values={
            "combination-a:group-1": {
            },
            "combination-b:group-1": {
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "buy_and_hold",
                "fee_mode": "none",
                "liquidity_mode": "infinite",
                "participation_rate": 1.0,
            },
        },
        group_ids=("combination-a:group-1", "combination-b:group-1"),
    )

    assert resolved["combination-a:group-1"]["rebalance_trigger"] == "on_factor_signal"
    assert resolved["combination-b:group-1"]["rebalance_trigger"] == "on_factor_signal"
    assert resolved["combination-b:group-1"]["position_policy"] == "buy_and_hold"
    assert resolved["combination-a:group-1"]["initial_capital"] == 1_000_000.0


def test_local_only_group_override_falls_back_with_diagnostics() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={"engine": "native"},
        group_values={"group-1": {"engine": "backtrader"}},
        group_ids=("group-1",),
    )

    assert resolved["group-1"]["engine"] == "native"
    assert resolved["group-1"]["_setting_fallbacks"] == [{
        "setting_key": "engine",
        "module": "execution_engine",
        "engine": "native",
        "requested_value": "backtrader",
        "applied_value": "native",
        "reason": "local_only_group_override",
    }]


def test_numeric_setting_strings_are_normalized() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={},
        group_values={"group-1": {"initial_capital": "123456.5"}},
        group_ids=("group-1",),
    )

    assert resolved["group-1"]["initial_capital"] == 123456.5
    assert "_setting_fallbacks" not in resolved["group-1"]


def test_invalid_numeric_setting_falls_back_with_diagnostics() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={},
        group_values={"group-1": {"initial_capital": ""}},
        group_ids=("group-1",),
    )

    assert resolved["group-1"]["initial_capital"] == 100_000_000.0
    assert resolved["group-1"]["_setting_fallbacks"] == [{
        "setting_key": "initial_capital",
        "module": "portfolio_capital",
        "engine": "native",
        "requested_value": "",
        "applied_value": 100_000_000.0,
        "reason": "invalid_setting_value",
    }]


def test_engine_owned_default_replaces_disabled_money_unit_policy() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={"engine": "qlib"},
        group_values={"group-1": {}},
        group_ids=("group-1",),
    )

    assert resolved["group-1"]["money_unit_policy"] == "engine_native"


def test_disabled_engine_setting_falls_back_with_diagnostics() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={"engine": "qlib", "money_unit_policy": "minor_units"},
        group_values={"group-1": {}},
        group_ids=("group-1",),
    )

    assert resolved["group-1"]["money_unit_policy"] == "engine_native"
    assert resolved["group-1"]["_setting_fallbacks"] == [{
        "setting_key": "money_unit_policy",
        "module": "accounting",
        "engine": "qlib",
        "requested_value": "minor_units",
        "applied_value": "engine_native",
        "reason": "engine_disabled_value",
    }]
