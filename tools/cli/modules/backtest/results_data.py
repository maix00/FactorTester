"""Pure data helpers for stored backtest result views."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any


def result_timestamp_ms(data: dict[str, Any], args: tuple[str, ...], *, error: Callable[[str], Exception]) -> int:
    explicit = arg_value(args, "--timestamp-ms")
    if explicit:
        return int(explicit)
    index_raw = arg_value(args, "--index")
    index = int(index_raw or "1") - 1
    groups_raw = data.get("groups")
    groups = groups_raw if isinstance(groups_raw, list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        timestamps = group.get("timestamps")
        if isinstance(timestamps, list) and timestamps:
            index = max(0, min(index, len(timestamps) - 1))
            return timestamp_value_to_ms(timestamps[index], error=error)
    raise error("最近一次结果没有时间索引，无法请求快照")


def selected_result_groups(data: dict[str, Any], group_name: str = "") -> list[dict[str, Any]]:
    groups = [group for group in (data.get("groups") or []) if isinstance(group, dict)]
    if not group_name:
        return groups
    group = result_group_for_name(data, group_name)
    return [group] if group else []


def result_group_for_name(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    for group in data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        keys = {
            str(group.get("name") or ""),
            str(group.get("id") or ""),
            str(group.get("group_id") or ""),
        }
        if name in keys:
            return group
    return None


def group_equity_curve(group: dict[str, Any]) -> list[float]:
    values = group.get("total_equity") or group.get("equity_curve") or []
    if isinstance(values, dict):
        values = list(values.values())
    return [as_float(value) for value in values]


def attribution_bucket(record: dict[str, Any], by: str) -> str:
    if by in {"ledger", "ledgers"}:
        return record_ledger_id(record) or "(未记录账本)"
    if by in {"cash-pool", "cash_pool", "cashpool"}:
        return record_cash_pool_id(record) or "(未记录资金池)"
    if by in {"product", "products", "contract", "contracts"}:
        return str(record.get("product") or record.get("instrument") or "")
    return ""


def attribution_table_title(by: str) -> str:
    if by in {"ledger", "ledgers"}:
        return "费用按账本聚合"
    if by in {"cash-pool", "cash_pool", "cashpool"}:
        return "费用按资金池聚合"
    return "费用按产品/合约聚合"


def attribution_table_header(by: str) -> str:
    if by in {"ledger", "ledgers"}:
        return "账本"
    if by in {"cash-pool", "cash_pool", "cashpool"}:
        return "资金池"
    return "产品/合约"


def record_ledger_id(record: dict[str, Any]) -> str:
    return record_detail_value(record, "ledger_id")


def record_cash_pool_id(record: dict[str, Any]) -> str:
    return record_detail_value(record, "cash_pool_id")


def record_detail_value(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if value not in (None, ""):
        return str(value)
    details = record.get("details")
    if isinstance(details, dict):
        value = details.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def group_detail_payload(state: Any, data: dict[str, Any], group: dict[str, Any], *, error: Callable[[str], Exception]) -> dict[str, Any]:
    product_path_selection_id = str(
        group.get("product_path_selection_id")
        or data.get("product_path_selection_id")
        or ""
    )
    if not product_path_selection_id:
        raise error("最近一次结果没有 product_path_selection_id，无法请求组内详情")
    return {
        "page_uuid": state.page_uuid,
        "product_path_selection_id": product_path_selection_id,
        "group_index": group.get("group_index", group.get("groupIndex", 1)),
        "group_id": group.get("group_id") or group.get("id"),
        "job_id": data.get("job_id") or "",
        "run_id": data.get("run_id") or data.get("run_token") or "",
    }


def product_display(product: Any) -> str:
    if not isinstance(product, dict):
        return str(product or "")
    name = str(product.get("name") or product.get("product") or product.get("display_ref") or "")
    desc = str(product.get("desc") or product.get("description") or "")
    if desc and desc not in name:
        return f"{name}({desc})"
    return name


def as_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def fmt_optional(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def fmt_detail_number(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if value is None and isinstance(record.get("details"), dict):
        value = record["details"].get(key)
    if value is None:
        return ""
    return f"{as_float(value):,.2f}"


def timestamp_value_to_ms(value: Any, *, error: Callable[[str], Exception]) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        raise error("时间索引为空，无法请求快照")
    try:
        return int(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise error(f"无法解析时间索引: {text}") from exc
    return int(parsed.timestamp() * 1000)


def group_id_for_name(data: dict[str, Any], name: str) -> str:
    for group in data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        keys = {str(group.get("name") or ""), str(group.get("id") or ""), str(group.get("group_id") or "")}
        if name in keys:
            return str(group.get("id") or group.get("group_id") or "")
    return ""


def arg_value(args: tuple[str, ...], flag: str) -> str:
    for index, token in enumerate(args):
        if token == flag and index + 1 < len(args):
            return str(args[index + 1])
    return ""
