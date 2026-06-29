"""本地 SQLite 存储：国信期货每笔下单数量限制表。"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

import pandas as pd

import settings as Settings
from tools.data.hub import DataHub

logger = logging.getLogger(__name__)

TABLE_NAME = "guosen_limit_order_volume"
EVENTS_TABLE_NAME = "guosen_limit_order_events"
AUDIT_SUMMARY_VIEW = "guosen_limit_order_events_audit_summary"
AUDIT_UNMATCHED_VIEW = "guosen_limit_order_events_audit_unmatched"
AUDIT_SUSPICIOUS_VIEW = "guosen_limit_order_events_audit_suspicious"

EVENT_COLUMNS = [
    "exchange",
    "product_label",
    "product_code",
    "product_code_match_status",
    "instrument_type",
    "contract_codes",
    "field",
    "old_value",
    "new_value",
    "effective_date",
    "source_url",
    "source_date",
    "raw_note",
    "is_product_level",
]


def _connect() -> sqlite3.Connection:
    return DataHub.get_instance().connect_store("openctp")


def ensure_sqlite_store() -> str:
    """确保本地 SQLite 文件可写，并返回路径。"""
    hub = DataHub.get_instance()
    with hub.connect_store("openctp"):
        pass
    return hub._get_sqlite_store("openctp").path()


def save_table(df: pd.DataFrame) -> str:
    """把抓取到的表格保存到本地 SQLite。"""
    hub = DataHub.get_instance()
    path = hub._get_sqlite_store("openctp").path()
    with hub.connect_store("openctp") as conn:
        df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)
    logger.info("已写入本地 SQLite: %s (%d 行)", path, len(df))
    return path


def load_latest_table() -> pd.DataFrame | None:
    """读取本地缓存的最新表格。"""
    try:
        with _connect() as conn:
            tables = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (TABLE_NAME,),
            ).fetchone()
            if tables is None:
                return None
            df = pd.read_sql_query(f'SELECT * FROM "{TABLE_NAME}"', conn)
            if df.empty:
                return None
            return df
    except Exception:
        return None


def _normalise_events(events: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for event in events:
        row = {column: event.get(column) for column in EVENT_COLUMNS}
        contract_codes = row.get("contract_codes")
        if isinstance(contract_codes, str):
            row["contract_codes"] = contract_codes
        elif contract_codes is None:
            row["contract_codes"] = "[]"
        else:
            row["contract_codes"] = json.dumps(list(contract_codes), ensure_ascii=False)
        row["instrument_type"] = row.get("instrument_type") or "future"
        row["product_code_match_status"] = row.get("product_code_match_status") or ""
        rows.append(row)
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


def save_events(events: list[dict[str, Any]]) -> str:
    """把解析后的调整/基线事件保存到本地 SQLite。"""
    hub = DataHub.get_instance()
    path = hub._get_sqlite_store("openctp").path()
    df = _normalise_events(events)
    with hub.connect_store("openctp") as conn:
        df.to_sql(EVENTS_TABLE_NAME, conn, if_exists="replace", index=False)
        ensure_event_audit_views(conn)
    logger.info("已写入本地 SQLite 事件表: %s (%d 行)", path, len(df))
    return path


def ensure_event_audit_views(conn: sqlite3.Connection) -> None:
    """创建固定审计视图，方便人工检查 Guosen 清洗质量。"""
    conn.execute(f'DROP VIEW IF EXISTS "{AUDIT_SUMMARY_VIEW}"')
    conn.execute(f'DROP VIEW IF EXISTS "{AUDIT_UNMATCHED_VIEW}"')
    conn.execute(f'DROP VIEW IF EXISTS "{AUDIT_SUSPICIOUS_VIEW}"')
    conn.execute(
        f"""
        CREATE VIEW "{AUDIT_SUMMARY_VIEW}" AS
        SELECT
            exchange,
            field,
            instrument_type,
            product_code_match_status,
            COUNT(*) AS row_count,
            COUNT(DISTINCT product_label) AS product_label_count,
            COUNT(DISTINCT product_code) AS product_code_count,
            MIN(COALESCE(effective_date, source_date)) AS min_effective_or_source_date,
            MAX(COALESCE(effective_date, source_date)) AS max_effective_or_source_date
        FROM "{EVENTS_TABLE_NAME}"
        GROUP BY exchange, field, instrument_type, product_code_match_status
        """
    )
    conn.execute(
        f"""
        CREATE VIEW "{AUDIT_UNMATCHED_VIEW}" AS
        SELECT
            exchange,
            product_label,
            product_code,
            instrument_type,
            field,
            contract_codes,
            new_value,
            effective_date,
            source_date,
            raw_note,
            COUNT(*) AS row_count
        FROM "{EVENTS_TABLE_NAME}"
        WHERE product_code_match_status != 'matched'
        GROUP BY
            exchange, product_label, product_code, instrument_type, field,
            contract_codes, new_value, effective_date, source_date, raw_note
        ORDER BY row_count DESC, exchange, product_label, field
        """
    )
    conn.execute(
        f"""
        CREATE VIEW "{AUDIT_SUSPICIOUS_VIEW}" AS
        SELECT *
        FROM "{EVENTS_TABLE_NAME}"
        WHERE
            product_label IS NULL
            OR product_code IS NULL
            OR lower(product_label) IN ('', 'nan', 'none')
            OR lower(product_code) IN ('', 'nan', 'none')
            OR new_value IS NULL
            OR field IS NULL
            OR instrument_type NOT IN ('future', 'option', 'unknown')
        ORDER BY exchange, product_label, field, effective_date, contract_codes
        """
    )


def load_latest_events() -> pd.DataFrame | None:
    """读取本地缓存的最新解析事件表。"""
    try:
        with _connect() as conn:
            table_exists = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (EVENTS_TABLE_NAME,),
            ).fetchone()
            if table_exists is None:
                return None
            df = pd.read_sql_query(f'SELECT * FROM "{EVENTS_TABLE_NAME}"', conn)
            if df.empty:
                return None
            return df
    except Exception:
        return None


def load_latest_source_metadata() -> tuple[str, str] | None:
    """从本地缓存读取最新的 source_url / source_date。"""
    try:
        with _connect() as conn:
            table_exists = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (TABLE_NAME,),
            ).fetchone()
            if table_exists is None:
                return None
            row = conn.execute(
                f"""
                SELECT source_url, source_date
                FROM "{TABLE_NAME}"
                WHERE source_url IS NOT NULL AND source_date IS NOT NULL
                ORDER BY source_date DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return str(row["source_url"]), str(row["source_date"])
    except Exception:
        return None


def sync_sqlite_store(
    url: str | None = None,
    *,
    source_url: str | None = None,
    source_date: str | None = None,
) -> pd.DataFrame:
    """抓取远端表格并同步原始表和解析事件表到本地 SQLite。"""
    from tools.data.field_history import save_historical_field_records

    from ._analysis import events_to_historical_field_records, parse_events_from_df

    if url is None and source_url is None:
        from . import fetch_table as package_fetch_table

        df = package_fetch_table()
    else:
        from ._source import fetch_table

        df = fetch_table(url=url, source_url=source_url, source_date=source_date)
    save_table(df)
    events = parse_events_from_df(df)
    save_events(events)
    save_historical_field_records(
        events_to_historical_field_records(events),
        replace_provider="Guosen",
        replace_source_key="Guosen/LimitOrderVolume",
    )
    return df


def load_source_metadata() -> tuple[str, str]:
    """优先从远端发现，失败时回退到本地缓存，最后回退到静态快照。"""
    try:
        from ._source import discover_source_url

        source_url, source_date = discover_source_url()
        return source_url, source_date.isoformat() if source_date is not None else ""
    except Exception as remote_exc:
        logger.info("远端来源发现失败，尝试本地缓存: %s", remote_exc)

    cached = load_latest_source_metadata()
    if cached is not None:
        return cached
    logger.error("本地缓存不可用: %s", Settings.CACHE_DB_PATH)
    raise RuntimeError("无法获取数据来源的 URL 和日期，请检查网络连接或本地缓存。")
