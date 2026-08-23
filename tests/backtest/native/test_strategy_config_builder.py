from __future__ import annotations

import pytest

from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy_config_builder import (
    apply_strategy_configs, build_strategy_configs,
)
from tools.testers.backtest.modules.cash_pool import cash_pool_store_for
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.strategy_book import StrategyBook
from tools.testers.backtest.modules.target import TargetStrategyModule
from tools.testers.backtest.modules.threshold_signal import ThresholdSignalModule

# GroupMembershipModule's core Flows are unconditionally active for every
# strategy this round (no second SignalToOrderModule exists yet to opt out
# into), so split_count/group_index -- both frontend_only_default=True --
# must be supplied explicitly in every payload below, or build_strategy_configs
# raises (see test_missing_frontend_only_default_field_raises).
_GROUP_FIELDS = {"split_count": 5, "group_index": 1}


def test_resolved_settings_map_to_matching_field_refs():
    configs = build_strategy_configs({
        "A1": {"fixed_fee_rate": 0.001, "engine_mode": "custom", "accounting_mode": "Custom", **_GROUP_FIELDS},
    })
    strategy = next(iter(configs))
    config = configs[strategy]
    assert config.get(FeeModule.fixed_fee_rate) is None
    assert config.get(EngineModule.engine_mode) == "custom"
    assert config.get(TradingRuleModule.accounting_mode) is None
    assert config.get(GroupMembershipModule.split_count) == 5


def test_unknown_settings_keys_are_ignored_not_errored():
    configs = build_strategy_configs({"A1": {"some_unrelated_old_key": 123, **_GROUP_FIELDS}})
    strategy = next(iter(configs))
    field_values = configs[strategy].field_values
    assert configs[strategy].get(GroupMembershipModule.split_count) == 5
    assert not any(ref.name == "some_unrelated_old_key" for ref in field_values)


def test_strategy_alias_becomes_strategy_name_prefix():
    configs = build_strategy_configs({"GroupA1": _GROUP_FIELDS})
    strategy = next(iter(configs))
    assert strategy.name.startswith("GroupA1:")


def test_two_strategies_get_independent_configs():
    configs = build_strategy_configs({
        "A1": {"fixed_fee_rate": 0.001, **_GROUP_FIELDS},
        "A2": {"fixed_fee_rate": 0.002, **_GROUP_FIELDS},
    })
    by_alias = {s.alias: c for s, c in configs.items()}
    assert by_alias["A1"].get(FeeModule.fixed_fee_rate) is None
    assert by_alias["A2"].get(FeeModule.fixed_fee_rate) is None


def test_factor_mode_incremental_activates_signal_live_not_precomputed():
    configs = build_strategy_configs({"A1": {"factor_mode": "incremental", **_GROUP_FIELDS}})
    config = next(iter(configs.values()))
    assert config.uses_flow("signal_live")
    assert config.uses_flow("schedule_bar_events")
    assert not config.uses_flow("signal_precomputed")
    assert not config.uses_flow("precompute_strategy_intents")


def test_factor_mode_precomputed_activates_signal_precomputed_not_live():
    configs = build_strategy_configs({"A1": {"factor_mode": "precomputed", **_GROUP_FIELDS}})
    config = next(iter(configs.values()))
    assert config.uses_flow("signal_precomputed")
    assert config.uses_flow("precompute_strategy_intents")
    assert not config.uses_flow("signal_live")
    assert not config.uses_flow("schedule_bar_events")


def test_factor_mode_auto_defaults_to_signal_precomputed():
    configs = build_strategy_configs({"A1": {"factor_mode": "auto", **_GROUP_FIELDS}})
    config = next(iter(configs.values()))
    assert config.uses_flow("signal_precomputed")
    assert config.uses_flow("precompute_strategy_intents")
    assert not config.uses_flow("signal_live")
    assert not config.uses_flow("schedule_bar_events")


def test_engine_mode_basic_disables_term_structure_lifecycle_flows():
    configs = build_strategy_configs({"A1": {"engine_mode": "basic", **_GROUP_FIELDS}})
    config = next(iter(configs.values()))
    assert not config.uses_flow("expand_term_structure")
    assert not config.uses_flow("resolve_tradable_target_weights")
    assert not config.uses_flow("register_force_close_notices")
    assert not config.uses_flow("register_rollover_notices")
    assert not config.uses_flow("handle_delivery_force_close_notice")
    assert not config.uses_flow("handle_rollover_notice")


def test_engine_mode_auto_keeps_term_structure_lifecycle_flows_available():
    configs = build_strategy_configs({"A1": {"engine_mode": "auto", **_GROUP_FIELDS}})
    config = next(iter(configs.values()))
    assert config.uses_flow("expand_term_structure")
    assert config.uses_flow("resolve_tradable_target_weights")
    assert config.uses_flow("register_force_close_notices")
    assert config.uses_flow("register_rollover_notices")


def test_factor_mode_auto_uses_live_for_non_vectorizable_factor():
    class LiveOnlyFactor:
        supports_vectorized = False

    configs = build_strategy_configs({
        "A1": {"factor_mode": "auto", "factor": LiveOnlyFactor(), **_GROUP_FIELDS},
    })
    config = next(iter(configs.values()))
    assert config.uses_flow("signal_live")
    assert config.uses_flow("schedule_bar_events")
    assert not config.uses_flow("signal_precomputed")


def test_factor_mode_precomputed_rejects_non_vectorizable_factor():
    class LiveOnlyFactor:
        supports_vectorized = False

    with pytest.raises(ValueError, match="vectorizable"):
        build_strategy_configs({
            "A1": {"factor_mode": "precomputed", "factor": LiveOnlyFactor(), **_GROUP_FIELDS},
        })


def test_factor_mode_incremental_rejects_non_incremental_factor():
    class NotIncrementalFactor:
        supports_incremental = False

    with pytest.raises(ValueError, match="incrementally"):
        build_strategy_configs({
            "A1": {"factor_mode": "incremental", "factor": NotIncrementalFactor(), **_GROUP_FIELDS},
        })


def test_non_variant_flows_are_always_active():
    configs = build_strategy_configs({"A1": _GROUP_FIELDS})
    config = next(iter(configs.values()))
    assert config.uses_flow("group_quantile_membership")
    assert not config.uses_flow("threshold_signal_target")
    assert config.uses_flow("initialize_ledgers")


def test_threshold_strategy_activates_threshold_flow_without_group_defaults():
    configs = build_strategy_configs({
        "T1": {
            "strategy_intent_mode": "threshold",
            "threshold_mode": "absolute",
            "entry_threshold": 0.5,
            "exit_threshold": 0.2,
            "side_mode": "long_only",
        },
    })
    config = next(iter(configs.values()))
    assert config.get(TargetStrategyModule.strategy_kind) == "threshold"
    assert config.get(ThresholdSignalModule.entry_threshold) == 0.5
    assert config.uses_flow("threshold_signal_target")
    assert config.uses_flow("precompute_strategy_intents")
    assert not config.uses_flow("group_quantile_membership")


def test_threshold_strategy_kind_alias_materializes_target_strategy_kind():
    configs = build_strategy_configs({
        "T1": {
            "strategy_kind": "threshold",
            "threshold_mode": "absolute",
            "entry_threshold": 0.5,
            "exit_threshold": 0.2,
            "side_mode": "long_only",
        },
    })
    config = next(iter(configs.values()))
    assert config.get(TargetStrategyModule.strategy_kind) == "threshold"
    assert config.uses_flow("threshold_signal_target")
    assert not config.uses_flow("group_quantile_membership")


def test_long_short_strategy_does_not_require_group_membership_fields():
    configs = build_strategy_configs({
        "LS A1/A5": {
            "strategy_kind": "long_short",
            "long_leg_strategy_ids": [{"strategy_id": "A1"}],
            "short_leg_strategy_ids": [{"strategy_id": "A5"}],
        },
    })
    config = next(iter(configs.values()))
    assert config.uses_flow("compose_long_short_target")
    assert not config.uses_flow("group_quantile_membership")
    assert not config.uses_flow("precompute_strategy_intents")


def test_daily_mark_to_market_flow_gating_by_engine_and_custom_field():
    auto = next(iter(build_strategy_configs({"A1": {"engine_mode": "auto", **_GROUP_FIELDS}}).values()))
    custom_engine_auto_accounting = next(iter(build_strategy_configs({
        "A1": {
            "engine_mode": "custom",
            "accounting_mode": "Auto",
            "daily_mark_to_market_enabled": False,
            "margin_mode": "auto",
            **_GROUP_FIELDS,
        },
    }).values()))
    exact = next(iter(build_strategy_configs({"A1": {"engine_mode": "exact", **_GROUP_FIELDS}}).values()))
    basic = next(iter(build_strategy_configs({"A1": {"engine_mode": "basic", **_GROUP_FIELDS}}).values()))
    custom_off = next(iter(build_strategy_configs({
        "A1": {
            "engine_mode": "custom",
            "accounting_mode": "Custom",
            "cost_basis_method": "FIFO",
            "daily_mark_to_market_enabled": False,
            **_GROUP_FIELDS,
        },
    }).values()))
    custom_on = next(iter(build_strategy_configs({
        "A1": {
            "engine_mode": "custom",
            "accounting_mode": "Custom",
            "cost_basis_method": "FIFO",
            "daily_mark_to_market_enabled": True,
            **_GROUP_FIELDS,
        },
    }).values()))

    for config in (auto, custom_engine_auto_accounting, exact, custom_on):
        assert config.uses_flow("register_daily_mark_to_market_notices")
        assert config.uses_flow("apply_daily_mark_to_market")
    for config in (basic, custom_off):
        assert not config.uses_flow("register_daily_mark_to_market_notices")
        assert not config.uses_flow("apply_daily_mark_to_market")


def test_ledger_daily_mark_to_market_disabled_removes_dmtm_and_ledger_lookup_flows():
    account = BacktestRunState()

    apply_strategy_configs(
        account,
        {"A1": {"engine_mode": "auto", **_GROUP_FIELDS}},
        ledger_configs={"private:A1": {"daily_mark_to_market_enabled": False, "margin_mode": "none"}},
    )

    config = next(iter(account.strategy_configs.values()))
    assert not config.uses_flow("register_daily_mark_to_market_notices")
    assert not config.uses_flow("apply_daily_mark_to_market")
    assert not config.uses_flow("lookup_current_prices_on_ledger")
    assert not config.uses_flow("lookup_historical_fields_on_ledger")


def test_margin_mode_off_ignores_margin_call_and_disables_ledger_flows():
    account = BacktestRunState()

    apply_strategy_configs(
        account,
        {
            "A1": {
                "engine_mode": "auto",
                "margin_mode": "off",
                "margin_call_mode": "liquidate",
                **_GROUP_FIELDS,
            }
        },
    )

    config = next(iter(account.strategy_configs.values()))
    strategy = next(iter(account.strategy_configs))
    ledger_config = account.ledger_config_for(f"private:{strategy.alias}")
    assert ledger_config.margin_mode == "off"
    assert ledger_config.margin_call_mode is None
    assert not config.uses_flow("register_daily_mark_to_market_notices")
    assert not config.uses_flow("apply_daily_mark_to_market")
    assert not config.uses_flow("register_margin_check_notices")
    assert not config.uses_flow("lookup_current_prices_on_ledger")
    assert not config.uses_flow("lookup_historical_fields_on_ledger")


def test_fixed_fee_rate_without_fixed_fee_mode_raises():
    account = BacktestRunState()

    with pytest.raises(ValueError, match="fixed_fee_rate"):
        apply_strategy_configs(account, {"A1": {"fixed_fee_rate": 0.001, **_GROUP_FIELDS}})


def test_fixed_margin_ratio_without_fixed_margin_mode_raises():
    account = BacktestRunState()

    with pytest.raises(ValueError, match="fixed_margin_ratio"):
        apply_strategy_configs(account, {"A1": {"fixed_margin_ratio": 0.2, **_GROUP_FIELDS}})


def test_margin_budget_rejects_target_above_hard_limit() -> None:
    account = BacktestRunState()

    with pytest.raises(ValueError, match="target <= max"):
        apply_strategy_configs(account, {"A1": {
            "target_margin_utilization": 0.90,
            "max_margin_utilization": 0.85,
            **_GROUP_FIELDS,
        }})


def test_apply_strategy_configs_uses_strategy_book_cash_pool_config():
    account = BacktestRunState()
    book = StrategyBook.from_dict({
        "strategies": {"A1": "book-a"},
        "cash_pools": {"book-a": "pool-main"},
        "cash_pool_configs": {
            "pool-main": {
                "initial_capital_major": 2_500_000.0,
                "base_currency": "USD",
                "currency_conversion_fee_rate": 0.0002,
                "target_margin_utilization": 0.75,
                "max_margin_utilization": 0.82,
                "margin_utilization_tolerance": 0.005,
            },
        },
    })
    apply_strategy_configs(
        account,
        {"A1": {"engine_mode": "custom", "margin_mode": "none", **_GROUP_FIELDS}},
        strategy_book=book,
    )

    config = cash_pool_store_for(account).config_by_pool["pool-main"]
    assert config.initial_capital_major == 2_500_000.0
    assert config.base_currency == "USD"
    assert config.currency_conversion_fee_rate == 0.0002
    assert config.target_margin_utilization == 0.75
    assert config.max_margin_utilization == 0.82
    assert config.margin_utilization_tolerance == 0.005


def test_apply_strategy_configs_keeps_account_currency_separate_from_pool_base_currency():
    account = BacktestRunState()
    book = StrategyBook.from_dict({
        "strategies": {"A1": "usd-account"},
        "cash_pools": {"usd-account": "pool-main"},
        "cash_pool_configs": {
            "pool-main": {"initial_capital_major": 1_000_000.0, "base_currency": "CNY"},
        },
    })

    apply_strategy_configs(
        account,
        {"A1": {
            "engine_mode": "custom", "margin_mode": "none",
            "account_currency": "USD", **_GROUP_FIELDS,
        }},
        strategy_book=book,
    )

    assert account.ledger_config_for("usd-account").account_currency == "USD"
    assert cash_pool_store_for(account).config_by_pool["pool-main"].base_currency == "CNY"


def test_auto_daily_mark_to_market_is_not_materialized_as_ledger_default():
    account = BacktestRunState()
    apply_strategy_configs(account, {"A1": {"engine_mode": "auto", **_GROUP_FIELDS}})

    strategy = next(iter(account.strategy_configs))
    ledger_config = account.ledger_config_for(f"private:{strategy.alias}")

    assert ledger_config.accounting_mode == "Auto"
    assert ledger_config.daily_mark_to_market_enabled is None


def test_hidden_fixed_fee_and_margin_defaults_are_not_materialized_for_auto_modes():
    account = BacktestRunState()
    apply_strategy_configs(account, {"A1": {"engine_mode": "auto", **_GROUP_FIELDS}})

    strategy = next(iter(account.strategy_configs))
    ledger_config = account.ledger_config_for(f"private:{strategy.alias}")

    assert ledger_config.fee_mode == "auto"
    assert ledger_config.fixed_fee_rate is None
    assert ledger_config.margin_mode == "auto"
    assert ledger_config.fixed_margin_ratio is None


def test_hidden_fixed_fee_and_margin_defaults_from_resolved_settings_are_ignored():
    account = BacktestRunState()
    apply_strategy_configs(
        account,
        {
            "A1": {
                "engine_mode": "auto",
                "fee_mode": "auto",
                "fixed_fee_rate": 0.0,
                "margin_mode": "auto",
                "fixed_margin_ratio": 1.0,
                **_GROUP_FIELDS,
            }
        },
    )

    strategy = next(iter(account.strategy_configs))
    ledger_config = account.ledger_config_for(f"private:{strategy.alias}")

    assert ledger_config.fee_mode == "auto"
    assert ledger_config.fixed_fee_rate is None
    assert ledger_config.margin_mode == "auto"
    assert ledger_config.fixed_margin_ratio is None


def test_fixed_fee_and_margin_modes_materialize_their_backend_defaults():
    account = BacktestRunState()
    apply_strategy_configs(
        account,
        {"A1": {"engine_mode": "custom", "fee_mode": "fixed", "margin_mode": "fixed", **_GROUP_FIELDS}},
    )

    strategy = next(iter(account.strategy_configs))
    ledger_config = account.ledger_config_for(f"private:{strategy.alias}")

    assert ledger_config.fee_mode == "fixed"
    assert ledger_config.fixed_fee_rate == 0.0
    assert ledger_config.margin_mode == "fixed"
    assert ledger_config.fixed_margin_ratio == 1.0


def test_missing_frontend_only_default_field_raises():
    """split_count's `default=5` is a UI display suggestion only
    (frontend_only_default=True) -- a strategy that doesn't supply it must
    not silently fall back to that value."""
    with pytest.raises(ValueError, match="split_count"):
        build_strategy_configs({"A1": {"group_index": 1}})


def test_ordinary_field_missing_value_materializes_real_default():
    """fixed_fee_rate (frontend_only_default=False) DOES use its declared
    default as a genuine backend fallback when absent -- unlike split_count."""
    configs = build_strategy_configs({"A1": _GROUP_FIELDS})
    config = next(iter(configs.values()))
    assert config.get(FeeModule.fixed_fee_rate) is None


def test_end_session_skip_defaults_to_false():
    configs = build_strategy_configs({"A1": _GROUP_FIELDS})
    config = next(iter(configs.values()))

    assert config.get(FactorSignalModule.end_session_skip) is False


def test_use_minor_units_preserves_auto_intent_outside_basic_engine_mode():
    from tools.testers.backtest.modules.minor_unit import MinorUnitModule

    for engine_mode in ("auto", "custom", "exact"):
        configs = build_strategy_configs({"A1": {"engine_mode": engine_mode, **_GROUP_FIELDS}})
        config = next(iter(configs.values()))
        assert config.get(MinorUnitModule.use_minor_units) == "auto", engine_mode
    # unset engine_mode resolves to "auto" (EngineModule.engine_mode's own default)
    configs = build_strategy_configs({"A1": _GROUP_FIELDS})
    config = next(iter(configs.values()))
    assert config.get(MinorUnitModule.use_minor_units) == "auto"


def test_use_minor_units_preserves_basic_engine_conditional_intent():
    from tools.testers.backtest.modules.minor_unit import MinorUnitModule

    configs = build_strategy_configs({"A1": {"engine_mode": "basic", **_GROUP_FIELDS}})
    config = next(iter(configs.values()))
    assert config.get(MinorUnitModule.use_minor_units) == "false"


def test_use_minor_units_explicit_value_overrides_the_engine_mode_default():
    from tools.testers.backtest.modules.minor_unit import MinorUnitModule

    configs = build_strategy_configs({
        "A1": {"engine_mode": "basic", "use_minor_units": True, **_GROUP_FIELDS},
    })
    config = next(iter(configs.values()))
    assert config.get(MinorUnitModule.use_minor_units) is True
