"""Update LocalCNFutures daily bars from external daily data sources.

The canonical local daily table is ``SOURCE_DATA_DIR/data_dayk.parquet``.
This module keeps the parsing and validation logic reusable so scripts,
tests, and future Local data-source bundle code do not need to duplicate the
same AKShare column mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from io import BytesIO, StringIO
import zipfile
import time
from typing import Iterable, Sequence
import concurrent.futures

import numpy as np
import pandas as pd
import requests

from sources.LocalCNFutures import SOURCE_DATA_DIR
from sources.LocalCNFutures.contract_files import (
    contract_uid_from_exchange_contract,
)


DAYK_PATH = Path(SOURCE_DATA_DIR) / "data_dayk.parquet"
MINUTE_DATA_DIR = Path(SOURCE_DATA_DIR) / "data_mink"
DEFAULT_MARKETS = ("DCE", "SHFE", "CZCE", "CFFEX", "INE", "GFEX")

DAYK_COLUMNS = [
    "trading_day",
    "trade_time",
    "trade_timestamp",
    "exchange_id",
    "instrument_id",
    "unique_instrument_id",
    "open_price",
    "highest_price",
    "lowest_price",
    "close_price",
    "settlement_price",
    "upper_limit_price",
    "lower_limit_price",
    "pre_settlement_price",
    "volume",
    "turnover",
    "open_interest",
    "insert_time",
    "pre_close_price",
    "day_session_price",
    "product_id",
    "twap",
    "vwap",
]

_SYMBOL_RE = re.compile(r"^([A-Za-z]+)(\d+[A-Za-z]?)$")
_EXCHANGE_ID_TO_SHORT = {
    "DCE": "DCE",
    "CZCE": "CZC",
    "INE": "INE",
    "SHFE": "SHF",
    "CFFEX": "CFE",
    "GFEX": "GFE",
}


@dataclass(frozen=True)
class DayKUpdateReport:
    path: Path
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    markets: tuple[str, ...]
    fetched_rows: int
    written_rows: int
    validation_mismatches: tuple[dict[str, object], ...]
    warnings: tuple[str, ...]


def normalize_akshare_daily_frame(raw: pd.DataFrame, market: str) -> pd.DataFrame:
    """Normalize an AKShare daily futures frame to LocalCNFutures dayk schema."""

    if raw.empty:
        return pd.DataFrame(columns=DAYK_COLUMNS)
    market = market.upper()
    df = raw.copy()
    df.columns = [str(col).strip().lower() for col in df.columns]
    if "symbol" not in df.columns or "date" not in df.columns:
        raise ValueError(f"{market} daily data missing symbol/date columns: {list(raw.columns)}")

    trading_day = parse_akshare_trade_dates(df["date"])
    unique_ids: list[str] = []
    valid_indices: list[int] = []
    for idx, (symbol, day) in enumerate(zip(df["symbol"].astype(str), trading_day, strict=False)):
        try:
            uid = normalize_contract_uid(symbol, market, pd.Timestamp(day))
        except ValueError:
            continue
        valid_indices.append(idx)
        unique_ids.append(uid)
    if not valid_indices:
        return pd.DataFrame(columns=DAYK_COLUMNS)
    df = df.iloc[valid_indices].reset_index(drop=True)
    trading_day = trading_day.iloc[valid_indices].reset_index(drop=True)

    out = pd.DataFrame(index=df.index)
    out["trading_day"] = trading_day
    out["trade_time"] = trading_day
    out["trade_timestamp"] = trading_day.astype("int64") // 1_000_000
    out["exchange_id"] = market
    out["instrument_id"] = df["symbol"].astype(str)
    out["unique_instrument_id"] = unique_ids
    out["open_price"] = _numeric_col(df, "open")
    out["highest_price"] = _numeric_col(df, "high")
    out["lowest_price"] = _numeric_col(df, "low")
    out["close_price"] = _numeric_col(df, "close")
    out["settlement_price"] = _numeric_col(df, "settle")
    out["upper_limit_price"] = _numeric_col(df, "upper_limit")
    out["lower_limit_price"] = _numeric_col(df, "lower_limit")
    out["pre_settlement_price"] = _numeric_col(df, "pre_settle")
    out["volume"] = _numeric_col(df, "volume")
    out["turnover"] = _numeric_col(df, "turnover")
    out["open_interest"] = _numeric_col(df, "open_interest")
    out["insert_time"] = pd.Timestamp.now()
    out["pre_close_price"] = _numeric_col(df, "pre_close")
    out["day_session_price"] = np.nan
    out["product_id"] = [uid.split("|")[2] for uid in unique_ids]
    out["twap"] = out[["open_price", "highest_price", "lowest_price", "close_price"]].mean(axis=1)
    volume = out["volume"].replace(0, np.nan)
    out["vwap"] = out["turnover"] / volume
    return out.reindex(columns=DAYK_COLUMNS)


def normalize_contract_symbol(symbol: str, market: str, trading_day: pd.Timestamp) -> tuple[str, str]:
    """Return ``(product_id, YYMM contract code)`` for an exchange symbol."""

    uid = normalize_contract_uid(symbol, market, trading_day)
    _, _, product_id, contract_code = uid.split("|", 3)
    return product_id, contract_code


def normalize_contract_uid(symbol: str, market: str, trading_day: pd.Timestamp) -> str:
    """Return LocalCNFutures contract UID for an exchange symbol."""

    compact = symbol.strip().upper().replace(" ", "")
    market = market.upper()
    match = _SYMBOL_RE.match(compact)
    if not match:
        raise ValueError(f"unsupported contract symbol: {symbol!r}")
    product_id, digits = match.groups()
    if market == "CZCE" and len(digits) == 3:
        year_digit = int(digits[0])
        decade = (trading_day.year // 10) * 10
        year = decade + year_digit
        if year < trading_day.year - 1:
            year += 10
        compact = f"{product_id}{year % 100:02d}{digits[1:]}"
    exchange_short = _EXCHANGE_ID_TO_SHORT.get(market, market)
    return contract_uid_from_exchange_contract(f"{compact}.{exchange_short}")


def parse_akshare_trade_dates(values: pd.Series) -> pd.Series:
    """Parse AKShare dates, including integer YYYYMMDD values from CZCE."""

    text = values.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    fallback_mask = parsed.isna()
    if fallback_mask.any():
        parsed.loc[fallback_mask] = pd.to_datetime(text.loc[fallback_mask], errors="coerce")
    if parsed.isna().any():
        bad = values.loc[parsed.isna()].head(5).to_list()
        raise ValueError(f"unsupported AKShare date values: {bad}")
    return parsed.dt.normalize()


def fetch_akshare_daily(date: str, market: str) -> pd.DataFrame:
    """Fetch one exchange/day from AKShare and normalize it."""

    import akshare as ak  # type: ignore[import-not-found]

    market = market.upper()
    raw: pd.DataFrame
    if market == "DCE":
        try:
            raw = ak.get_dce_daily(date=date)
        except Exception:
            raw = ak.get_futures_daily(start_date=date, end_date=date, market=market)
    else:
        raw = ak.get_futures_daily(start_date=date, end_date=date, market=market)
    return normalize_akshare_daily_frame(raw, market)


def fetch_akshare_daily_with_retries(
    date: str,
    market: str,
    *,
    attempts: int = 3,
    empty_retry_delay: float = 0.5,
) -> pd.DataFrame:
    """Fetch one exchange/day, retrying transient empty AKShare responses.

    Some exchange adapters, notably GFEX through AKShare, may return an empty
    frame for an existing trading day when called in a tight loop. Holidays stay
    empty after retries and are skipped by the caller.
    """

    last = pd.DataFrame(columns=DAYK_COLUMNS)
    for attempt in range(max(attempts, 1)):
        last = fetch_akshare_daily(date, market)
        if not last.empty:
            return last
        if attempt < attempts - 1:
            time.sleep(empty_retry_delay * (attempt + 1))
    return last


def fetch_cffex_monthly_daily(year_month: str) -> pd.DataFrame:
    """Fetch and normalize one CFFEX official monthly daily-data zip."""

    url = f"http://www.cffex.com.cn/sj/historysj/{year_month}/zip/{year_month}.zip"
    response = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            )
        },
        timeout=(5, 10),
        stream=True,
    )
    if response.status_code == 404:
        return pd.DataFrame(columns=DAYK_COLUMNS)
    response.raise_for_status()

    frames: list[pd.DataFrame] = []
    content = b"".join(response.iter_content(chunk_size=64 * 1024))
    with zipfile.ZipFile(BytesIO(content)) as archive:
        for filename in sorted(archive.namelist()):
            if not filename.endswith("_1.csv"):
                continue
            date = filename.split("_", 1)[0]
            with archive.open(filename) as file:
                text = file.read().decode("gb2312")
            raw = _parse_cffex_daily_csv(text, date)
            if not raw.empty:
                frames.append(normalize_akshare_daily_frame(raw, "CFFEX"))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=DAYK_COLUMNS)


def fetch_dce_sina_daily_range(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    minute_data_dir: str | Path = MINUTE_DATA_DIR,
    max_workers: int = 8,
) -> pd.DataFrame:
    """Fetch DCE contract daily bars from Sina as fallback when DCE blocks API access."""

    import akshare as ak  # type: ignore[import-not-found]

    contracts = _dce_contracts_from_local_minutes(start, end, minute_data_dir=minute_data_dir)
    if not contracts:
        contracts = _dce_contracts_from_eastmoney_table()
    if not contracts:
        return pd.DataFrame(columns=DAYK_COLUMNS)

    def fetch_one(symbol: str) -> pd.DataFrame:
        try:
            raw = ak.futures_zh_daily_sina(symbol=symbol)
        except Exception:
            return pd.DataFrame(columns=DAYK_COLUMNS)
        return _normalize_sina_dce_daily(raw, symbol, start, end)

    frames: list[pd.DataFrame] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {executor.submit(fetch_one, symbol): symbol for symbol in sorted(contracts)}
        for future in concurrent.futures.as_completed(future_to_symbol):
            frame = future.result()
            if not frame.empty:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=DAYK_COLUMNS)


def _normalize_sina_dce_daily(raw: pd.DataFrame, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if raw.empty or "date" not in raw.columns:
        return pd.DataFrame(columns=DAYK_COLUMNS)
    symbol = symbol.upper()
    uid = normalize_contract_uid(symbol, "DCE", start)
    _, _, product_id, contract_code = uid.split("|", 3)
    df = raw.copy()
    df["date"] = parse_akshare_trade_dates(df["date"])
    df["settle"] = pd.to_numeric(df["settle"], errors="coerce")
    df["pre_settle"] = df["settle"].shift(1)
    df = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    if df.empty:
        return pd.DataFrame(columns=DAYK_COLUMNS)
    out = pd.DataFrame(index=df.index)
    out["trading_day"] = df["date"]
    out["trade_time"] = df["date"]
    out["trade_timestamp"] = out["trading_day"].astype("int64") // 1_000_000
    out["exchange_id"] = "DCE"
    out["instrument_id"] = symbol
    out["unique_instrument_id"] = uid
    out["open_price"] = _numeric_col(df, "open")
    out["highest_price"] = _numeric_col(df, "high")
    out["lowest_price"] = _numeric_col(df, "low")
    out["close_price"] = _numeric_col(df, "close")
    out["settlement_price"] = _numeric_col(df, "settle")
    out["upper_limit_price"] = np.nan
    out["lower_limit_price"] = np.nan
    out["pre_settlement_price"] = _numeric_col(df, "pre_settle")
    out["volume"] = _numeric_col(df, "volume")
    out["turnover"] = np.nan
    out["open_interest"] = _numeric_col(df, "hold")
    out["insert_time"] = pd.Timestamp.now()
    out["pre_close_price"] = np.nan
    out["day_session_price"] = np.nan
    out["product_id"] = product_id
    out["twap"] = out[["open_price", "highest_price", "lowest_price", "close_price"]].mean(axis=1)
    out["vwap"] = np.nan
    return out.reindex(columns=DAYK_COLUMNS)


def _dce_contracts_from_local_minutes(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    minute_data_dir: str | Path,
) -> set[str]:
    minute_data_dir = Path(minute_data_dir)
    contracts: set[str] = set()
    for month in pd.period_range(start, end, freq="M"):
        path = minute_data_dir / f"data_qc_future_mink_{month.strftime('%Y%m')}.parquet"
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path, columns=["unique_instrument_id"])
        except Exception:
            continue
        values = frame["unique_instrument_id"].dropna().astype(str).unique()
        for uid in values:
            parts = uid.split("|")
            if len(parts) == 4 and parts[0] == "DCE" and parts[1] == "F":
                symbol = f"{parts[2]}{parts[3]}".upper()
                if re.match(r"^[A-Z]+\d{4}F?$", symbol):
                    contracts.add(symbol)
    return contracts


def _dce_contracts_from_eastmoney_table() -> set[str]:
    import akshare as ak  # type: ignore[import-not-found]

    try:
        table = ak.futures_hist_table_em()
    except Exception:
        return set()
    rows = table[table["市场简称"] == "大商所"]
    codes = rows["合约代码"].dropna().astype(str).str.upper()
    return {code for code in codes if _SYMBOL_RE.match(code)}


def _parse_cffex_daily_csv(text: str, date: str) -> pd.DataFrame:
    data_df = pd.read_csv(StringIO(text))
    if data_df.empty or "合约代码" not in data_df.columns:
        return pd.DataFrame()
    data_df = data_df[~data_df["合约代码"].isin(["小计", "合计"])].copy()
    data_df = data_df[~data_df["合约代码"].astype(str).str.contains("IO|MO|HO", regex=True)]
    data_df.reset_index(inplace=True, drop=True)
    if data_df.empty:
        return pd.DataFrame()
    data_df["合约代码"] = data_df["合约代码"].astype(str).str.strip()
    symbols = data_df["合约代码"].to_list()
    varieties = [re.compile(r"[a-zA-Z_]+").findall(symbol)[0] for symbol in symbols]
    if data_df.shape[1] == 15:
        data_df.columns = [
            "symbol", "open", "high", "low", "volume", "turnover", "open_interest",
            "_1", "close", "settle", "pre_settle", "_2", "_3", "_4", "_5",
        ]
    else:
        data_df.columns = [
            "symbol", "open", "high", "low", "volume", "turnover", "open_interest",
            "_1", "close", "settle", "pre_settle", "_2", "_3", "_4",
        ]
    data_df["date"] = date
    data_df["variety"] = varieties
    return data_df[
        [
            "symbol", "date", "open", "high", "low", "close", "volume",
            "open_interest", "turnover", "settle", "pre_settle", "variety",
        ]
    ]


def update_data_dayk_from_akshare(
    *,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    markets: Sequence[str] = DEFAULT_MARKETS,
    path: str | Path = DAYK_PATH,
    minute_data_dir: str | Path = MINUTE_DATA_DIR,
    dry_run: bool = False,
    strict: bool = False,
    strict_validation: bool = False,
    show_progress: bool = False,
) -> DayKUpdateReport:
    """Append AKShare daily futures bars into ``data_dayk.parquet``.

    Existing ``(unique_instrument_id, trading_day)`` rows are replaced by the
    newest fetched row. Holidays naturally fetch zero rows and are skipped.
    """

    path = Path(path)
    markets = tuple(market.upper() for market in markets)
    existing = _read_existing_dayk(path)
    end = pd.Timestamp(end_date).normalize() if end_date is not None else pd.Timestamp.today().normalize()
    market_starts = _resolve_market_start_dates(existing, markets, start_date)
    start = min(market_starts.values()) if market_starts else end
    if not market_starts or all(end < market_start for market_start in market_starts.values()):
        return DayKUpdateReport(path, start, end, tuple(markets), 0, len(existing), (), ())

    frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    if "DCE" in markets:
        try:
            dce_frame = fetch_dce_sina_daily_range(
                market_starts["DCE"],
                end,
                minute_data_dir=minute_data_dir,
            )
        except Exception as exc:
            message = f"DCE Sina fallback {market_starts['DCE'].date()}-{end.date()}: {exc}"
            if strict:
                raise RuntimeError(message) from exc
            warnings.append(message)
        else:
            if not dce_frame.empty:
                frames.append(dce_frame)
    if "CFFEX" in markets:
        cffex_months = list(pd.period_range(market_starts["CFFEX"], end, freq="M"))
        month_iterator: Iterable[pd.Period] = cffex_months
        if show_progress and cffex_months:
            from tqdm import tqdm

            month_iterator = tqdm(cffex_months, desc="Fetching CFFEX monthly zips")
        for month in month_iterator:
            try:
                frame = fetch_cffex_monthly_daily(month.strftime("%Y%m"))
            except Exception as exc:
                message = f"CFFEX {month.strftime('%Y%m')}: {exc}"
                if strict:
                    raise RuntimeError(message) from exc
                warnings.append(message)
                continue
            if not frame.empty:
                frame = frame[(frame["trading_day"] >= market_starts["CFFEX"]) & (frame["trading_day"] <= end)]
                if not frame.empty:
                    frames.append(frame)
    daily_markets = tuple(market for market in markets if market not in {"CFFEX", "DCE"})
    tasks = [
        (day, market)
        for market in daily_markets
        for day in pd.date_range(market_starts[market], end, freq="D")
        if day <= end
    ]
    iterator: Iterable[tuple[pd.Timestamp, str]] = tasks
    if show_progress and tasks:
        from tqdm import tqdm

        iterator = tqdm(tasks, desc="Fetching daily futures bars")
    for day, market in iterator:
        date_str = day.strftime("%Y%m%d")
        try:
            frame = fetch_akshare_daily_with_retries(date_str, market)
        except Exception as exc:
            message = f"{market} {date_str}: {exc}"
            if strict:
                raise RuntimeError(message) from exc
            warnings.append(message)
            continue
        if not frame.empty:
            frames.append(frame)

    fetched = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=DAYK_COLUMNS)
    mismatches = validate_daily_against_minute(fetched, minute_data_dir=minute_data_dir)
    if mismatches and strict_validation:
        raise ValueError(f"daily/minute close mismatch: {mismatches[:5]}")

    combined = _merge_dayk(existing, fetched)
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_parquet_atomic(combined, path)

    return DayKUpdateReport(
        path=path,
        start_date=start,
        end_date=end,
        markets=tuple(m.upper() for m in markets),
        fetched_rows=len(fetched),
        written_rows=len(combined),
        validation_mismatches=tuple(mismatches),
        warnings=tuple(warnings),
    )


def validate_daily_against_minute(
    daily: pd.DataFrame,
    *,
    minute_data_dir: str | Path = MINUTE_DATA_DIR,
    tolerance: float = 1e-8,
    sample_limit: int = 20,
) -> list[dict[str, object]]:
    """Compare fetched daily close with the last local minute close when present."""

    if daily.empty:
        return []
    minute_data_dir = Path(minute_data_dir)
    if not minute_data_dir.exists():
        return []
    daily = daily.copy()
    daily["trading_day"] = pd.to_datetime(daily["trading_day"]).dt.normalize()
    daily["_month"] = daily["trading_day"].dt.strftime("%Y%m")
    mismatches: list[dict[str, object]] = []
    for month, group in daily.groupby("_month"):
        minute_path = minute_data_dir / f"data_qc_future_mink_{month}.parquet"
        if not minute_path.exists():
            continue
        minute = pd.read_parquet(minute_path)
        if minute.empty or not {"unique_instrument_id", "trading_day", "trade_time", "close_price"} <= set(minute.columns):
            continue
        minute = minute[minute["unique_instrument_id"].isin(group["unique_instrument_id"].unique())].copy()
        if minute.empty:
            continue
        minute["trading_day"] = pd.to_datetime(minute["trading_day"]).dt.normalize()
        last_minute = (
            minute.sort_values("trade_time")
            .groupby(["unique_instrument_id", "trading_day"], as_index=False)
            .tail(1)[["unique_instrument_id", "trading_day", "close_price"]]
            .rename(columns={"close_price": "minute_close"})
        )
        check = group.merge(last_minute, on=["unique_instrument_id", "trading_day"], how="inner")
        if check.empty:
            continue
        bad = check[(check["close_price"] - check["minute_close"]).abs() > tolerance]
        for row in bad.head(sample_limit - len(mismatches)).itertuples(index=False):
            mismatches.append({
                "unique_instrument_id": row.unique_instrument_id,
                "trading_day": str(pd.Timestamp(row.trading_day).date()),
                "daily_close": float(row.close_price),
                "minute_close": float(row.minute_close),
            })
        if len(mismatches) >= sample_limit:
            break
    return mismatches


def _numeric_col(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[name], errors="coerce").astype("float64")


def _read_existing_dayk(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=DAYK_COLUMNS)
    existing = pd.read_parquet(path)
    if "trading_day" in existing.columns:
        existing["trading_day"] = pd.to_datetime(existing["trading_day"]).dt.normalize()
    return existing.reindex(columns=DAYK_COLUMNS)


def _resolve_start_date(existing: pd.DataFrame, start_date: str | pd.Timestamp | None) -> pd.Timestamp:
    if start_date is not None:
        return pd.Timestamp(start_date).normalize()
    if existing.empty or "trading_day" not in existing.columns or existing["trading_day"].dropna().empty:
        return pd.Timestamp.today().normalize()
    return (pd.to_datetime(existing["trading_day"]).max() + pd.Timedelta(days=1)).normalize()


def _resolve_market_start_dates(
    existing: pd.DataFrame,
    markets: Sequence[str],
    start_date: str | pd.Timestamp | None,
) -> dict[str, pd.Timestamp]:
    if start_date is not None:
        start = pd.Timestamp(start_date).normalize()
        return {market.upper(): start for market in markets}
    starts: dict[str, pd.Timestamp] = {}
    if existing.empty or not {"exchange_id", "trading_day"} <= set(existing.columns):
        today = pd.Timestamp.today().normalize()
        return {market.upper(): today for market in markets}
    frame = existing[["exchange_id", "trading_day"]].dropna().copy()
    frame["exchange_id"] = frame["exchange_id"].astype(str).str.upper()
    frame["trading_day"] = pd.to_datetime(frame["trading_day"]).dt.normalize()
    max_by_market = frame.groupby("exchange_id")["trading_day"].max().to_dict()
    fallback = _resolve_start_date(existing, None)
    for market in markets:
        key = market.upper()
        starts[key] = (max_by_market.get(key, fallback) + pd.Timedelta(days=1)).normalize()
    return starts


def _merge_dayk(existing: pd.DataFrame, fetched: pd.DataFrame) -> pd.DataFrame:
    if fetched.empty:
        return existing.reindex(columns=DAYK_COLUMNS)
    combined = pd.concat([existing, fetched], ignore_index=True).reindex(columns=DAYK_COLUMNS)
    combined["trading_day"] = pd.to_datetime(combined["trading_day"]).dt.normalize()
    combined = (
        combined.drop_duplicates(["unique_instrument_id", "trading_day"], keep="last")
        .sort_values(["unique_instrument_id", "trading_day"])
        .reset_index(drop=True)
    )
    return combined


def _write_parquet_atomic(df: pd.DataFrame, path: Path) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    df.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, path)
