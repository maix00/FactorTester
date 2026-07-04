from __future__ import annotations

from tools.testers.backtest.engines.native.ledger import BacktestRunState
from tools.testers.backtest.engines.native.strategy_config_builder import (
    apply_strategy_configs,
    build_strategy_configs,
)
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule
from tools.testers.settings.counterparty import (
    CounterPartyProfile,
    apply_counterparty_profile_defaults,
    apply_counterparty_profiles_to_resolved_settings,
    counterparty_profile,
    register_counterparty_profile,
    resolve_counterparty_profiles_by_ledger,
    unregister_counterparty_profile,
)
from tools.testers.backtest.modules.strategy_book import StrategyBook

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


def test_counterparty_resolves_to_ledger_level_for_shared_strategy_book():
    book = StrategyBook.from_dict({
        "strategies": {
            "A1": "shared-book",
            "A2": "shared-book",
        },
    })
    resolved = resolve_counterparty_profiles_by_ledger(
        {
            "A1": {"counterparty_profile": "exchange_base", **_GROUP_FIELDS},
            "A2": {"counterparty_profile": "exchange_base", **_GROUP_FIELDS},
        },
        strategy_book=book,
    )
    assert resolved == {"shared-book": "exchange_base"}


def test_counterparty_rejects_conflicting_strategy_profiles_on_shared_ledger():
    register_counterparty_profile(CounterPartyProfile(
        id="__test_other_profile__",
        label="测试另一预设",
        field_defaults={FeeModule.fee_mode: "fixed"},
    ))
    try:
        book = StrategyBook.from_dict({
            "strategies": {
                "A1": "shared-book",
                "A2": "shared-book",
            },
        })
        try:
            resolve_counterparty_profiles_by_ledger(
                {
                    "A1": {"counterparty_profile": "exchange_base", **_GROUP_FIELDS},
                    "A2": {"counterparty_profile": "__test_other_profile__", **_GROUP_FIELDS},
                },
                strategy_book=book,
            )
        except ValueError as exc:
            assert "conflicting counterparty profiles" in str(exc)
        else:
            raise AssertionError("expected shared-ledger counterparty conflict")
    finally:
        unregister_counterparty_profile("__test_other_profile__")


def test_counterparty_per_ledger_override_can_resolve_shared_ledger_conflict():
    register_counterparty_profile(CounterPartyProfile(
        id="__test_ledger_override_profile__",
        label="测试账本覆盖预设",
        field_defaults={FeeModule.fee_mode: "fixed"},
    ))
    try:
        book = StrategyBook.from_dict({
            "strategies": {
                "A1": "shared-book",
                "A2": "shared-book",
            },
        })
        resolved = resolve_counterparty_profiles_by_ledger(
            {
                "A1": {**_GROUP_FIELDS},
                "A2": {**_GROUP_FIELDS},
            },
            strategy_book=book,
            counterparty="exchange_base",
            counterparty_by_ledger={"shared-book": "__test_ledger_override_profile__"},
        )
        assert resolved == {"shared-book": "__test_ledger_override_profile__"}
    finally:
        unregister_counterparty_profile("__test_ledger_override_profile__")


def test_counterparty_projection_keeps_strategy_config_builder_compatible():
    settings = apply_counterparty_profiles_to_resolved_settings(
        {
            "A1": {**_GROUP_FIELDS},
            "A2": {**_GROUP_FIELDS},
        },
        counterparty="exchange_base",
    )
    assert settings["A1"]["counterparty_profile"] == "exchange_base"
    assert settings["A2"]["counterparty_profile"] == "exchange_base"
    configs = build_strategy_configs(settings)
    assert {config.get(FeeModule.fee_mode) for config in configs.values()} == {"auto"}


def test_apply_strategy_configs_accepts_strategy_book_and_ledger_counterparty_override():
    register_counterparty_profile(CounterPartyProfile(
        id="__test_bootstrap_profile__",
        label="测试入口预设",
        field_defaults={FeeModule.fee_mode: "fixed"},
    ))
    apply_counterparty_profile_defaults()
    try:
        account = BacktestRunState()
        book = StrategyBook.from_dict({
            "strategies": {
                "A1": "shared-book",
                "A2": "shared-book",
            },
        })
        apply_strategy_configs(
            account,
            {
                "A1": {"engine_mode": "custom", **_GROUP_FIELDS},
                "A2": {"engine_mode": "custom", **_GROUP_FIELDS},
            },
            strategy_book=book,
            counterparty="exchange_base",
            counterparty_by_ledger={"shared-book": "__test_bootstrap_profile__"},
        )
        assert account.strategy_book is book
        assert {config.get(FeeModule.fee_mode) for config in account.strategy_configs.values()} == {"fixed"}
    finally:
        unregister_counterparty_profile("__test_bootstrap_profile__")


def test_apply_strategy_configs_projects_ledger_config_fields():
    account = BacktestRunState()
    book = StrategyBook.from_dict({
        "strategies": {
            "A1": "shared-book",
            "A2": "shared-book",
        },
        "ledgers": {
            "shared-book": {
                "fee_mode": "fixed",
                "margin_mode": "fixed",
                "accounting_mode": "Custom",
                "daily_mark_to_market_enabled": True,
                "cost_basis_method": "FIFO",
            },
        },
    })
    apply_strategy_configs(
        account,
        {
            "A1": {"engine_mode": "custom", **_GROUP_FIELDS},
            "A2": {"engine_mode": "custom", **_GROUP_FIELDS},
        },
        strategy_book=book,
    )
    assert account.strategy_book is book
    for config in account.strategy_configs.values():
        assert config.get(FeeModule.fee_mode) == "fixed"
        assert config.get(MarginModule.margin_mode) == "fixed"
        assert config.get(TradingRuleModule.accounting_mode) == "Custom"
        assert config.get(TradingRuleModule.daily_mark_to_market_enabled) is True
        assert config.get(TradingRuleModule.cost_basis_method) == "FIFO"


def test_apply_strategy_configs_rejects_conflicting_ledger_config_fields():
    account = BacktestRunState()
    book = StrategyBook.from_dict({
        "strategies": {
            "A1": {"ledger_ids": ["book-a", "book-b"], "default_ledger_id": "book-a"},
        },
        "ledgers": {
            "book-a": {"fee_mode": "fixed"},
            "book-b": {"fee_mode": "zero"},
        },
    })
    try:
        apply_strategy_configs(
            account,
            {"A1": {"engine_mode": "custom", **_GROUP_FIELDS}},
            strategy_book=book,
        )
    except ValueError as exc:
        assert "conflicting fee_mode" in str(exc)
    else:
        raise AssertionError("expected conflicting ledger config fields to fail")


def test_apply_strategy_configs_rejects_shared_ledger_counterparty_conflict():
    register_counterparty_profile(CounterPartyProfile(
        id="__test_bootstrap_conflict_profile__",
        label="测试入口冲突预设",
        field_defaults={FeeModule.fee_mode: "fixed"},
    ))
    apply_counterparty_profile_defaults()
    try:
        account = BacktestRunState()
        book = StrategyBook.from_dict({
            "strategies": {
                "A1": "shared-book",
                "A2": "shared-book",
            },
        })
        try:
            apply_strategy_configs(
                account,
                {
                    "A1": {"counterparty_profile": "exchange_base", **_GROUP_FIELDS},
                    "A2": {"counterparty_profile": "__test_bootstrap_conflict_profile__", **_GROUP_FIELDS},
                },
                strategy_book=book,
            )
        except ValueError as exc:
            assert "conflicting counterparty profiles" in str(exc)
        else:
            raise AssertionError("expected counterparty conflict during strategy-config bootstrap")
    finally:
        unregister_counterparty_profile("__test_bootstrap_conflict_profile__")
