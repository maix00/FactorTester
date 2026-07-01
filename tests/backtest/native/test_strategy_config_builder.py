from __future__ import annotations

import pytest

from tools.testers.backtest.engines.native.ledger import BacktestRunState
from tools.testers.backtest.engines.native.strategy_config_builder import (
    apply_strategy_configs, build_strategy_configs,
)
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule
from tools.testers.backtest.modules.engine import EngineModule

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
    assert config.get(FeeModule.fixed_fee_rate) == 0.001
    assert config.get(EngineModule.engine_mode) == "custom"
    assert config.get(TradingRuleModule.accounting_mode) == "Custom"
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
    assert by_alias["A1"].get(FeeModule.fixed_fee_rate) == 0.001
    assert by_alias["A2"].get(FeeModule.fixed_fee_rate) == 0.002


def test_factor_mode_incremental_activates_signal_live_not_precomputed():
    configs = build_strategy_configs({"A1": {"factor_mode": "incremental", **_GROUP_FIELDS}})
    config = next(iter(configs.values()))
    assert config.uses_flow("signal_live")
    assert config.uses_flow("schedule_bar_events")
    assert not config.uses_flow("signal_precomputed")


def test_factor_mode_precomputed_activates_signal_precomputed_not_live():
    configs = build_strategy_configs({"A1": {"factor_mode": "precomputed", **_GROUP_FIELDS}})
    config = next(iter(configs.values()))
    assert config.uses_flow("signal_precomputed")
    assert not config.uses_flow("signal_live")
    assert not config.uses_flow("schedule_bar_events")


def test_factor_mode_auto_defaults_to_signal_precomputed():
    configs = build_strategy_configs({"A1": {"factor_mode": "auto", **_GROUP_FIELDS}})
    config = next(iter(configs.values()))
    assert config.uses_flow("signal_precomputed")
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
    assert config.uses_flow("initialize_ledgers")


def test_apply_strategy_configs_sets_account_attribute():
    account = BacktestRunState()
    apply_strategy_configs(account, {"A1": {"fixed_fee_rate": 0.001, **_GROUP_FIELDS}})
    assert len(account.strategy_configs) == 1
    strategy = next(iter(account.strategy_configs))
    assert account.strategy_configs[strategy].get(FeeModule.fixed_fee_rate) == 0.001


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
    assert config.get(FeeModule.fixed_fee_rate) == 0.0
