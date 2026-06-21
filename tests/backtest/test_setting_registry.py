from __future__ import annotations

import pytest
from flask import Flask

from server.modules.single_factor_test import sft_bp
from tools.backtest.settings import backtest_setting_registry, resolve_group_settings


def test_setting_manifest_loads_tabs_before_tab_controls() -> None:
    application = backtest_setting_registry.get("group_test")

    index = application.manifest()
    engine_tab = application.tab_manifest("engine")

    assert "settings" not in index
    assert [tab["key"] for tab in index["tab_lists"]["local-settings"]] == [
        "engine", "capital", "allocation", "rebalance", "cost", "liquidity", "market_rules",
    ]
    assert index["default_mounted_tabs"] == {
        "local-settings": ["engine"],
        "group-settings": [],
    }
    assert [tab["key"] for tab in index["tab_lists"]["group-settings"]] == [
        "capital", "allocation", "rebalance", "cost", "liquidity",
    ]
    assert index["defaults"]["engine"] == {
        "value": "native",
        "tab_key": "engine",
        "scope_policy": "local_only",
    }
    assert [setting["key"] for setting in engine_tab["settings"]] == [
        "engine", "factor_mode",
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
    assert len(tab.get_json()["settings"]) == 2
    assert missing.status_code == 404


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
            "rebalance_mode": "on_factor_signal",
            "fee_mode": "market",
            "liquidity_mode": "volume_participation",
            "participation_rate": 0.1,
            "market_rule_fallback": "latest_available",
        },
        group_values={
            "combination-a:group-1": {
            },
            "combination-b:group-1": {
                "rebalance_mode": "buy_and_hold",
                "fee_mode": "none",
                "liquidity_mode": "infinite",
                "participation_rate": 1.0,
            },
        },
        group_ids=("combination-a:group-1", "combination-b:group-1"),
    )

    assert resolved["combination-a:group-1"]["rebalance_mode"] == "on_factor_signal"
    assert resolved["combination-b:group-1"]["rebalance_mode"] == "buy_and_hold"
    assert resolved["combination-a:group-1"]["initial_capital"] == 1_000_000.0


def test_local_only_setting_cannot_be_overridden_by_group() -> None:
    application = backtest_setting_registry.get("group_test")

    with pytest.raises(ValueError, match="local-only setting engine"):
        resolve_group_settings(
            application,
            local_values={},
            group_values={"group-1": {"engine": "backtrader"}},
            group_ids=("group-1",),
        )
