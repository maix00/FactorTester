from __future__ import annotations

from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy_config_builder import (
    apply_strategy_configs,
    build_strategy_configs,
)
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.market_data import _required_market_rule_field_names
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule
from tools.testers.settings.counterparty import (
    CounterPartyProfile,
    apply_counterparty_profile_defaults,
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


def test_counterparty_profile_resolves_to_ledger_config_not_strategy_config():
    account = BacktestRunState()
    apply_strategy_configs(
        account,
        {"A1": {"engine_mode": "custom", **_GROUP_FIELDS}},
        counterparty="exchange_base",
    )
    ledger_id = next(iter(account.ledger_configs))
    ledger_config = account.ledger_config_for(ledger_id)
    assert ledger_config.fee_mode == "auto"
    assert ledger_config.margin_mode == "auto"
    assert ledger_config.accounting_mode == "Auto"
    assert ledger_config.use_int_position is True
    config = next(iter(account.strategy_configs.values()))
    assert config.get(FeeModule.fee_mode, None) is None
    assert config.get(MarginModule.margin_mode, None) is None
    assert config.get(TradingRuleModule.accounting_mode, None) is None


def test_explicit_margin_close_keeps_chip_value_and_skips_margin_flows():
    account = BacktestRunState()
    apply_strategy_configs(
        account,
        {"A1": {"engine_mode": "auto", "margin_mode": "none", **_GROUP_FIELDS}},
        counterparty="exchange_base",
    )

    ledger_id = next(iter(account.ledger_configs))
    ledger_config = account.ledger_config_for(ledger_id)
    assert ledger_config.margin_mode == "none"
    assert ledger_config.cost_basis_method is None

    config = next(iter(account.strategy_configs.values()))
    assert not config.uses_flow("register_margin_check_notices")
    assert not config.uses_flow("apply_margin_requirement_change")
    assert not config.uses_flow("handle_margin_liquidation_notice")
    fields = set(_required_market_rule_field_names(account))
    assert not {
        "LongMarginRatioByMoney",
        "ShortMarginRatioByMoney",
        "LongMarginRatioByVolume",
        "ShortMarginRatioByVolume",
    } & fields


def test_build_strategy_configs_does_not_materialize_ledger_owned_fields():
    configs = build_strategy_configs({
        "A1": {
            "engine_mode": "custom",
            "counterparty_profile": "exchange_base",
            "fee_mode": "fixed",
            "margin_mode": "fixed",
            "accounting_mode": "Custom",
            **_GROUP_FIELDS,
        },
    })
    strategy = next(iter(configs))
    config = configs[strategy]
    assert config.get(FeeModule.fee_mode, None) is None
    assert config.get(MarginModule.margin_mode, None) is None
    assert config.get(TradingRuleModule.accounting_mode, None) is None


def test_engine_mode_basic_auto_exact_presets_do_not_write_ledger_fields_to_strategy_config():
    configs = build_strategy_configs({
        "basic": {"engine_mode": "basic", **_GROUP_FIELDS},
        "auto": {"engine_mode": "auto", **_GROUP_FIELDS},
        "exact": {"engine_mode": "exact", **_GROUP_FIELDS},
    })
    assert {config.get(FeeModule.fee_mode, None) for config in configs.values()} == {None}


def test_registering_a_second_profile_does_not_clobber_the_first():
    register_counterparty_profile(CounterPartyProfile(
        id="__test_second_profile__",
        label="测试第二预设",
        field_defaults={FeeModule.fee_mode: "fixed"},
    ))
    apply_counterparty_profile_defaults()
    try:
        account = BacktestRunState()
        apply_strategy_configs(
            account,
            {
                "first": {"engine_mode": "custom", **_GROUP_FIELDS},
                "second": {"engine_mode": "custom", **_GROUP_FIELDS},
            },
            counterparty_by_strategy={
                "first": "exchange_base",
                "second": "__test_second_profile__",
            },
        )
        configs_by_ledger = {ledger_id: config.fee_mode for ledger_id, config in account.ledger_configs.items()}
        assert "auto" in set(configs_by_ledger.values())
        assert "fixed" in set(configs_by_ledger.values())
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


def test_counterparty_profile_can_be_applied_to_ledger_config():
    register_counterparty_profile(CounterPartyProfile(
        id="__test_ledger_config_profile__",
        label="测试账本配置预设",
        field_defaults={FeeModule.fee_mode: "fixed"},
    ))
    apply_counterparty_profile_defaults()
    try:
        account = BacktestRunState()
        book = StrategyBook.from_dict({
            "strategies": {
                "A1": "shared-book",
                "A2": "shared-book",
            }
        })
        apply_strategy_configs(
            account,
            {
                "A1": {"engine_mode": "custom", **_GROUP_FIELDS},
                "A2": {"engine_mode": "custom", **_GROUP_FIELDS},
            },
            strategy_book=book,
            counterparty_by_ledger={"shared-book": "__test_ledger_config_profile__"},
        )
        assert account.ledger_config_for("shared-book").fee_mode == "fixed"
        assert {config.get(FeeModule.fee_mode, None) for config in account.strategy_configs.values()} == {None}
    finally:
        unregister_counterparty_profile("__test_ledger_config_profile__")


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
        assert account.ledger_config_for("shared-book").fee_mode == "fixed"
        assert {config.get(FeeModule.fee_mode, None) for config in account.strategy_configs.values()} == {None}
    finally:
        unregister_counterparty_profile("__test_bootstrap_profile__")


def test_apply_strategy_configs_projects_ledger_config_fields():
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
        ledger_configs={
            "shared-book": {
                "fee_mode": "fixed",
                "margin_mode": "fixed",
                "accounting_mode": "Custom",
                "daily_mark_to_market_enabled": True,
                "cost_basis_method": "FIFO",
            },
        },
    )
    ledger_config = account.ledger_config_for("shared-book")
    assert ledger_config.fee_mode == "fixed"
    assert ledger_config.margin_mode == "fixed"
    assert ledger_config.accounting_mode == "Custom"
    assert ledger_config.daily_mark_to_market_enabled is True
    assert ledger_config.cost_basis_method == "FIFO"
    assert {config.get(FeeModule.fee_mode, None) for config in account.strategy_configs.values()} == {None}


def test_apply_strategy_configs_rejects_conflicting_ledger_config_fields():
    account = BacktestRunState()
    book = StrategyBook.from_dict({
        "strategies": {
            "A1": {"ledger_ids": ["book-a", "book-b"], "default_ledger_id": "book-a"},
        },
    })
    try:
        apply_strategy_configs(
            account,
            {"A1": {"engine_mode": "custom", **_GROUP_FIELDS}},
            strategy_book=book,
            ledger_configs={
            "book-a": {"fee_mode": "fixed"},
            "book-b": {"fee_mode": "zero"},
            },
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
