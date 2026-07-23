"""Cash-pool configuration validation and conflict handling."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.config import CashPoolConfig


def validate_margin_budget(config: CashPoolConfig, *, cash_pool_id: str) -> None:
    values = (
        config.target_margin_utilization,
        config.max_margin_utilization,
        config.margin_utilization_tolerance,
    )
    if all(value is None for value in values):
        return
    target = float(
        config.target_margin_utilization
        if config.target_margin_utilization is not None else 0.80
    )
    maximum = float(
        config.max_margin_utilization
        if config.max_margin_utilization is not None else 0.85
    )
    tolerance = float(
        config.margin_utilization_tolerance
        if config.margin_utilization_tolerance is not None else 0.01
    )
    if not 0 < target <= maximum < 1:
        raise ValueError(
            f"cash_pool {cash_pool_id!r} margin utilization requires 0 < target <= max < 1"
        )
    if tolerance < 0:
        raise ValueError(
            f"cash_pool {cash_pool_id!r} margin utilization tolerance must be non-negative"
        )


def merge_compatible(
    left: CashPoolConfig, right: CashPoolConfig, *, cash_pool_id: str, source: str,
) -> CashPoolConfig:
    values: dict[str, Any] = {}
    for key in (
        "initial_capital_major", "base_currency", "currency_conversion_fee_rate",
        "target_margin_utilization", "max_margin_utilization",
        "margin_utilization_tolerance",
    ):
        left_value, right_value = getattr(left, key), getattr(right, key)
        if left_value is None:
            values[key] = right_value
        elif right_value is None or right_value == left_value:
            values[key] = left_value
        else:
            hint = (
                " -- a shared cash pool is one pool of money in one currency; "
                "route cross-currency movement through FX trade events instead."
                if key == "base_currency" else ""
            )
            raise ValueError(
                f"cash_pool {cash_pool_id!r} receives conflicting {key}: "
                f"{left_value!r} vs {right_value!r} from {source}{hint}"
            )
    return CashPoolConfig(**values)
