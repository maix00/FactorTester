"""Internal immutable inputs for margin-budget orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TargetItem:
    strategy: Any
    product: Any
    ledger: Any
    pool_id: str
    equity: float
    weight: float
    margin_ratio: float
    margin_enabled: bool

    @property
    def gross_notional(self) -> float:
        return abs(self.weight) * self.equity

    @property
    def projected_margin(self) -> float:
        return self.gross_notional * self.margin_ratio


@dataclass(frozen=True)
class PoolSettings:
    target: float
    maximum: float
    tolerance: float


def require_one_pool_setting(
    pool_id: str,
    values: list[PoolSettings],
) -> PoolSettings:
    unique = {(item.target, item.maximum, item.tolerance) for item in values}
    if len(unique) != 1:
        raise ValueError(
            f"cash_pool {pool_id!r} receives conflicting margin utilization settings: "
            f"{sorted(unique)!r}"
        )
    return values[0]


def settings_for_pool(state, pool_id: str, config: Any, module: Any) -> PoolSettings:
    from tools.testers.backtest.modules.cash_pool import cash_pool_store_for

    pool = cash_pool_store_for(state).config_by_pool.get(str(pool_id))
    return PoolSettings(
        target=float(
            getattr(pool, "target_margin_utilization", None)
            or config.get(module.target_margin_utilization, 0.80)
        ),
        maximum=float(
            getattr(pool, "max_margin_utilization", None)
            or config.get(module.max_margin_utilization, 0.85)
        ),
        tolerance=float(
            getattr(pool, "margin_utilization_tolerance", None)
            if getattr(pool, "margin_utilization_tolerance", None) is not None
            else config.get(module.margin_utilization_tolerance, 0.01)
        ),
    )
