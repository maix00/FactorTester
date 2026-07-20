"""Build the observed listed-contract curve for Chinese futures."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd

from sources.LocalCNFutures import ROLLER_INFO_PATH, SOURCE_DATA_DIR, TERM_STRUCTURE_PATH
from tools.products.AdjustableTermStructure import (
    TERM_CONTRACT_COL,
    TERM_CONTRACT_UID_COL,
    TERM_DAYS_TO_MATURITY_COL,
    TERM_IS_MAIN_COL,
    TERM_IS_SECONDARY_COL,
    TERM_MATURITY_COL,
    TERM_PRODUCT_COL,
    TERM_RANK_COL,
    TERM_TRADING_DAY_COL,
)
from tools.data.types import DataColumn


dayk_path = os.path.join(SOURCE_DATA_DIR, "data_dayk.parquet")
roller_info_path = ROLLER_INFO_PATH

_EXCHANGE_SHORT = {
    "DCE": "DCE",
    "CZCE": "CZC",
    "SHFE": "SHF",
    "CFFEX": "CFE",
    "GFEX": "GFE",
    "INE": "INE",
}


def _contract_identity(uid: str, trading_day: pd.Timestamp) -> tuple[str, str, pd.Timestamp] | None:
    parts = str(uid).split("|")
    if len(parts) < 4 or parts[1] != "F":
        return None
    exchange, _, product_code, delivery_code = parts[:4]
    digits = "".join(char for char in delivery_code if char.isdigit())
    if len(digits) not in {3, 4}:
        return None
    if len(digits) == 3:
        year_digit, month_text = int(digits[0]), digits[1:]
        decade = (trading_day.year // 10) * 10
        year = decade + year_digit
        if year < trading_day.year - 2:
            year += 10
    else:
        year_two, month_text = int(digits[:2]), digits[2:]
        century = (trading_day.year // 100) * 100
        year = century + year_two
        if year < trading_day.year - 20:
            year += 100
        elif year > trading_day.year + 20:
            year -= 100
    month = int(month_text)
    if not 1 <= month <= 12:
        return None
    short_exchange = _EXCHANGE_SHORT.get(exchange, exchange)
    product_name = f"{product_code.upper()}.{short_exchange}"
    contract_name = f"{product_code.upper()}{year % 100:02d}{month:02d}.{short_exchange}"
    maturity = pd.Period(f"{year:04d}-{month:02d}", freq="M").end_time.normalize()
    return product_name, contract_name, maturity


def _continuous_contract_days(path: str, *, secondary: bool) -> pd.DataFrame:
    if not os.path.isfile(path):
        return pd.DataFrame(columns=[TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_CONTRACT_UID_COL])
    roller = pd.read_parquet(path, columns=["PRODUCT", "CONTRACT_UID", "STARTDATE", "ENDDATE"])
    suffix_mask = roller["PRODUCT"].astype(str).str.contains(r"(?:_S|-S)\.", regex=True)
    roller = roller[suffix_mask if secondary else ~suffix_mask].copy()
    if roller.empty:
        return pd.DataFrame(columns=[TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_CONTRACT_UID_COL])
    roller[TERM_PRODUCT_COL] = roller["PRODUCT"].astype(str).str.replace(r"(?:_S|-S)(?=\.)", "", regex=True)
    frames = []
    for row in roller.dropna(subset=["STARTDATE", "ENDDATE", "CONTRACT_UID"]).itertuples(index=False):
        frames.append(pd.DataFrame({
            TERM_PRODUCT_COL: getattr(row, TERM_PRODUCT_COL),
            TERM_TRADING_DAY_COL: pd.date_range(row.STARTDATE, row.ENDDATE, freq="D"),
            TERM_CONTRACT_UID_COL: str(row.CONTRACT_UID),
        }))
    if not frames:
        return pd.DataFrame(columns=[TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_CONTRACT_UID_COL])
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        [TERM_PRODUCT_COL, TERM_TRADING_DAY_COL], keep="last"
    )


def generate_cn_futures_term_structure(
    contract_dayk_path: str = dayk_path,
    main_roller_info_path: str = roller_info_path,
    output_path: str = TERM_STRUCTURE_PATH,
    products: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Build one observed listed-contract curve per underlying and trading day.

    Continuous main/secondary mappings only annotate the curve. They never
    decide curve membership or maturity ordering.
    """
    dayk = pd.read_parquet(contract_dayk_path).rename(
        columns={"unique_instrument_id": TERM_CONTRACT_UID_COL}
    )
    dayk[TERM_TRADING_DAY_COL] = pd.to_datetime(dayk["trading_day"]).dt.normalize()
    contract_meta = (
        dayk.groupby(TERM_CONTRACT_UID_COL, as_index=False)[TERM_TRADING_DAY_COL]
        .min()
    )
    contract_meta["_identity"] = [
        _contract_identity(uid, day)
        for uid, day in zip(contract_meta[TERM_CONTRACT_UID_COL], contract_meta[TERM_TRADING_DAY_COL])
    ]
    contract_meta = contract_meta[contract_meta["_identity"].notna()].copy()
    contract_meta[TERM_PRODUCT_COL] = contract_meta["_identity"].map(lambda value: value[0])
    contract_meta[TERM_CONTRACT_COL] = contract_meta["_identity"].map(lambda value: value[1])
    contract_meta[TERM_MATURITY_COL] = contract_meta["_identity"].map(lambda value: value[2])
    dayk = dayk.merge(
        contract_meta[[TERM_CONTRACT_UID_COL, TERM_PRODUCT_COL, TERM_CONTRACT_COL, TERM_MATURITY_COL]],
        on=TERM_CONTRACT_UID_COL,
        how="inner",
    )
    if products:
        dayk = dayk[dayk[TERM_PRODUCT_COL].isin(products)]

    out = pd.DataFrame({
        TERM_PRODUCT_COL: dayk[TERM_PRODUCT_COL],
        TERM_TRADING_DAY_COL: dayk[TERM_TRADING_DAY_COL],
        TERM_CONTRACT_UID_COL: dayk[TERM_CONTRACT_UID_COL],
        TERM_CONTRACT_COL: dayk[TERM_CONTRACT_COL],
        TERM_MATURITY_COL: dayk[TERM_MATURITY_COL],
        TERM_DAYS_TO_MATURITY_COL: (
            dayk[TERM_MATURITY_COL] - dayk[TERM_TRADING_DAY_COL]
        ).dt.days,
        "OPEN": dayk.get("open_price"),
        "HIGH": dayk.get("highest_price"),
        "LOW": dayk.get("lowest_price"),
        "CLOSE": dayk.get("close_price"),
        "VWAP": dayk.get("vwap"),
        DataColumn.SETTLEMENT_PRICE.name: dayk.get("settlement_price"),
        DataColumn.PRE_SETTLEMENT_PRICE.name: dayk.get("pre_settlement_price"),
        "VOLUME": dayk.get("volume"),
        "OPEN_INTEREST": dayk.get("open_interest"),
    }).drop_duplicates(
        [TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_CONTRACT_UID_COL], keep="last"
    )
    out = out.sort_values(
        [TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_MATURITY_COL, TERM_CONTRACT_UID_COL]
    )
    out[TERM_RANK_COL] = out.groupby([TERM_PRODUCT_COL, TERM_TRADING_DAY_COL]).cumcount()

    for column, secondary in ((TERM_IS_MAIN_COL, False), (TERM_IS_SECONDARY_COL, True)):
        selected = _continuous_contract_days(main_roller_info_path, secondary=secondary)
        if selected.empty:
            out[column] = False
            continue
        selected[column] = True
        out = out.merge(
            selected,
            on=[TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_CONTRACT_UID_COL],
            how="left",
        )
        out[column] = out[column].fillna(False).astype(bool)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(output_path, index=False)
    return out


if __name__ == "__main__":
    print(generate_cn_futures_term_structure())
