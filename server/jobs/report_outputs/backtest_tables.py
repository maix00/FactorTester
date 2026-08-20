"""Declarations for optional backtest analysis tables.

Keeping these mechanically similar declarations together makes the wire
contract reviewable without extending the shared IC/output registry further.
"""

from __future__ import annotations

from typing import Any


def _table(
    label: str,
    name: str,
    *,
    requires: list[str],
    retention: str = "summary",
) -> dict[str, Any]:
    return {
        "label": label,
        "formats": ["csv", "json"],
        "presentation": "table",
        "viewer": "data_table",
        "artifacts": [f"{name}_csv", f"{name}_data", f"{name}_receipt"],
        "canonical_artifact": f"{name}_data",
        "rendition_artifacts": [f"{name}_csv"],
        "receipt_artifact": f"{name}_receipt",
        "before_run": True,
        "after_run": True,
        "requires": requires,
        "analyses": ["backtest"],
        "result_retention_mode": retention,
    }


BACKTEST_TABLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "order_detail": _table(
        "订单明细", "order_detail", requires=["order_audit"],
    ),
    "fill_detail": _table(
        "成交与结算明细", "fill_detail", requires=["order_audit"],
    ),
    "cash_detail": _table(
        "现金变化", "cash_detail", requires=["order_audit"],
    ),
    "position_detail": _table(
        "持仓变化", "position_detail", requires=["group_execution"], retention="full",
    ),
    "exposure_detail": _table(
        "风险敞口与杠杆", "exposure_detail",
        requires=["group_execution"], retention="full",
    ),
    "turnover_detail": _table(
        "换手率", "turnover_detail", requires=["group_execution"],
    ),
    "drawdown_detail": _table(
        "回撤区间", "drawdown_detail", requires=["result"],
    ),
    "period_returns": _table(
        "周期收益", "period_returns", requires=["result"],
    ),
}


BACKTEST_TABLE_DESCRIPTIONS = {
    artifact: description
    for name, definition in BACKTEST_TABLE_DEFINITIONS.items()
    for artifact, description in {
        f"{name}_csv": f"{definition['label']}（CSV）",
        f"{name}_data": f"{definition['label']}（JSON）",
        f"{name}_receipt": f"{definition['label']}生成说明（JSON）",
    }.items()
}
