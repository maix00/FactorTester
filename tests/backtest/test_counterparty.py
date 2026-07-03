from __future__ import annotations

from tools.testers.backtest.engines.native.strategy_config_builder import build_strategy_configs
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule
from tools.testers.settings.counterparty import (
    CounterPartyProfile,
    apply_counterparty_profile_defaults,
    counterparty_profile,
    register_counterparty_profile,
    unregister_counterparty_profile,
)

# GroupMembershipModule's core Flows are unconditionally active (see
# test_strategy_config_builder.py's _GROUP_FIELDS comment) -- split_count/
# group_index must be supplied in every payload below.
_GROUP_FIELDS = {"split_count": 5, "group_index": 1}


def setup_module() -> None:
    # Idempotent: re-injecting the same default_when entries is harmless,
    # and this guarantees the mechanism is applied regardless of whether
    # some other test module already triggered register_all_module_settings.
    apply_counterparty_profile_defaults()


def test_exchange_base_profile_is_registered_at_import_time():
    profile = counterparty_profile("exchange_base")
    assert profile is not None
    assert profile.label


def test_counterparty_profile_expands_fee_and_margin_defaults():
    configs = build_strategy_configs({
        "A1": {
            "engine_mode": "custom",
            "counterparty_profile": "exchange_base",
            **_GROUP_FIELDS,
        },
    })
    strategy = next(iter(configs))
    config = configs[strategy]
    assert config.get(FeeModule.fee_mode) == "auto"
    assert config.get(MarginModule.margin_mode) == "auto"
    assert config.get(TradingRuleModule.accounting_mode) == "Auto"
    assert config.get(TradingRuleModule.use_int_position) is True


def test_explicit_field_value_wins_over_counterparty_profile():
    configs = build_strategy_configs({
        "A1": {
            "engine_mode": "custom",
            "counterparty_profile": "exchange_base",
            "fee_mode": "fixed",
            **_GROUP_FIELDS,
        },
    })
    strategy = next(iter(configs))
    config = configs[strategy]
    assert config.get(FeeModule.fee_mode) == "fixed"
    # margin_mode still comes from the profile -- only fee_mode was overridden
    assert config.get(MarginModule.margin_mode) == "auto"


def test_no_profile_selected_is_bit_identical_to_current_custom_mode_behavior():
    configs = build_strategy_configs({
        "A1": {"engine_mode": "custom", **_GROUP_FIELDS},
    })
    strategy = next(iter(configs))
    config = configs[strategy]
    # engine_mode=custom with no counterparty_profile and no explicit fee_mode/
    # margin_mode falls back to each field's own bare `default` (unchanged
    # from before this feature existed) -- not the exchange_base profile.
    assert config.get(FeeModule.fee_mode) == "auto"  # FeeModule.fee_mode's own bare default
    assert config.get(MarginModule.margin_mode) == "auto"  # MarginModule.margin_mode's own bare default


def test_engine_mode_basic_auto_exact_presets_unaffected_by_counterparty_profile():
    configs = build_strategy_configs({
        "basic": {"engine_mode": "basic", **_GROUP_FIELDS},
        "auto": {"engine_mode": "auto", **_GROUP_FIELDS},
        "exact": {"engine_mode": "exact", **_GROUP_FIELDS},
    })
    by_alias = {s.alias: s for s in configs}
    assert configs[by_alias["basic"]].get(FeeModule.fee_mode) == "zero"
    assert configs[by_alias["auto"]].get(FeeModule.fee_mode) == "auto"
    assert configs[by_alias["exact"]].get(FeeModule.fee_mode) == "exact"


def test_registering_a_second_profile_does_not_clobber_the_first():
    register_counterparty_profile(CounterPartyProfile(
        id="__test_second_profile__",
        label="测试第二预设",
        field_defaults={FeeModule.fee_mode: "fixed"},
    ))
    apply_counterparty_profile_defaults()
    try:
        configs = build_strategy_configs({
            "first": {"engine_mode": "custom", "counterparty_profile": "exchange_base", **_GROUP_FIELDS},
            "second": {"engine_mode": "custom", "counterparty_profile": "__test_second_profile__", **_GROUP_FIELDS},
        })
        by_alias = {s.alias: s for s in configs}
        assert configs[by_alias["first"]].get(FeeModule.fee_mode) == "auto"
        assert configs[by_alias["second"]].get(FeeModule.fee_mode) == "fixed"
    finally:
        # This registry is process-global mutable state shared with every
        # other test module in the same pytest session -- leaking this
        # test-only profile would corrupt other tests' manifest assertions.
        unregister_counterparty_profile("__test_second_profile__")
