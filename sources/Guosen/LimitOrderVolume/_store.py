"""本地 SQLite 存储：国信期货每笔下单数量限制表。"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import pandas as pd

from tools.data.hub import DataHub

logger = logging.getLogger(__name__)

TABLE_NAME = "guosen_limit_order_volume"


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
    """抓取远端表格并同步到本地 SQLite。"""
    from ._source import fetch_table

    df = fetch_table(url=url, source_url=source_url, source_date=source_date)
    save_table(df)
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
    logger.error("本地缓存不可用: %s", CACHE_DB_PATH)
    raise RuntimeError("无法获取数据来源的 URL 和日期，请检查网络连接或本地缓存。")
