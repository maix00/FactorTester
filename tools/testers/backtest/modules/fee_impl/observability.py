"""Runtime diagnostics for transaction-fee assumptions and fallbacks."""

from __future__ import annotations

from tools.testers.backtest.modules.runtime_info import (
    product_display,
    product_display_text,
    record_runtime_fallback_interval,
    record_runtime_info,
)

from .market import missing_market_fee_fields


def record_fee_runtime_assumption(
    state,
    *,
    strategy,
    product,
    timestamp,
    mode: str,
    fields: dict[str, object],
) -> None:
    alias = str(getattr(strategy, "alias", strategy) or "")
    if mode == "zero":
        record_runtime_info(
            state,
            code="fee_zero_mode",
            type="交易费用",
            status="研究假设",
            level="warning",
            message=f"策略 {alias} 使用零手续费假设",
            detail=f"策略 {alias} 明确按零手续费运行；收益结果未扣除交易费用。",
            details={"strategy": alias, "fee_mode": "zero"},
            aggregation_key=alias,
        )
        return
    missing = missing_market_fee_fields(fields)
    if mode != "auto" or not missing:
        return
    display = product_display(product)
    record_runtime_fallback_interval(
        state,
        code="fee_auto_missing_history",
        type="交易费用",
        status="高风险回退",
        level="error",
        product=product,
        timestamp=timestamp,
        source="历史交易费率",
        fallback="零手续费",
        reason="该时点缺少完整的历史费率字段",
        extra={"strategy": alias, "missing_fields": missing},
    )
    row = next(
        (
            item
            for item in getattr(state, "runtime_info_rows", ())
            if item.get("code") == "fee_auto_missing_history"
            and item.get("details", {}).get("strategy") == alias
            and item.get("details", {}).get("product") == display["name"]
        ),
        None,
    )
    if row is not None:
        details = row["details"]
        row["message"] = f"策略 {alias} 的 {product_display_text(display)} 缺少历史费率，已回退为零手续费"
        row["detail"] = (
            f"高风险：策略 {alias} 的 {product_display_text(display)} 在 "
            f"{details['start']} 到 {details['end']} 期间缺少完整历史费率，"
            f"已按零手续费计算；累计 {details['count']} 个交易时点。"
        )
