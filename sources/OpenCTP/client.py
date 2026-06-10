"""OpenCTP online field-data HTTP client.

The OpenCTP data center exposes five public JSON endpoints:
markets, products, instruments, prices, and times.  This module keeps the
provider-specific CTP field names at the boundary and offers small normalized
DataFrames for local consumers that need stable snake_case columns.

This package deliberately does not manage local OHLCV/K-line files.  Local
price storage remains under ``sources.LocalCNFutures``; OpenCTP is only the
online reference source for exchange/product/contract specs, live quotes, and
trading sessions.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from scripts.data_dir import DATA_DIR


BASE_URL = "http://dict.openctp.cn"
CACHE_DIR = Path(DATA_DIR) / "cache" / "openctp"
CACHE_DB_PATH = CACHE_DIR / "openctp.sqlite"
ENDPOINTS = {
    "markets": "/markets",
    "products": "/products",
    "instruments": "/instruments",
    "prices": "/prices",
    "times": "/times",
}


def _comma(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return ",".join(str(item) for item in value)
    except TypeError:
        return str(value)


def _cache_key(query: dict[str, str]) -> str:
    return urlencode(sorted(query.items()))


def _connect_cache() -> sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS openctp_responses (
            endpoint TEXT NOT NULL,
            query_key TEXT NOT NULL,
            query_json TEXT NOT NULL,
            url TEXT NOT NULL,
            data_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (endpoint, query_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS openctp_cnfutures_contract_specs (
            snapshot_date TEXT NOT NULL,
            exchange TEXT,
            product_id TEXT,
            variety_name TEXT,
            instrument_id TEXT NOT NULL,
            instrument_name TEXT,
            product_class TEXT,
            multiplier REAL,
            min_tick REAL,
            min_trade_quantity REAL,
            max_trade_quantity REAL,
            long_margin_ratio REAL,
            long_margin_fixed REAL,
            short_margin_ratio REAL,
            short_margin_fixed REAL,
            open_ratio REAL,
            open_fixed REAL,
            close_ratio REAL,
            close_fixed REAL,
            closetoday_ratio REAL,
            closetoday_fixed REAL,
            price REAL,
            volume REAL,
            open_interest REAL,
            open_total_fee REAL,
            close_total_fee REAL,
            closetoday_total_fee REAL,
            delivery_year REAL,
            delivery_month REAL,
            open_date TEXT,
            expire_date TEXT,
            delivery_date TEXT,
            underlying_instrument_id TEXT,
            underlying_multiple REAL,
            options_type TEXT,
            strike_price REAL,
            life_phase TEXT,
            contract_key TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (snapshot_date, instrument_id)
        )
        """
    )
    _ensure_columns(conn, "openctp_cnfutures_contract_specs", {
        "variety_name": "TEXT",
        "price": "REAL",
        "volume": "REAL",
        "open_interest": "REAL",
        "open_total_fee": "REAL",
        "close_total_fee": "REAL",
        "closetoday_total_fee": "REAL",
    })
    return conn


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {
        str(row["name"])
        for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')


def ensure_sqlite_store() -> str:
    """Ensure the OpenCTP SQLite store exists and return its path."""
    with _connect_cache():
        pass
    sync_cnfutures_contract_specs_from_fee_parquet()
    return str(CACHE_DB_PATH)


def _read_cache(endpoint: str, query: dict[str, str]) -> list[dict[str, Any]] | None:
    try:
        with _connect_cache() as conn:
            row = conn.execute(
                "SELECT data_json FROM openctp_responses WHERE endpoint = ? AND query_key = ?",
                (endpoint, _cache_key(query)),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _write_cache(endpoint: str, query: dict[str, str], data: list[dict[str, Any]], *, url: str) -> None:
    try:
        with _connect_cache() as conn:
            conn.execute(
                """
                INSERT INTO openctp_responses
                    (endpoint, query_key, query_json, url, data_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(endpoint, query_key) DO UPDATE SET
                    query_json = excluded.query_json,
                    url = excluded.url,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at
                """,
                (
                    endpoint,
                    _cache_key(query),
                    json.dumps(query, ensure_ascii=False, sort_keys=True),
                    url,
                    json.dumps(data, ensure_ascii=False),
                    time.time(),
                ),
            )
    except Exception:
        pass


def _request(endpoint: str, *, refresh: bool = False, **params: Any) -> list[dict[str, Any]]:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown OpenCTP endpoint: {endpoint!r}")
    query = {
        key: _comma(value)
        for key, value in params.items()
        if value is not None and _comma(value) not in (None, "")
    }
    if not refresh:
        cached = _read_cache(endpoint, query)
        if cached is not None:
            return cached
    url = BASE_URL + ENDPOINTS[endpoint]
    if query:
        url += "?" + urlencode(query)
    with urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if int(payload.get("rsp_code", -1)) != 0:
        raise RuntimeError(f"OpenCTP {endpoint} failed: {payload.get('rsp_message')}")
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise TypeError(f"OpenCTP {endpoint} returned non-list data")
    _write_cache(endpoint, query, data, url=url)
    return data


def _frame(endpoint: str, **params: Any) -> pd.DataFrame:
    return pd.DataFrame(_request(endpoint, **params))


def fetch_markets(*, areas: Any = None, refresh: bool = False) -> list[dict[str, Any]]:
    return _request("markets", areas=areas, refresh=refresh)


def fetch_products(
    *,
    types: Any = None,
    areas: Any = None,
    markets: Any = None,
    products: Any = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    return _request("products", types=types, areas=areas, markets=markets, products=products, refresh=refresh)


def fetch_instruments(
    *,
    types: Any = None,
    areas: Any = None,
    markets: Any = None,
    products: Any = None,
    instruments: Any = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    rows = _request(
        "instruments",
        types=types,
        areas=areas,
        markets=markets,
        products=products,
        instruments=instruments,
        refresh=refresh,
    )
    _write_contract_specs(rows)
    return rows


def fetch_prices(
    *,
    types: Any = None,
    areas: Any = None,
    markets: Any = None,
    products: Any = None,
    instruments: Any = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    return _request(
        "prices",
        types=types,
        areas=areas,
        markets=markets,
        products=products,
        instruments=instruments,
        refresh=refresh,
    )


def fetch_times(
    *,
    types: Any = None,
    areas: Any = None,
    markets: Any = None,
    products: Any = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    return _request("times", types=types, areas=areas, markets=markets, products=products, refresh=refresh)


def frame_markets(**params: Any) -> pd.DataFrame:
    return _frame("markets", **params)


def frame_products(**params: Any) -> pd.DataFrame:
    return _frame("products", **params)


def frame_instruments(**params: Any) -> pd.DataFrame:
    return _frame("instruments", **params)


def frame_prices(**params: Any) -> pd.DataFrame:
    return _frame("prices", **params)


def frame_times(**params: Any) -> pd.DataFrame:
    return _frame("times", **params)


def normalise_instrument_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = text.split(".")[0]
    return re.sub(r"[^A-Z0-9]", "", text)


def _none_if_na(value: Any) -> Any:
    return None if pd.isna(value) else value


def _contract_specs_count() -> int:
    with _connect_cache() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM openctp_cnfutures_contract_specs").fetchone()
    return int(row["n"])


def _contract_specs_has_fee_snapshot_columns() -> bool:
    with _connect_cache() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM openctp_cnfutures_contract_specs
            WHERE variety_name IS NOT NULL
               OR open_interest IS NOT NULL
               OR open_total_fee IS NOT NULL
            """
        ).fetchone()
    return int(row["n"]) > 0


def _upsert_contract_specs(specs: pd.DataFrame, *, snapshot_date: str | None = None) -> None:
    if specs.empty:
        return
    now = time.time()
    columns = [
        "snapshot_date", "exchange", "product_id", "variety_name", "instrument_id", "instrument_name",
        "product_class", "multiplier", "min_tick", "min_trade_quantity", "max_trade_quantity",
        "long_margin_ratio", "long_margin_fixed", "short_margin_ratio", "short_margin_fixed",
        "open_ratio", "open_fixed", "close_ratio", "close_fixed", "closetoday_ratio",
        "closetoday_fixed", "price", "volume", "open_interest", "open_total_fee",
        "close_total_fee", "closetoday_total_fee", "delivery_year", "delivery_month", "open_date", "expire_date",
        "delivery_date", "underlying_instrument_id", "underlying_multiple", "options_type",
        "strike_price", "life_phase", "contract_key", "updated_at",
    ]
    insert_sql = f"""
        INSERT INTO openctp_cnfutures_contract_specs ({', '.join(columns)})
        VALUES ({', '.join('?' for _ in columns)})
        ON CONFLICT(snapshot_date, instrument_id) DO UPDATE SET
            exchange = excluded.exchange,
            product_id = excluded.product_id,
            variety_name = excluded.variety_name,
            instrument_name = excluded.instrument_name,
            product_class = excluded.product_class,
            multiplier = excluded.multiplier,
            min_tick = excluded.min_tick,
            min_trade_quantity = excluded.min_trade_quantity,
            max_trade_quantity = excluded.max_trade_quantity,
            long_margin_ratio = excluded.long_margin_ratio,
            long_margin_fixed = excluded.long_margin_fixed,
            short_margin_ratio = excluded.short_margin_ratio,
            short_margin_fixed = excluded.short_margin_fixed,
            open_ratio = excluded.open_ratio,
            open_fixed = excluded.open_fixed,
            close_ratio = excluded.close_ratio,
            close_fixed = excluded.close_fixed,
            closetoday_ratio = excluded.closetoday_ratio,
            closetoday_fixed = excluded.closetoday_fixed,
            price = excluded.price,
            volume = excluded.volume,
            open_interest = excluded.open_interest,
            open_total_fee = excluded.open_total_fee,
            close_total_fee = excluded.close_total_fee,
            closetoday_total_fee = excluded.closetoday_total_fee,
            delivery_year = excluded.delivery_year,
            delivery_month = excluded.delivery_month,
            open_date = excluded.open_date,
            expire_date = excluded.expire_date,
            delivery_date = excluded.delivery_date,
            underlying_instrument_id = excluded.underlying_instrument_id,
            underlying_multiple = excluded.underlying_multiple,
            options_type = excluded.options_type,
            strike_price = excluded.strike_price,
            life_phase = excluded.life_phase,
            contract_key = excluded.contract_key,
            updated_at = excluded.updated_at
    """
    values = []
    for _, row in specs.iterrows():
        row_snapshot_date = str(row.get("date") or snapshot_date or date.today().strftime("%Y%m%d"))
        values.append((
            row_snapshot_date,
            _none_if_na(row.get("exchange")),
            _none_if_na(row.get("variety_code") or row.get("product_id")),
            _none_if_na(row.get("variety_name")),
            _none_if_na(row.get("contract_code") or row.get("instrument_id")),
            _none_if_na(row.get("contract_name") or row.get("instrument_name")),
            _none_if_na(row.get("product_class")),
            _none_if_na(row.get("multiplier")),
            _none_if_na(row.get("min_tick")),
            _none_if_na(row.get("min_trade_quantity")),
            _none_if_na(row.get("max_trade_quantity")),
            _none_if_na(row.get("long_margin_ratio")),
            _none_if_na(row.get("long_margin_fixed")),
            _none_if_na(row.get("short_margin_ratio")),
            _none_if_na(row.get("short_margin_fixed")),
            _none_if_na(row.get("open_ratio")),
            _none_if_na(row.get("open_fixed")),
            _none_if_na(row.get("close_ratio")),
            _none_if_na(row.get("close_fixed")),
            _none_if_na(row.get("closetoday_ratio")),
            _none_if_na(row.get("closetoday_fixed")),
            _none_if_na(row.get("price")),
            _none_if_na(row.get("volume")),
            _none_if_na(row.get("open_interest")),
            _none_if_na(row.get("open_total_fee")),
            _none_if_na(row.get("close_total_fee")),
            _none_if_na(row.get("closetoday_total_fee")),
            _none_if_na(row.get("delivery_year")),
            _none_if_na(row.get("delivery_month")),
            _none_if_na(row.get("open_date")),
            _none_if_na(row.get("expire_date")),
            _none_if_na(row.get("delivery_date")),
            _none_if_na(row.get("underlying_instrument_id")),
            _none_if_na(row.get("underlying_multiple")),
            _none_if_na(row.get("options_type")),
            _none_if_na(row.get("strike_price")),
            _none_if_na(row.get("life_phase")),
            _none_if_na(row.get("contract_key")),
            now,
        ))
    try:
        with _connect_cache() as conn:
            conn.executemany(insert_sql, values)
    except Exception:
        pass


def _write_contract_specs(rows: list[dict[str, Any]], *, snapshot_date: str | None = None) -> None:
    specs = instruments_to_contract_specs(rows)
    _upsert_contract_specs(specs, snapshot_date=snapshot_date)


def upsert_cnfutures_contract_specs(specs: pd.DataFrame, *, snapshot_date: str | None = None) -> None:
    """Upsert normalized CN futures contract specs into SQLite."""
    _upsert_contract_specs(specs, snapshot_date=snapshot_date)


def sync_cnfutures_contract_specs_from_fee_parquet(
    *,
    data_dir: str | Path | None = None,
    force: bool = False,
) -> int:
    """Import existing LocalCNFutures fee parquet snapshots into the SQLite typed table."""
    if not force and _contract_specs_count() > 0 and _contract_specs_has_fee_snapshot_columns():
        return 0
    try:
        from sources.LocalCNFutures import FeeData
    except Exception:
        return 0
    source_dir = Path(data_dir) if data_dir is not None else getattr(FeeData, "_DATA_DIR", None)
    if source_dir is None:
        return 0
    paths = sorted(Path(source_dir).glob("fees_contracts_2*.parquet"))
    imported = 0
    for path in paths:
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if df.empty:
            continue
        if "date" not in df.columns:
            match = re.fullmatch(r"fees_contracts_(\d{8})\.parquet", path.name)
            df = df.copy()
            df["date"] = match.group(1) if match else date.today().strftime("%Y%m%d")
        _upsert_contract_specs(df)
        imported += len(df)
    return imported


def _contract_specs_sql_frame(where: str = "", params: tuple[Any, ...] = ()) -> pd.DataFrame:
    sql = """
        SELECT
            snapshot_date AS date,
            exchange,
            product_id AS variety_code,
            variety_name,
            instrument_id AS contract_code,
            instrument_name AS contract_name,
            product_class,
            multiplier,
            min_tick,
            min_trade_quantity,
            max_trade_quantity,
            long_margin_ratio,
            long_margin_fixed,
            short_margin_ratio,
            short_margin_fixed,
            open_ratio,
            open_fixed,
            close_ratio,
            close_fixed,
            closetoday_ratio,
            closetoday_fixed,
            price,
            volume,
            open_interest,
            open_total_fee,
            close_total_fee,
            closetoday_total_fee,
            delivery_year,
            delivery_month,
            open_date,
            expire_date,
            delivery_date,
            underlying_instrument_id,
            underlying_multiple,
            options_type,
            strike_price,
            life_phase,
            contract_key
        FROM openctp_cnfutures_contract_specs
    """
    if where:
        sql += " WHERE " + where
    sql += " ORDER BY product_id, instrument_id"
    with _connect_cache() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def read_cnfutures_contract_specs_for_date(
    trading_day: Any | None = None,
    *,
    allow_latest_fallback: bool = True,
    fee_data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Read contract-level CN futures specs from SQLite with as-of semantics."""
    sync_cnfutures_contract_specs_from_fee_parquet(data_dir=fee_data_dir)
    target = pd.Timestamp(trading_day).strftime("%Y%m%d") if trading_day is not None else date.today().strftime("%Y%m%d")
    with _connect_cache() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT snapshot_date
            FROM openctp_cnfutures_contract_specs
            WHERE snapshot_date <= ?
            ORDER BY snapshot_date DESC
            """,
            (target,),
        ).fetchall()
        source_date = str(rows[0]["snapshot_date"]) if rows else None
        source = "historical_snapshot" if source_date == target else "historical_forward_fill"
        if source_date is None and allow_latest_fallback:
            latest = conn.execute(
                "SELECT MAX(snapshot_date) AS snapshot_date FROM openctp_cnfutures_contract_specs"
            ).fetchone()
            source_date = str(latest["snapshot_date"]) if latest and latest["snapshot_date"] else None
            source = "latest_inferred"
    if source_date is None:
        raise FileNotFoundError(f"未找到 {target} 或更早的合约级费率快照")
    df = _contract_specs_sql_frame("snapshot_date = ?", (source_date,))
    df.attrs["fee_source"] = source
    df.attrs["fee_source_date"] = source_date
    df.attrs["requested_fee_date"] = target
    return df


def read_latest_cnfutures_product_specs(*, fee_data_dir: str | Path | None = None) -> pd.DataFrame:
    """Read latest product-level display specs from contract specs in SQLite."""
    df = read_cnfutures_contract_specs_for_date(
        None,
        allow_latest_fallback=True,
        fee_data_dir=fee_data_dir,
    )
    if df.empty:
        return df
    if "open_interest" in df.columns:
        df = df.sort_values("open_interest", ascending=False, na_position="last")
    df = df.drop_duplicates(subset=["variety_code"], keep="first").copy()
    df = df.rename(columns={"contract_code": "representative_contract_code"})
    return df.reset_index(drop=True)


def list_sqlite_tables() -> list[dict[str, Any]]:
    with _connect_cache() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        result = []
        for row in rows:
            name = str(row["name"])
            count = conn.execute(f'SELECT COUNT(*) AS n FROM "{name}"').fetchone()["n"]
            result.append({"name": name, "rows": int(count)})
    return result


def read_sqlite_table(table_name: str, *, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    allowed = {item["name"] for item in list_sqlite_tables()}
    if table_name not in allowed:
        raise ValueError(f"Unknown OpenCTP table: {table_name}")
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    with _connect_cache() as conn:
        columns = [row["name"] for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
        count = int(conn.execute(f'SELECT COUNT(*) AS n FROM "{table_name}"').fetchone()["n"])
        rows = conn.execute(
            f'SELECT * FROM "{table_name}" LIMIT ? OFFSET ?',
            (limit, offset),
        ).fetchall()
    return {
        "table": table_name,
        "columns": columns,
        "rows": [dict(row) for row in rows],
        "total": count,
        "limit": limit,
        "offset": offset,
        "database": str(CACHE_DB_PATH),
    }


def instruments_to_contract_specs(rows: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    """Convert OpenCTP instrument rows to local contract spec columns."""
    df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame()

    out = pd.DataFrame({
        "exchange": df.get("ExchangeID"),
        "contract_code": df.get("InstrumentID"),
        "contract_name": df.get("InstrumentName"),
        "variety_code": df.get("ProductID"),
        "product_class": df.get("ProductClass"),
        "multiplier": df.get("VolumeMultiple"),
        "min_tick": df.get("PriceTick"),
        "min_trade_quantity": df.get("MinLimitOrderVolume"),
        "max_trade_quantity": df.get("MaxLimitOrderVolume"),
        "long_margin_ratio": df.get("LongMarginRatioByMoney"),
        "long_margin_fixed": df.get("LongMarginRatioByVolume"),
        "short_margin_ratio": df.get("ShortMarginRatioByMoney"),
        "short_margin_fixed": df.get("ShortMarginRatioByVolume"),
        "open_ratio": df.get("OpenRatioByMoney"),
        "open_fixed": df.get("OpenRatioByVolume"),
        "close_ratio": df.get("CloseRatioByMoney"),
        "close_fixed": df.get("CloseRatioByVolume"),
        "closetoday_ratio": df.get("CloseTodayRatioByMoney"),
        "closetoday_fixed": df.get("CloseTodayRatioByVolume"),
        "delivery_year": df.get("DeliveryYear"),
        "delivery_month": df.get("DeliveryMonth"),
        "open_date": df.get("OpenDate"),
        "expire_date": df.get("ExpireDate"),
        "delivery_date": df.get("DeliveryDate"),
        "underlying_instrument_id": df.get("UnderlyingInstrID"),
        "underlying_multiple": df.get("UnderlyingMultiple"),
        "options_type": df.get("OptionsType"),
        "strike_price": df.get("StrikePrice"),
        "life_phase": df.get("InstLifePhase"),
    })
    for col in [
        "multiplier", "min_tick", "min_trade_quantity", "max_trade_quantity",
        "long_margin_ratio", "long_margin_fixed", "short_margin_ratio", "short_margin_fixed",
        "open_ratio", "open_fixed", "close_ratio", "close_fixed",
        "closetoday_ratio", "closetoday_fixed", "underlying_multiple", "strike_price",
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out["contract_key"] = out["contract_code"].map(normalise_instrument_code)
    out["variety_code"] = out["variety_code"].astype(str).str.strip().str.upper()
    out["exchange"] = out["exchange"].astype(str).str.strip()
    out["contract_code"] = out["contract_code"].astype(str).str.strip()
    out["contract_name"] = out["contract_name"].astype(str).str.strip()
    out = out[out["contract_key"].str.len() > 0]
    return out.reset_index(drop=True)
