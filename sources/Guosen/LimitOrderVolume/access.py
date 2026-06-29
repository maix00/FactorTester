"""访问国信期货限价单手数调整事件的方法。

提供按交易所、品种、日期等维度查询 AlterEvent 的便捷函数。
"""

from __future__ import annotations

from datetime import date
import json
from typing import Any

import pandas as pd

from .alter import AlterEvent, Exchange, iter_known_events


# ---------------------------------------------------------------------------
# 内存缓存（模块加载时一次性构建）
# ---------------------------------------------------------------------------
_EVENTS: list[AlterEvent] = []
_EVENTS_BY_EXCHANGE: dict[str, list[AlterEvent]] = {}
_EVENTS_BY_PRODUCT: dict[str, list[AlterEvent]] = {}


def _parse_contract_codes(value: Any) -> tuple[str, ...]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    text = str(value).strip()
    if not text:
        return ()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in text.split(",")]
    if isinstance(parsed, list):
        return tuple(str(item) for item in parsed if str(item))
    return ()


def _parse_effective_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat"}:
        return None
    return date.fromisoformat(text[:10])


def _events_from_frame(df: pd.DataFrame) -> list[AlterEvent]:
    events: list[AlterEvent] = []
    for _, row in df.iterrows():
        events.append(
            AlterEvent(
                exchange=str(row.get("exchange") or ""),
                product_label=str(row.get("product_label") or ""),
                product_code=str(row.get("product_code") or ""),
                product_code_match_status=str(row.get("product_code_match_status") or ""),
                instrument_type=str(row.get("instrument_type") or "future"),
                contract_codes=_parse_contract_codes(row.get("contract_codes")),
                field=str(row.get("field") or "MinLimitOrderVolume"),
                old_value=None if pd.isna(row.get("old_value")) else float(row.get("old_value")),
                new_value=0.0 if pd.isna(row.get("new_value")) else float(row.get("new_value")),
                effective_date=_parse_effective_date(row.get("effective_date")),
                source_url=str(row.get("source_url") or ""),
                source_date=str(row.get("source_date") or ""),
                raw_note=str(row.get("raw_note") or ""),
            )
        )
    return events


def _load_events_from_sqlite() -> list[AlterEvent]:
    from ._analysis import parse_events_from_df
    from ._store import load_latest_events, load_latest_table, save_events

    events_df = load_latest_events()
    if events_df is not None:
        return _events_from_frame(events_df)

    raw_df = load_latest_table()
    if raw_df is None:
        return []

    event_dicts = parse_events_from_df(raw_df)
    save_events(event_dicts)
    return _events_from_frame(pd.DataFrame(event_dicts))


def _ensure_loaded() -> None:
    """懒加载：首次访问时优先从 SQLite 事件表构建缓存。"""
    global _EVENTS, _EVENTS_BY_EXCHANGE, _EVENTS_BY_PRODUCT
    if _EVENTS:
        return

    _EVENTS = _load_events_from_sqlite()
    if not _EVENTS:
        _EVENTS = iter_known_events()

    for ev in _EVENTS:
        _EVENTS_BY_EXCHANGE.setdefault(ev.exchange, []).append(ev)
        _EVENTS_BY_PRODUCT.setdefault(ev.product_label, []).append(ev)
        if ev.product_code:
            _EVENTS_BY_PRODUCT.setdefault(ev.product_code, []).append(ev)


# ---------------------------------------------------------------------------
# 查询 API
# ---------------------------------------------------------------------------

def list_all_events() -> list[AlterEvent]:
    """返回全部已知调整事件。"""
    _ensure_loaded()
    return list(_EVENTS)


def list_events_by_exchange(exchange: str) -> list[AlterEvent]:
    """按交易所代码筛选。

    exchange 取值为 Exchange 常量：SHFE, INE, DCE, CZCE, GFEX, CFFEX
    """
    _ensure_loaded()
    return list(_EVENTS_BY_EXCHANGE.get(exchange, []))


def list_events_by_product(product_label: str) -> list[AlterEvent]:
    """按品种中文名筛选（如 '动力煤'、'甲醇'）。"""
    _ensure_loaded()
    return list(_EVENTS_BY_PRODUCT.get(product_label, []))


def list_events_effective_on_or_before(cutoff: date) -> list[AlterEvent]:
    """返回在指定日期或之前生效的全部事件。"""
    _ensure_loaded()
    return [ev for ev in _EVENTS if ev.effective_date and ev.effective_date <= cutoff]


def list_events_effective_after(cutoff: date) -> list[AlterEvent]:
    """返回在指定日期之后生效的全部事件。"""
    _ensure_loaded()
    return [ev for ev in _EVENTS if ev.effective_date and ev.effective_date > cutoff]


def list_events_effective_between(start: date, end: date) -> list[AlterEvent]:
    """返回在 [start, end] 区间的生效事件。"""
    _ensure_loaded()
    return [
        ev
        for ev in _EVENTS
        if ev.effective_date and start <= ev.effective_date <= end
    ]


# ---------------------------------------------------------------------------
# DataFrame 格式导出
# ---------------------------------------------------------------------------

def to_dataframe(events: list[AlterEvent] | None = None) -> pd.DataFrame:
    """将 AlterEvent 列表转为 DataFrame。

    若未传入 events，返回全部已知事件。
    """
    _ensure_loaded()
    source = events if events is not None else _EVENTS
    if not source:
        return pd.DataFrame(
            columns=[
                "exchange", "product_label", "product_code", "instrument_type", "contract_codes",
                "field", "old_value", "new_value", "effective_date",
                "is_product_level", "source_url", "source_date", "raw_note",
            ]
        )
    rows = []
    for ev in source:
        rows.append({
            "exchange": ev.exchange,
            "product_label": ev.product_label,
            "product_code": ev.product_code,
            "product_code_match_status": ev.product_code_match_status,
            "instrument_type": ev.instrument_type,
            "contract_codes": ev.contract_range,
            "field": ev.field,
            "old_value": ev.old_value,
            "new_value": ev.new_value,
            "effective_date": ev.effective_date.isoformat() if ev.effective_date else None,
            "is_product_level": ev.is_product_level,
            "source_url": ev.source_url,
            "source_date": ev.source_date,
            "raw_note": ev.raw_note,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 便捷导出函数：用于注册到 loader
# ---------------------------------------------------------------------------

def iter_all_events() -> list[AlterEvent]:
    """供外部 loader 调用的入口。等价于 list_all_events()。"""
    return list_all_events()
