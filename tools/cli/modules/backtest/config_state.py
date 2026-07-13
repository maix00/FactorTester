"""State mutation helpers for backtest configuration commands."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.modules.backtest import config_args as config_arg_helpers


def strategy_book_payload(state) -> dict[str, Any]:
    payload = dict(state.backtest_strategy_book or {})
    payload.setdefault("strategies", {})
    payload.setdefault("cash_pools", {})
    payload.setdefault("cash_pool_configs", {})
    return payload


def apply_strategy_book_ledger(state, args: tuple[str, ...], *, arg_value) -> None:
    strategy = arg_value(args, "--strategy")
    ledger = arg_value(args, "--ledger")
    if not strategy or not ledger:
        raise click.ClickException("strategy-book ledger 必须传 --strategy STRATEGY --ledger LEDGER")
    cash_pool = arg_value(args, "--cash-pool") or ledger
    make_default = "--default" in args
    payload = strategy_book_payload(state)
    strategies = payload.setdefault("strategies", {})
    raw_entry = strategies.get(strategy)
    entry = dict(raw_entry) if isinstance(raw_entry, dict) else {}
    ledgers = list(entry.get("ledger_ids") or entry.get("ledgers") or [])
    if ledger not in ledgers:
        ledgers.append(ledger)
    entry["ledger_ids"] = ledgers
    if make_default or not entry.get("default_ledger_id"):
        entry["default_ledger_id"] = ledger
    strategies[strategy] = entry
    payload.setdefault("cash_pools", {})[ledger] = cash_pool
    state.backtest_strategy_book = payload


def apply_strategy_book_cash_pool(state, args: tuple[str, ...], *, arg_value) -> None:
    cash_pool = arg_value(args, "--cash-pool")
    if not cash_pool:
        raise click.ClickException("strategy-book cash-pool 必须传 --cash-pool ID")
    payload = strategy_book_payload(state)
    configs = payload.setdefault("cash_pool_configs", {})
    config = dict(configs.get(cash_pool) or {})
    config_arg_helpers.set_optional_float_arg(config, args, "--initial-capital-major", "initial_capital_major", arg_value=arg_value)
    base_currency = arg_value(args, "--base-currency")
    if base_currency:
        config["base_currency"] = base_currency
    config_arg_helpers.set_optional_float_arg(config, args, "--currency-conversion-fee-rate", "currency_conversion_fee_rate", arg_value=arg_value)
    configs[cash_pool] = config
    state.backtest_strategy_book = payload
