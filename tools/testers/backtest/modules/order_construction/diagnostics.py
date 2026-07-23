"""Aggregated diagnostics for targets that cannot produce an Order."""

from __future__ import annotations

from tools.testers.backtest.modules.runtime_info import (
    product_display,
    product_display_text,
    record_runtime_info,
)


def record_untradable_target_skip(state, strategy, product, timestamp) -> None:
    strategy_name = str(getattr(strategy, "alias", strategy))
    product_info = product_display(product)
    display = product_display_text(product_info)
    reason = "缺少有效可交易价格或被可交易状态过滤"
    aggregation_key = f"{strategy_name}|{product_info['name']}|{reason}"
    ts_text = str(timestamp)
    start, end, count, seen = existing_interval(state, aggregation_key)
    start = min(start, ts_text) if start else ts_text
    end = max(end, ts_text) if end else ts_text
    if ts_text not in seen:
        seen.add(ts_text)
        count += 1
    details = {
        "strategy": strategy_name,
        "product": product_info["name"],
        "product_desc": product_info["desc"],
        "reason": reason,
        "start": start,
        "end": end,
        "timestamp": end,
        "count": count,
        "_seen_timestamps": sorted(seen),
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


def existing_interval(
    state, aggregation_key: str,
) -> tuple[str | None, str | None, int, set[str]]:
    rows = getattr(state, "runtime_info_rows", None)
    if not isinstance(rows, list):
        return None, None, 0, set()
    for row in rows:
        if not (
            isinstance(row, dict)
            and row.get("code") == "order_target_skipped_untradable"
            and row.get("aggregation_key") == aggregation_key
        ):
            continue
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        seen_raw = details.get("_seen_timestamps")
        seen = (
            {str(value) for value in seen_raw}
            if isinstance(seen_raw, (list, tuple, set))
            else ({str(details["start"])} if details.get("start") else set())
        )
        return (
            str(details.get("start")) if details.get("start") else None,
            str(details.get("end")) if details.get("end") else None,
            int(details.get("count") or 0), seen,
        )
    return None, None, 0, set()
