"""Bounded research artifacts derived from authoritative backtest state."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def project_net_returns(
    *,
    engine_result: dict[str, Any],
    group_owner: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Project fee-adjusted returns without interpreting factor quality."""
    if str(engine_result.get("engine") or "") != "native":
        return None
    portfolios = engine_result.get("portfolios")
    if not isinstance(portfolios, dict) or not portfolios:
        raise ValueError("net return artifact requires portfolio equity")
    owners = {
        str(item.get("strategy_id") or item.get("group_id") or ""): item
        for item in group_owner
        if isinstance(item, dict)
        and str(item.get("strategy_id") or item.get("group_id") or "")
    }
    series = [
        _strategy_returns(
            strategy_id=strategy_id,
            portfolio=portfolios[strategy_id],
            owner=owners.get(strategy_id, {}),
        )
        for strategy_id in sorted(portfolios)
    ]
    return {
        "schema_version": 1,
        "artifact_kind": "net_return_series",
        "engine": "native",
        "accounting_basis": (
            "ledger_equity_after_fees_slippage_margin_and_settlement"
        ),
        "valuation_basis": "display_equity_curve_signal_points",
        "series": series,
    }


def _strategy_returns(
    *,
    strategy_id: str,
    portfolio: Any,
    owner: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(portfolio, dict):
        raise ValueError("portfolio equity must be an object")
    curve = (
        portfolio.get("display_equity_curve")
        or portfolio.get("equity_curve")
    )
    if not isinstance(curve, dict) or not curve:
        raise ValueError(
            f"strategy {strategy_id!r} has no authoritative equity curve"
        )
    points = sorted(
        (
            (pd.Timestamp(timestamp), float(equity))
            for timestamp, equity in curve.items()
        ),
        key=lambda item: item[0],
    )
    equity = pd.Series(
        [item[1] for item in points],
        index=pd.DatetimeIndex([item[0] for item in points]),
        dtype=float,
    )
    if (
        equity.index.has_duplicates
        or not all(math.isfinite(value) and value != 0.0 for value in equity)
    ):
        raise ValueError(
            f"strategy {strategy_id!r} equity is non-finite or non-divisible"
        )
    returns = equity.pct_change().fillna(0.0)
    if not all(math.isfinite(value) for value in returns):
        raise ValueError(f"strategy {strategy_id!r} returns are non-finite")
    return {
        "strategy_id": strategy_id,
        "display_name": str(
            owner.get("display_name") or owner.get("group_name") or strategy_id
        ),
        "factor_alias": str(owner.get("factor_alias") or ""),
        "timestamps": [timestamp.isoformat() for timestamp in equity.index],
        "returns": [round(float(value), 12) for value in returns],
    }
