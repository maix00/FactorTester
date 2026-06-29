"""国信期货 — 限价单/最小开仓下单量 历史调整事件（含期货和期权）。

访问策略：
- 如果这个 source 今天已经成功访问过，优先直接读本地历史记录
- 否则先尝试在线发现最新链接并抓取
- 在线成功后记录今天的访问日期到 ``sources/visits``，并同步表格到本地 SQLite
- 在线失败时回退到本地历史记录；本地也没有时再回退静态快照
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tools.data.hub import DataHub
from ._source import SOURCE_NAME, discover_source_url, fetch_table as _fetch_table
from ._store import (
    ensure_sqlite_store,
    load_latest_events,
    load_latest_source_metadata,
    load_latest_table,
    save_events,
    save_table,
)

SOURCE_KEY = "Guosen/LimitOrderVolume"
hub = DataHub.get_instance()
hub.register_visit_source(SOURCE_KEY, SOURCE_NAME)


def _today_str() -> str:
    return date.today().isoformat()


def _load_local_table():
    return load_latest_table()


def _load_local_metadata() -> tuple[str, str] | None:
    return load_latest_source_metadata()


def _discover_online_metadata() -> tuple[str, str]:
    source_url, source_date = discover_source_url()
    return source_url, source_date.isoformat() if source_date is not None else ""


def _load_online_table(source_url: str, source_date: str) -> Any:
    df = _fetch_table(source_url=source_url, source_date=source_date)
    save_table(df)
    _save_events_for_table(df)
    return df


def _save_events_for_table(df: Any) -> None:
    from tools.data.field_history import save_historical_field_records

    from ._analysis import events_to_historical_field_records, parse_events_from_df

    events = parse_events_from_df(df)
    save_events(events)
    save_historical_field_records(
        events_to_historical_field_records(events),
        replace_provider="Guosen",
        replace_source_key=SOURCE_KEY,
    )


def _ensure_events_for_cached_table(df: Any) -> None:
    if load_latest_events() is None:
        _save_events_for_table(df)


def load_source_metadata() -> tuple[str, str]:
    """Resolve source metadata with visit-aware offline fallback."""
    cached = _load_local_metadata()
    source_url: str | None = None
    source_date: str | None = None
    today_visited = hub.get_latest_access_date(SOURCE_KEY) == _today_str()
    if today_visited and cached is not None:
        return cached

    try:
        source_url, source_date = _discover_online_metadata()
    except Exception:
        if cached is not None:
            return cached
        raise RuntimeError("无法在线获取数据来源的 URL 和日期，且本地缓存不可用，请检查网络连接或本地缓存。")   

    if cached is not None:
        _, local_date = cached
        if local_date == source_date:
            return cached

    return source_url, source_date


SOURCE_URL, SOURCE_DATE = load_source_metadata()


def fetch_table(url: str | None = None):
    """抓取表格；无显式 URL 时遵循访问记录优先本地历史。"""
    if url is not None:
        df = _fetch_table(url=url, source_url=url)
        save_table(df)
        _save_events_for_table(df)
        hub.record_visit(SOURCE_KEY, source_label=SOURCE_NAME, access_date=_today_str())
        return df

    today = _today_str()
    cached = _load_local_table()
    local_metadata = _load_local_metadata()
    if hub.get_latest_access_date(SOURCE_KEY) == today:
        if cached is not None:
            _ensure_events_for_cached_table(cached)
            return cached

    try:
        source_url, source_date = _discover_online_metadata()
    except Exception:
        if cached is not None:
            _ensure_events_for_cached_table(cached)
            return cached
        raise

    if local_metadata is not None and local_metadata[1] == source_date:
        hub.record_visit(SOURCE_KEY, source_label=SOURCE_NAME, access_date=today)
        if cached is not None:
            _ensure_events_for_cached_table(cached)
            return cached
        # 本地元数据还在但表数据丢了，兜底回抓一次。

    df = _load_online_table(source_url, source_date)
    hub.record_visit(SOURCE_KEY, source_label=SOURCE_NAME, access_date=today)
    return df


from .access import (
    iter_all_events,
    list_all_events,
    list_events_by_exchange,
    list_events_by_product,
    list_events_effective_between,
    list_events_effective_on_or_before,
    list_events_effective_after,
    to_dataframe,
)
from .alter import AlterEvent, Exchange, KNOWN_ALTER_EVENTS, parse_alter_events_from_note

__all__ = [
    # 数据源元信息
    "SOURCE_URL",
    "SOURCE_NAME",
    "SOURCE_DATE",
    "SOURCE_KEY",
    # 数据采集
    "discover_source_url",
    "fetch_table",
    "ensure_sqlite_store",
    "load_latest_source_metadata",
    "load_latest_table",
    "load_latest_events",
    "save_table",
    "save_events",
    "load_source_metadata",
    # 模型
    "AlterEvent",
    "Exchange",
    "KNOWN_ALTER_EVENTS",
    "parse_alter_events_from_note",
    # 查询
    "list_all_events",
    "list_events_by_exchange",
    "list_events_by_product",
    "list_events_effective_on_or_before",
    "list_events_effective_after",
    "list_events_effective_between",
    "to_dataframe",
    "iter_all_events",
]
