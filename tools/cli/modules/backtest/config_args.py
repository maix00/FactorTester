"""Argument parsing helpers for backtest configuration commands."""

from __future__ import annotations

from typing import Any

import click


def parse_ledger_config_args(args: tuple[str, ...], *, arg_value, parse_raw_settings) -> dict[str, Any]:
    values: dict[str, Any] = {}
    string_fields = {
        "--fee-mode": "fee_mode",
        "--transaction-fee-source": "transaction_fee_source",
        "--margin-mode": "margin_mode",
        "--margin-call-mode": "margin_call_mode",
        "--accounting-mode": "accounting_mode",
        "--cost-basis-method": "cost_basis_method",
        "--tradability-policy": "tradability_policy",
        "--clearing-rounding-policy": "clearing_rounding_policy",
    }
    float_fields = {
        "--fixed-fee-rate": "fixed_fee_rate",
        "--fixed-margin-ratio": "fixed_margin_ratio",
        "--liquidation-target-buffer": "liquidation_target_buffer",
        "--cash-reserve-ratio": "cash_reserve_ratio",
        "--cash-reserve-major": "cash_reserve_major",
    }
    bool_fields = {
        "--daily-mark-to-market-enabled": "daily_mark_to_market_enabled",
        "--use-int-position": "use_int_position",
    }
    for flag, key in string_fields.items():
        value = arg_value(args, flag)
        if value:
            values[key] = value
    for flag, key in float_fields.items():
        value = arg_value(args, flag)
        if value:
            values[key] = float(value)
    for flag, key in bool_fields.items():
        value = arg_value(args, flag)
        if value:
            values[key] = parse_bool(value, flag)
    extra = parse_raw_settings(tuple(strip_known_ledger_config_args(args)))
    values.update(extra)
    return values


def strip_known_ledger_config_args(args: tuple[str, ...]) -> list[str]:
    known_with_value = {
        "--ledger",
        "--fee-mode",
        "--transaction-fee-source",
        "--fixed-fee-rate",
        "--margin-mode",
        "--fixed-margin-ratio",
        "--margin-call-mode",
        "--liquidation-target-buffer",
        "--accounting-mode",
        "--daily-mark-to-market-enabled",
        "--cost-basis-method",
        "--use-int-position",
        "--tradability-policy",
        "--clearing-rounding-policy",
        "--cash-reserve-ratio",
        "--cash-reserve-major",
    }
    result: list[str] = []
    i = 0
    while i < len(args):
        if args[i] in known_with_value:
            i += 2
            continue
        result.append(args[i])
        i += 1
    return result


def set_optional_float_arg(target: dict[str, Any], args: tuple[str, ...], flag: str, key: str, *, arg_value) -> None:
    value = arg_value(args, flag)
    if value:
        target[key] = float(value)


def parse_bool(value: str, flag: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise click.ClickException(f"{flag} 需要布尔值: {value}")
