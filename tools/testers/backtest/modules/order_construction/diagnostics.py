"""Aggregated diagnostics for targets that cannot produce an Order."""

from __future__ import annotations

from tools.testers.backtest.modules.runtime_info import (
    product_display,
    product_display_text,
    record_runtime_info,
    runtime_interval_state,
)


def record_untradable_target_skip(state, strategy, product, timestamp) -> None:
    strategy_name = str(getattr(strategy, "alias", strategy))
    product_info = product_display(product)
    display = product_display_text(product_info)
    reason = "缺少有效可交易价格或被可交易状态过滤"
    aggregation_key = f"{strategy_name}|{product_info['name']}|{reason}"
    ts_text = str(timestamp)
    start, end, count, last_timestamp = runtime_interval_state(
        state, "order_target_skipped_untradable", aggregation_key, ts_text,
    )
    details = {
        "strategy": strategy_name,
        "product": product_info["name"],
        "product_desc": product_info["desc"],
        "reason": reason,
        "start": start,
        "end": end,
        "timestamp": end,
        "count": count,
        "last_timestamp": last_timestamp,
    }
    record_runtime_info(
        state, code="order_target_skipped_untradable", type="订单",
        status="未生成", level="warning",
        message=f"{display} 当前不可交易，目标调整未生成订单",
        detail=(
            f"{display} 在 {start} 到 {end} 期间 {reason}；"
            f"目标调整未生成订单，既有持仓保留，等待后续可交易时点；累计 {count} 次。"
        ),
        details=details, aggregation_key=aggregation_key,
    )
