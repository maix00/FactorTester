"""State mutation helpers for backtest configuration commands."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.field_store import FieldStore
from tools.cli.modules.backtest import config_args as config_arg_helpers
from tools.cli.modules.backtest.shared.fields import resolve_backtest_public_fields
from tools.cli.modules.keys import BACKTEST_BACKEND_KEY
from tools.cli.modules.products.controller import product_group_selection


def stores_for_backtest(state, client=None) -> tuple[FieldStore, FieldStore]:
    client = client or client_from_config()
    page_store = FieldStore.from_manifest(client.manifest("single_factor_page"), values=state.page_settings)
    backtest_store = FieldStore.from_manifest(
        client.manifest(BACKTEST_BACKEND_KEY),
        values=state.backtest_local_settings,
        parent=page_store,
    )
    return page_store, backtest_store


def ensure_page_candidates(state, client) -> None:
    page_store = FieldStore.from_manifest(client.manifest("single_factor_page"), values=state.page_settings)
    fields = resolve_backtest_public_fields(page_store)
    if not page_store.effective(fields.product_path_candidates):
        groups = client.list_candidates(fields.product_path_candidates)
        page_store.set(fields.product_path_candidates, groups)
        if groups and not page_store.effective(fields.product_path_selection):
            page_store.set(fields.product_path_selection, product_group_selection(groups[0]))
    state.page_settings = page_store.to_payload()


def load_default_factor_for_product_group(
    state,
    client,
    page_store: FieldStore,
    *,
    factor_family: str,
    product_group_label: str,
) -> None:
    if not factor_family:
        return
    overview = client.factor_library_overview(factor_family=factor_family, product_group=product_group_label)
    factors = list(overview.get("factors") or [])
    fields = resolve_backtest_public_fields(page_store)
    page_store.set(fields.factor_candidates, factors)
    if factors:
        page_store.set(fields.factor, str(factors[0].get("factor_alias") or factors[0].get("alias") or ""))


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
