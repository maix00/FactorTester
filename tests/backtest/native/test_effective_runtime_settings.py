from __future__ import annotations

from types import SimpleNamespace

from tools.testers.backtest.engines.native.config import ledger_config_from_mapping
from tools.testers.backtest.engines.native.effective_settings import (
    build_effective_runtime_settings,
)
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy_config_builder import (
    apply_strategy_configs,
)
from tools.testers.backtest.modules.market_data import (
    _historical_field_policy_for_engine,
    _transaction_fee_source_for_ledger_config,
)
from tools.testers.backtest.modules.minor_unit import resolve_use_minor_units
from tools.testers.settings import backtest_setting_registry, resolve_group_settings


_GROUP_FIELDS = {"split_count": 5, "group_index": 1}


def _resolve(local_values: dict) -> dict:
    application = backtest_setting_registry.get("group_test")
    return resolve_group_settings(
        application,
        local_values=local_values,
        group_values={"group-1": {}},
        group_ids=("group-1",),
    )["group-1"]


def test_runtime_inferred_fields_have_neutral_defaults() -> None:
    resolved = _resolve({"engine": "native", "engine_mode": "auto"})

    assert resolved["cost_basis_method"] == "auto"
    assert resolved["daily_mark_to_market_enabled"] == "auto"
    assert resolved["use_int_position"] == "auto"

    basic = _resolve({"engine": "native", "engine_mode": "basic"})
    assert basic["cost_basis_method"] == "WeightAverage"
    assert basic["daily_mark_to_market_enabled"] == "false"
    assert basic["use_int_position"] == "false"


def test_all_runtime_inferred_selectors_have_neutral_registered_defaults() -> None:
    """Every setting resolved from engine/market data keeps intent as its default.

    Concrete business-policy defaults (for example order type and initial
    capital) are intentionally not in this contract.  This list covers the
    selectors whose effective value is chosen later by the engine, market
    rule fields, data-source coverage, or a counterparty/ledger policy.
    """
    application = backtest_setting_registry.get("group_test")
    expected = {
        "engine_mode": "auto",
        "factor_mode": "auto",
        "warmup_mode": "auto",
        "calendar_frequency": "auto",
        "data_source_mode": "auto",
        "freq_mode": "auto",
        "matching_model": "auto",
        "fee_mode": "auto",
        "transaction_fee_source": "auto",
        "margin_mode": "auto",
        "margin_call_mode": "auto",
        "accounting_mode": "Auto",
        "cost_basis_method": "auto",
        "daily_mark_to_market_enabled": "auto",
        "use_int_position": "auto",
        "use_minor_units": "auto",
        "historical_field_policy": "auto",
    }

    assert {
        key: application.settings[key].default
        for key in expected
    } == expected

    resolved = _resolve({"engine": "native", "engine_mode": "auto"})
    assert {key: resolved[key] for key in expected} == expected


def test_ledger_config_does_not_turn_auto_into_true() -> None:
    config = ledger_config_from_mapping({
        "daily_mark_to_market_enabled": "auto",
        "use_int_position": "auto",
    })

    assert config.daily_mark_to_market_enabled is None
    assert config.use_int_position is None


def test_runtime_inferred_policy_values_are_resolved_from_auto() -> None:
    state = BacktestRunState()
    apply_strategy_configs(
        state,
        {"A1": {"engine_mode": "auto", **_GROUP_FIELDS}},
    )
    strategy = next(iter(state.strategy_configs))
    config = state.config_for(strategy)
    ledger = state.ledger_for_strategy(strategy)
    ledger_config = state.ledger_config_for(ledger)

    assert _historical_field_policy_for_engine(state, "auto") == "latest_available"
    assert _transaction_fee_source_for_ledger_config(ledger_config) == "exchange"
    assert resolve_use_minor_units(config) is True

    exact = BacktestRunState()
    apply_strategy_configs(
        exact,
        {"A1": {"engine_mode": "exact", **_GROUP_FIELDS}},
    )
    assert _historical_field_policy_for_engine(exact, "auto") == "strict_historical"


def test_effective_manifest_uses_the_loaded_market_rule_snapshot() -> None:
    product = SimpleNamespace(name="CN.TEST")
    state = BacktestRunState()
    apply_strategy_configs(
        state,
        {"A1": {"engine_mode": "auto", **_GROUP_FIELDS}},
    )
    state.market_data_store.load_plan = [
        (product, SimpleNamespace(name="MIN1"), SimpleNamespace(key="LocalCNFutures")),
    ]
    state.market_data_store.field_state_store = {
        "CN.TEST": {
            "CostBasisMethod": "DailyMarkToMarket",
            "LongMarginRatioByMoney": 0.12,
            "ShortMarginRatioByMoney": 0.14,
            "VolumeMultiple": 10,
            "SettlementPrice": 100,
        },
    }

    manifest = build_effective_runtime_settings(
        state,
        settings_by_strategy={"A1": {"engine_mode": "auto"}},
        products=[product],
    )
    strategy = manifest["strategies"]["A1"]["effective"]
    ledger = manifest["ledgers"]["private:A1"]["effective"]
    product_values = manifest["ledgers"]["private:A1"]["products"]["CN.TEST"]
    effective = product_values["by_ledger"]["private:A1"]

    assert strategy["factor_mode"] == "precomputed"
    assert strategy["historical_field_policy"] == "latest_available"
    assert strategy["transaction_fee_source"] == "exchange"
    assert ledger["transaction_fee_source"] == "exchange"
    assert strategy["use_int_position"] is True
    assert strategy["use_minor_units"] is True
    assert effective["cost_basis_method"] == "FIFO"
    assert effective["daily_mark_to_market_enabled"] is True
    assert effective["margin_accounting"] is True
    assert effective["market_margin_ratio"] == 0.12
