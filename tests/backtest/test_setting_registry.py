from __future__ import annotations

import pytest
from flask import Flask

from server.modules.single_factor_test import sft_bp
from tools.backtest.settings import backtest_setting_registry, resolve_strategy_settings


def test_setting_manifest_loads_tabs_before_tab_controls() -> None:
    application = backtest_setting_registry.get("group_test")

    index = application.manifest()
    engine_tab = application.tab_manifest("engine")

    assert "settings" not in index
    assert [tab["key"] for tab in index["tabs"]] == [
        "engine", "capital", "rebalance", "cost", "liquidity",
    ]
    assert [setting["key"] for setting in engine_tab["settings"]] == [
        "engine", "factor_execution",
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
    assert all("settings" not in tab for tab in payload["tabs"])
    assert "settings" not in payload


def test_selectable_settings_resolve_different_strategy_rules() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_strategy_settings(
        application,
        scopes={
            "initial_capital": "shared",
            "rebalance_mode": "strategy",
            "fee_mode": "strategy",
            "liquidity_mode": "strategy",
            "participation_rate": "strategy",
        },
        shared_values={
            "engine": "native_event",
            "factor_execution": "incremental",
            "initial_capital": 1_000_000.0,
        },
        strategy_values={
            "combination-a:group-1": {
                "rebalance_mode": "each_period",
                "fee_mode": "market",
                "liquidity_mode": "volume_participation",
                "participation_rate": 0.1,
            },
            "combination-b:group-1": {
                "rebalance_mode": "buy_and_hold",
                "fee_mode": "none",
                "liquidity_mode": "infinite",
                "participation_rate": 1.0,
            },
        },
        strategy_ids=("combination-a:group-1", "combination-b:group-1"),
    )

    assert resolved["combination-a:group-1"]["rebalance_mode"] == "each_period"
    assert resolved["combination-b:group-1"]["rebalance_mode"] == "buy_and_hold"
    assert resolved["combination-a:group-1"]["initial_capital"] == 1_000_000.0


def test_shared_setting_cannot_be_overridden_per_strategy() -> None:
    application = backtest_setting_registry.get("group_test")

    with pytest.raises(ValueError, match="shared setting engine"):
        resolve_strategy_settings(
            application,
            scopes={},
            shared_values={},
            strategy_values={"strategy-1": {"engine": "backtrader"}},
            strategy_ids=("strategy-1",),
        )
