"""Fee-mode resolution."""

from __future__ import annotations

from typing import Any, cast

from tools.testers.backtest.modules.engine import engine_mode_for


def normalise_fee_mode(value: object) -> str:
    mode = str(value or "auto")
    allowed = {
        "auto", "exact", "custom", "close_yesterday",
        "close_today", "fixed", "zero",
    }
    if mode not in allowed:
        raise ValueError(f"unsupported fee_mode: {mode!r}")
    return mode


def resolve_fee_mode(config, ledger_config=None) -> str:
    engine_mode = engine_mode_for(config)
    if engine_mode == "basic":
        return "zero"
    if engine_mode == "auto":
        return "auto"
    if engine_mode == "exact":
        return "exact"
    return resolve_fee_mode_from_ledger_config(ledger_config)


def resolve_fee_mode_from_ledger_config(ledger_config=None) -> str:
    return normalise_fee_mode(
        getattr(ledger_config, "fee_mode", None) or "auto",
    )


def strategy_value(config, ref, default: Any) -> Any:
    value = config.get(ref, None)
    return default if value is None else value


def number(value: object, default: float) -> float:
    if value in (None, ""):
        return default
    parsed = float(cast(Any, value))
    return default if parsed != parsed else parsed
