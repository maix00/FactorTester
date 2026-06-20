"""从 OpenCTP products 端点同步品种列表到本地 SQLite。

数据源：http://dict.openctp.cn/products
raw 表：src_openctp_products（unifieddata.sqlite）— 增量 INSERT，永不删除
  - 主键：(ExchangeID, ProductID)
  - LatestVisitDate：该品种最后一次在 API 中出现的时间（退市品种不会更新）
VIEW：source_products（统一视图）、cnfutures_list（仅期货）
访问注册：sources.visits（source_key = "OpenCTP/products/source_products"）
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from typing import Any

import settings as Settings
from tools.data.hub import DataHub

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SOURCE_KEY = "OpenCTP/products/source_products"
SOURCE_LABEL = "OpenCTP 品种列表"
RAW_TABLE_NAME = "src_openctp_products"
SOURCE_VIEW_NAME = "source_products"
LEGACY_TABLE_NAME = "cnproducts_list"
LEGACY_VIEW_NAME = "cnfutures_list"

# 与 http://dict.openctp.cn/products 返回字段一一对应
# ProductClass: 详见 http://openctp.cn/dc_products.html
COLUMNS: dict[str, str] = {
    "ExchangeID":   "TEXT NOT NULL",   # 交易所代码
    "ProductID":    "TEXT NOT NULL",   # 品种代码
    "ProductName":  "TEXT NOT NULL",   # 品种中文名
    "ProductClass": "TEXT NOT NULL",   # 产品类型（期货/期权/组合/股票/基金/债券）
}
COLUMN_ORDER = list(COLUMNS)


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    Settings.CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(Settings.CACHE_DB_PATH)
    conn.row_factory = sqlite3.Row
    cols_ddl = ", ".join(
        f'"{name}" {definition}' for name, definition in COLUMNS.items()
    )
    existing_raw = conn.execute(
        "SELECT type FROM sqlite_master WHERE name=?",
        (RAW_TABLE_NAME,),
    ).fetchone()
    existing_legacy = conn.execute(
        "SELECT type FROM sqlite_master WHERE name=?",
        (LEGACY_TABLE_NAME,),
    ).fetchone()
    if existing_legacy and existing_legacy[0] == "table" and existing_raw is None:
        conn.execute(f'ALTER TABLE "{LEGACY_TABLE_NAME}" RENAME TO "{RAW_TABLE_NAME}"')
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{RAW_TABLE_NAME}" (
            {cols_ddl},
            "LatestVisitDate" TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (ExchangeID, ProductID)
        )
        """
    )
    existing_cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{RAW_TABLE_NAME}")').fetchall()}
    if 'LatestVisitDate' not in existing_cols:
        conn.execute(f'ALTER TABLE "{RAW_TABLE_NAME}" ADD COLUMN "LatestVisitDate" TEXT NOT NULL DEFAULT \'\'')
    # 规范层视图：统一产品视图 + 仅期货视图
    conn.execute(
        f"""
        CREATE VIEW IF NOT EXISTS "{SOURCE_VIEW_NAME}" AS
        SELECT *
        FROM "{RAW_TABLE_NAME}"
        ORDER BY "ExchangeID" ASC, "ProductID" ASC
        """
    )
    conn.execute(
        f"""
        CREATE VIEW IF NOT EXISTS "{LEGACY_VIEW_NAME}" AS
        SELECT *
        FROM "{RAW_TABLE_NAME}"
        WHERE "ProductClass" = '1'
        ORDER BY "ProductID" ASC
        """
    )
    if conn.execute("SELECT type FROM sqlite_master WHERE name=?", (LEGACY_TABLE_NAME,)).fetchone() is None:
        conn.execute(
            f"""
            CREATE VIEW IF NOT EXISTS "{LEGACY_TABLE_NAME}" AS
            SELECT *
            FROM "{SOURCE_VIEW_NAME}"
            """
        )
    return conn


def ensure_sqlite_store() -> str:
    """Ensure the OpenCTP product store schema exists and return its path."""
    with _connect():
        pass
    return str(Settings.CACHE_DB_PATH)


# ---------------------------------------------------------------------------
# 增量同步
# ---------------------------------------------------------------------------
def sync_products_from_openctp(*, refresh: bool = False) -> list[dict[str, Any]]:
    """从 OpenCTP /products 拉取全量品种，增量写入 raw 产品表。

    已存在的 (ExchangeID, ProductID) 跳过，不存在的才新增。
    已退市品种不会被删除，始终保留在本地。

    Returns:
        本次新增的品种 dict 列表。
    """
    from sources.OpenCTP.client import fetch_products

    ensure_sqlite_store()
    rows = fetch_products(refresh=refresh)

    if not rows:
        logger.warning("OpenCTP /products 返回空数据，跳过同步")
        return []

    today = date.today().isoformat()
    new_rows: list[dict[str, Any]] = []
    updated_count = 0

    with _connect() as conn:
        for row in rows:
            values = [row.get(col) for col in COLUMN_ORDER]
            # 先尝试 INSERT（已存在则忽略）
            cur = conn.execute(
                f"""
                INSERT OR IGNORE INTO "{RAW_TABLE_NAME}" (
                    "{'", "'.join(COLUMN_ORDER)}", "LatestVisitDate"
                ) VALUES (
                    {", ".join("?" for _ in COLUMN_ORDER)}, ?
                )
                """,
                (*values, today),
            )
            if cur.rowcount > 0:
                new_rows.append(row)
            else:
                # 已存在 → 仅更新 LatestVisitDate
                conn.execute(
                    f"""
                    UPDATE "{RAW_TABLE_NAME}"
                    SET "LatestVisitDate" = ?
                    WHERE "ExchangeID" = ? AND "ProductID" = ?
                    """,
                    (today, values[0], values[1]),
                )
                updated_count += 1

    hub = DataHub.get_instance()
    hub.record_visit(SOURCE_KEY, source_label=SOURCE_LABEL)
    logger.info(
        "src_openctp_products 同步完成：共 %d 个品种，本次新增 %d，更新日期 %d",
        len(rows),
        len(new_rows),
        updated_count,
    )
    return new_rows


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def load_products_list() -> list[dict[str, Any]]:
    """从本地 SQLite 读取已缓存的品种列表（全量，含已退市）。"""
    try:
        with _connect() as conn:
            rows = conn.execute(
                f"""
                SELECT "{'", "'.join(COLUMN_ORDER)}"
                FROM "{SOURCE_VIEW_NAME}"
                ORDER BY ExchangeID, ProductID
                """
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
