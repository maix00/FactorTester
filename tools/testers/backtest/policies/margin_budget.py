"""Pure cash-pool margin-budget decision contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MarginBudgetRequest:
    cash_pool_id: str
    effective_timestamp: Any
    equity: float
    target_utilization: float
    max_utilization: float
    tolerance: float
    raw_gross_notional: float
    raw_projected_margin: float


@dataclass(frozen=True)
class MarginBudgetDecision:
    cash_pool_id: str
    effective_timestamp: Any
    equity: float
    scale: float
    gross_leverage: float
    weighted_margin_ratio: float
    target_margin: float
    projected_margin: float
    projected_utilization: float
    max_utilization: float
    tolerance: float
    policy_id: str = "default_target_margin_utilization"
    policy_version: str = "1"
    reason_code: str = "target_margin_budget"
    diagnostics: dict[str, Any] = field(default_factory=dict)


def default_margin_budget_policy(request: MarginBudgetRequest) -> MarginBudgetDecision:
    _validate_request(request)
    target_margin = request.equity * request.target_utilization
    if request.raw_projected_margin <= 1e-12:
        scale = 1.0
        reason = "no_margin_target"
    else:
        scale = target_margin / request.raw_projected_margin
        reason = "target_margin_budget"
    projected = request.raw_projected_margin * scale
    gross = request.raw_gross_notional * scale
    weighted = (
        request.raw_projected_margin / request.raw_gross_notional
        if request.raw_gross_notional > 1e-12 else 0.0
    )
    return MarginBudgetDecision(
        cash_pool_id=request.cash_pool_id,
        effective_timestamp=request.effective_timestamp,
        equity=request.equity,
        scale=scale,
        gross_leverage=gross / request.equity,
        weighted_margin_ratio=weighted,
        target_margin=target_margin,
        projected_margin=projected,
        projected_utilization=projected / request.equity,
        max_utilization=request.max_utilization,
        tolerance=request.tolerance,
        reason_code=reason,
        diagnostics={
            "raw_gross_notional": request.raw_gross_notional,
            "raw_projected_margin": request.raw_projected_margin,
        },
    )


def validate_margin_budget_decision(
    request: MarginBudgetRequest,
    decision: MarginBudgetDecision,
) -> None:
    if decision.cash_pool_id != request.cash_pool_id:
        raise ValueError("margin budget decision changed cash_pool_id")
    if decision.scale < 0 or not _finite(decision.scale):
        raise ValueError("margin budget scale must be finite and non-negative")
    if decision.projected_utilization > request.max_utilization + request.tolerance:
        raise ValueError("margin budget decision exceeds max utilization")


def _validate_request(request: MarginBudgetRequest) -> None:
    values = (
        request.equity,
        request.target_utilization,
        request.max_utilization,
        request.tolerance,
        request.raw_gross_notional,
        request.raw_projected_margin,
    )
    if not all(_finite(value) for value in values):
        raise ValueError("margin budget request values must be finite")
    if request.equity <= 0:
        raise ValueError("margin budget requires positive cash-pool equity")
    if not 0 < request.target_utilization <= request.max_utilization < 1:
        raise ValueError("margin utilization requires 0 < target <= max < 1")
    if request.tolerance < 0:
        raise ValueError("margin utilization tolerance must be non-negative")
    if request.raw_gross_notional < 0 or request.raw_projected_margin < 0:
        raise ValueError("projected notional and margin must be non-negative")


def _finite(value: float) -> bool:
    from math import isfinite

    return isfinite(float(value))
