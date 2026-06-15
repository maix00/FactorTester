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
CACHE_DIR = Path(DATA_DIR) / "cache" / "localdata"
CACHE_DB_PATH = CACHE_DIR / "onlinedata.sqlite"
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
            ExchangeID TEXT,
            ProductID TEXT,
            InstrumentID TEXT NOT NULL,
            InstrumentName TEXT,
            ProductClass TEXT,
            VolumeMultiple REAL,
            PriceTick REAL,
            MinLimitOrderVolume REAL,
            MaxLimitOrderVolume REAL,
            LongMarginRatioByMoney REAL,
            LongMarginRatioByVolume REAL,
            ShortMarginRatioByMoney REAL,
            ShortMarginRatioByVolume REAL,
            OpenRatioByMoney REAL,
            OpenRatioByVolume REAL,
            CloseRatioByMoney REAL,
            CloseRatioByVolume REAL,
            CloseTodayRatioByMoney REAL,
            CloseTodayRatioByVolume REAL,
            DeliveryYear REAL,
            DeliveryMonth REAL,
            OpenDate TEXT,
            ExpireDate TEXT,
            DeliveryDate TEXT,
            UnderlyingInstrID TEXT,
            UnderlyingMultiple REAL,
            OptionsType TEXT,
            StrikePrice REAL,
            InstLifePhase TEXT,
            NormalizedInstrumentID TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (snapshot_date, InstrumentID)
        )
        """
    )
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
    """Return True if the SQLite table has at least one row (fee parquet already imported)."""
    return _contract_specs_count() > 0


def _upsert_contract_specs(specs: pd.DataFrame, *, snapshot_date: str | None = None) -> None:
    if specs.empty:
        return
    now = time.time()
    columns = [
        "snapshot_date", "ExchangeID", "ProductID", "InstrumentID", "InstrumentName",
        "ProductClass", "VolumeMultiple", "PriceTick", "MinLimitOrderVolume", "MaxLimitOrderVolume",
        "LongMarginRatioByMoney", "LongMarginRatioByVolume", "ShortMarginRatioByMoney", "ShortMarginRatioByVolume",
        "OpenRatioByMoney", "OpenRatioByVolume", "CloseRatioByMoney", "CloseRatioByVolume", "CloseTodayRatioByMoney",
        "CloseTodayRatioByVolume", "DeliveryYear", "DeliveryMonth", "OpenDate", "ExpireDate",
        "DeliveryDate", "UnderlyingInstrID", "UnderlyingMultiple", "OptionsType",
        "StrikePrice", "InstLifePhase", "NormalizedInstrumentID", "updated_at",
    ]
    insert_sql = f"""
        INSERT INTO openctp_cnfutures_contract_specs ({', '.join(columns)})
        VALUES ({', '.join('?' for _ in columns)})
        ON CONFLICT(snapshot_date, InstrumentID) DO UPDATE SET
            ExchangeID = excluded.ExchangeID,
            ProductID = excluded.ProductID,
            InstrumentName = excluded.InstrumentName,
            ProductClass = excluded.ProductClass,
            VolumeMultiple = excluded.VolumeMultiple,
            PriceTick = excluded.PriceTick,
            MinLimitOrderVolume = excluded.MinLimitOrderVolume,
            MaxLimitOrderVolume = excluded.MaxLimitOrderVolume,
            LongMarginRatioByMoney = excluded.LongMarginRatioByMoney,
            LongMarginRatioByVolume = excluded.LongMarginRatioByVolume,
            ShortMarginRatioByMoney = excluded.ShortMarginRatioByMoney,
            ShortMarginRatioByVolume = excluded.ShortMarginRatioByVolume,
            OpenRatioByMoney = excluded.OpenRatioByMoney,
            OpenRatioByVolume = excluded.OpenRatioByVolume,
            CloseRatioByMoney = excluded.CloseRatioByMoney,
            CloseRatioByVolume = excluded.CloseRatioByVolume,
            CloseTodayRatioByMoney = excluded.CloseTodayRatioByMoney,
            CloseTodayRatioByVolume = excluded.CloseTodayRatioByVolume,
            DeliveryYear = excluded.DeliveryYear,
            DeliveryMonth = excluded.DeliveryMonth,
            OpenDate = excluded.OpenDate,
            ExpireDate = excluded.ExpireDate,
            DeliveryDate = excluded.DeliveryDate,
            UnderlyingInstrID = excluded.UnderlyingInstrID,
            UnderlyingMultiple = excluded.UnderlyingMultiple,
            OptionsType = excluded.OptionsType,
            StrikePrice = excluded.StrikePrice,
            InstLifePhase = excluded.InstLifePhase,
            NormalizedInstrumentID = excluded.NormalizedInstrumentID,
            updated_at = excluded.updated_at
    """
    values = []
    for _, row in specs.iterrows():
        row_snapshot_date = str(row.get("date") or snapshot_date or date.today().strftime("%Y%m%d"))
        values.append((
            row_snapshot_date,
            _none_if_na(row.get("ExchangeID")),
            _none_if_na(row.get("ProductID") or row.get("variety_code")),
            _none_if_na(row.get("InstrumentID") or row.get("contract_code")),
            _none_if_na(row.get("InstrumentName") or row.get("contract_name")),
            _none_if_na(row.get("ProductClass")),
            _none_if_na(row.get("VolumeMultiple")),
            _none_if_na(row.get("PriceTick")),
            _none_if_na(row.get("MinLimitOrderVolume")),
            _none_if_na(row.get("MaxLimitOrderVolume")),
            _none_if_na(row.get("LongMarginRatioByMoney")),
            _none_if_na(row.get("LongMarginRatioByVolume")),
            _none_if_na(row.get("ShortMarginRatioByMoney")),
            _none_if_na(row.get("ShortMarginRatioByVolume")),
            _none_if_na(row.get("OpenRatioByMoney")),
            _none_if_na(row.get("OpenRatioByVolume")),
            _none_if_na(row.get("CloseRatioByMoney")),
            _none_if_na(row.get("CloseRatioByVolume")),
            _none_if_na(row.get("CloseTodayRatioByMoney")),
            _none_if_na(row.get("CloseTodayRatioByVolume")),
            _none_if_na(row.get("DeliveryYear")),
            _none_if_na(row.get("DeliveryMonth")),
            _none_if_na(row.get("OpenDate")),
            _none_if_na(row.get("ExpireDate")),
            _none_if_na(row.get("DeliveryDate")),
            _none_if_na(row.get("UnderlyingInstrID")),
            _none_if_na(row.get("UnderlyingMultiple")),
            _none_if_na(row.get("OptionsType")),
            _none_if_na(row.get("StrikePrice")),
            _none_if_na(row.get("InstLifePhase")),
            _none_if_na(row.get("NormalizedInstrumentID")),
            now,
        ))
    try:
        with _connect_cache() as conn:
            conn.executemany(insert_sql, values)
    except Exception:
        pass


def _write_contract_specs(rows: list[dict[str, Any]], *, snapshot_date: str | None = None) -> None:
    specs = _clean_instrument_rows(rows)
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
            ExchangeID,
            ProductID,
            InstrumentID,
            InstrumentName,
            ProductClass,
            VolumeMultiple,
            PriceTick,
            MinLimitOrderVolume,
            MaxLimitOrderVolume,
            LongMarginRatioByMoney,
            LongMarginRatioByVolume,
            ShortMarginRatioByMoney,
            ShortMarginRatioByVolume,
            OpenRatioByMoney,
            OpenRatioByVolume,
            CloseRatioByMoney,
            CloseRatioByVolume,
            CloseTodayRatioByMoney,
            CloseTodayRatioByVolume,
            DeliveryYear,
            DeliveryMonth,
            OpenDate,
            ExpireDate,
            DeliveryDate,
            UnderlyingInstrID,
            UnderlyingMultiple,
            OptionsType,
            StrikePrice,
            InstLifePhase,
            NormalizedInstrumentID
        FROM openctp_cnfutures_contract_specs
    """
    if where:
        sql += " WHERE " + where
    sql += " ORDER BY ProductID, InstrumentID"
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


def read_cnfutures_contract_specs_over_date_range(
    trading_days: list | pd.DatetimeIndex,
    *,
    variety_codes: list[str] | None = None,
    fee_data_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Read per-product contract specs aligned to a list of trading days.

    Each trading_day is forward-filled from the nearest available snapshot:
    for each date in *trading_days* we find the latest snapshot_date <= that date.
    Returns a DataFrame indexed by ``(trading_day, ProductID)`` with one row per
    (trading_day, product) combination.

    Columns returned: VolumeMultiple, PriceTick, MinLimitOrderVolume,
    LongMarginRatioByMoney, OpenRatioByMoney, OpenRatioByVolume,
    CloseRatioByMoney, CloseRatioByVolume, CloseTodayRatioByMoney,
    CloseTodayRatioByVolume.
    """
    sync_cnfutures_contract_specs_from_fee_parquet(data_dir=fee_data_dir)

    if not isinstance(trading_days, pd.DatetimeIndex):
        trading_days = pd.DatetimeIndex(trading_days)
    trading_days = trading_days.sort_values()

    date_strs = [d.strftime("%Y%m%d") for d in trading_days]

    with _connect_cache() as conn:
        # Get all distinct snapshot_dates
        all_snapshots = sorted({
            str(r["snapshot_date"])
            for r in conn.execute(
                "SELECT DISTINCT snapshot_date FROM openctp_cnfutures_contract_specs ORDER BY snapshot_date"
            ).fetchall()
        })

    if not all_snapshots:
        raise FileNotFoundError("未找到任何合约规格快照")

    # Build mapping: each trading_day → nearest snapshot_date (forward-fill)
    snap_map: dict[str, str] = {}
    snap_idx = 0
    for ds in date_strs:
        # Advance snap_idx to the last snapshot <= ds
        while snap_idx + 1 < len(all_snapshots) and all_snapshots[snap_idx + 1] <= ds:
            snap_idx += 1
        if all_snapshots[snap_idx] <= ds:
            snap_map[ds] = all_snapshots[snap_idx]
        else:
            # No snapshot on or before this date — use the earliest available
            snap_map[ds] = all_snapshots[0]

    # Build unique snapshot_dates to query
    unique_snaps = sorted(set(snap_map.values()))
    placeholders = ",".join("?" for _ in unique_snaps)
    where_clause = f"snapshot_date IN ({placeholders})"
    params = tuple(unique_snaps)

    if variety_codes:
        vc_placeholders = ",".join("?" for _ in variety_codes)
        where_clause += f" AND ProductID IN ({vc_placeholders})"
        params = params + tuple(str(vc).upper() for vc in variety_codes)

    df = _contract_specs_sql_frame(where_clause, params)
    if df.empty:
        return pd.DataFrame()

    # For each ProductID, keep the first row to dedup
    df = df.drop_duplicates(subset=["date", "ProductID"], keep="first")

    # Remap snapshot_date → trading_day
    reverse_map = {v: k for k, v in snap_map.items()}
    df["trading_day"] = df["date"].map(reverse_map)
    df["trading_day"] = pd.to_datetime(df["trading_day"], format="%Y%m%d")

    # Build aligned rows: for each (trading_day, ProductID) pair
    required_pairs = pd.DataFrame(
        [(td, vc) for td in date_strs for vc in (variety_codes or df["ProductID"].unique())],
        columns=["trading_day", "ProductID"],
    )
    required_pairs["trading_day"] = pd.to_datetime(required_pairs["trading_day"], format="%Y%m%d")
    required_pairs["ProductID"] = required_pairs["ProductID"].astype(str).str.upper()

    # Merge with actual data, forward-fill missing
    spec_cols = [
        "VolumeMultiple", "PriceTick", "MinLimitOrderVolume", "LongMarginRatioByMoney",
        "OpenRatioByMoney", "OpenRatioByVolume", "CloseRatioByMoney", "CloseRatioByVolume",
        "CloseTodayRatioByMoney", "CloseTodayRatioByVolume",
    ]
    aligned = required_pairs.merge(
        df[["trading_day", "ProductID"] + spec_cols],
        on=["trading_day", "ProductID"],
        how="left",
    )
    # Forward-fill per ProductID
    for col in spec_cols:
        if col in aligned.columns:
            aligned[col] = aligned.groupby("ProductID")[col].ffill()

    # Fill remaining NaN with safe defaults
    defaults = {
        "VolumeMultiple": 1.0,
        "PriceTick": 0.0,
        "MinLimitOrderVolume": 1.0,
        "LongMarginRatioByMoney": 1.0,
        "OpenRatioByMoney": 0.0,
        "OpenRatioByVolume": 0.0,
        "CloseRatioByMoney": 0.0,
        "CloseRatioByVolume": 0.0,
        "CloseTodayRatioByMoney": 0.0,
        "CloseTodayRatioByVolume": 0.0,
    }
    for col, default in defaults.items():
        if col in aligned.columns:
            aligned[col] = aligned[col].fillna(default)

    aligned = aligned.set_index(["trading_day", "ProductID"]).sort_index()
    return aligned


def read_latest_cnfutures_product_specs(*, fee_data_dir: str | Path | None = None) -> pd.DataFrame:
    """Read latest product-level display specs from contract specs in SQLite."""
    df = read_cnfutures_contract_specs_for_date(
        None,
        allow_latest_fallback=True,
        fee_data_dir=fee_data_dir,
    )
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["ProductID"], keep="first").copy()
    df = df.rename(columns={"InstrumentID": "representative_contract_code"})
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


def _clean_instrument_rows(rows: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    """Clean OpenCTP instrument rows: coerce numerics, strip IDs, add NormalizedInstrumentID."""
    df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return df
    numeric_cols = [
        "VolumeMultiple", "PriceTick", "MinLimitOrderVolume", "MaxLimitOrderVolume",
        "LongMarginRatioByMoney", "LongMarginRatioByVolume",
        "ShortMarginRatioByMoney", "ShortMarginRatioByVolume",
        "OpenRatioByMoney", "OpenRatioByVolume",
        "CloseRatioByMoney", "CloseRatioByVolume",
        "CloseTodayRatioByMoney", "CloseTodayRatioByVolume",
        "DeliveryYear", "DeliveryMonth",
        "UnderlyingMultiple", "StrikePrice",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["NormalizedInstrumentID"] = df["InstrumentID"].map(normalise_instrument_code)
    for col in ["ExchangeID", "InstrumentID", "InstrumentName", "ProductID"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    if "ProductID" in df.columns:
        df["ProductID"] = df["ProductID"].str.upper()
    df = df[df["NormalizedInstrumentID"].str.len() > 0]
    return df.reset_index(drop=True)
