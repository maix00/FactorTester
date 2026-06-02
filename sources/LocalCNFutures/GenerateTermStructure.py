"""Generate CN futures term-structure snapshots.

The output is consumed by tools.products.AdjustableTermStructure.  It stores one
row per (product, trading_day, contract), ordered by maturity inside each day.
"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from Settings import DATA_DIR
from sources.LocalCNFutures import TERM_STRUCTURE_PATH
from sources.LocalCNFutures.CNFutures import exchange_map
from tools.products.AdjustableTermStructure import (
    TERM_CONTRACT_COL,
    TERM_CONTRACT_UID_COL,
    TERM_DAYS_TO_MATURITY_COL,
    TERM_IS_MAIN_COL,
    TERM_MATURITY_COL,
    TERM_PRODUCT_COL,
    TERM_RANK_COL,
    TERM_TRADING_DAY_COL,
)


contract_mapping_path = os.path.join(DATA_DIR, 'wind_mapping.parquet')
dayk_path = os.path.join(DATA_DIR, 'data_dayk.parquet')
roller_info_path = os.path.join(DATA_DIR, 'roller_info.parquet')


def _patch_czc_contract_decade(row: pd.Series) -> Optional[str]:
    contract = row.get('CONTRACT')
    if not isinstance(contract, str):
        return None
    if not contract.endswith('CZC'):
        return contract
    enddate = row.get('ENDDATE')
    if pd.isna(enddate):
        return None
    digits = ''.join(filter(str.isdigit, contract))
    if len(digits) == 4:
        return contract
    if len(digits) != 3:
        return None

    end_str = pd.Timestamp(enddate).strftime('%Y%m%d')
    next_two = str(int(end_str[2:4]) + 1).zfill(2)
    decade = end_str[2] if digits[0] == end_str[3] else (next_two[0] if digits[0] == next_two[-1] else None)
    return contract.replace(digits, decade + digits) if decade else None


def _contract_to_uid(contract: Optional[str]) -> Optional[str]:
    if not contract or '.' not in contract:
        return None
    product_month, exchange = contract.split('.')
    first_digit = next((i for i, c in enumerate(product_month) if c.isdigit()), len(product_month))
    reverse_exchange = {v: k for k, v in exchange_map.items()}
    return f"{reverse_exchange.get(exchange, exchange)}|F|{product_month[:first_digit]}|{product_month[first_digit:]}"


def _load_mapping(path: str) -> pd.DataFrame:
    mapping = (
        pd.read_parquet(path)
        .rename(columns={'S_INFO_WINDCODE': 'PRODUCT', 'FS_MAPPING_WINDCODE': 'CONTRACT'})
    )
    mapping['STARTDATE'] = pd.to_datetime(mapping['STARTDATE'])
    mapping['ENDDATE'] = pd.to_datetime(mapping['ENDDATE'])
    mapping = mapping.dropna(subset=['PRODUCT', 'CONTRACT', 'STARTDATE', 'ENDDATE'])
    mapping['CONTRACT_PATCHED'] = mapping.apply(_patch_czc_contract_decade, axis=1)
    mapping[TERM_CONTRACT_UID_COL] = mapping['CONTRACT_PATCHED'].apply(_contract_to_uid)
    return mapping.dropna(subset=[TERM_CONTRACT_UID_COL])


def generate_cn_futures_term_structure(
    contract_start_end_path: str = contract_mapping_path,
    contract_dayk_path: str = dayk_path,
    main_roller_info_path: str = roller_info_path,
    output_path: str = TERM_STRUCTURE_PATH,
    products: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Build and save CN futures term-structure snapshots.

    The contract pool is inferred from mapping STARTDATE/ENDDATE windows.  The
    daily values come from contract-level day-k data.  A contract only appears
    on days where both mapping coverage and market data exist.
    """
    mapping = _load_mapping(contract_start_end_path)
    if products:
        mapping = mapping[mapping['PRODUCT'].isin(products)]

    dayk = pd.read_parquet(contract_dayk_path).rename(columns={'unique_instrument_id': TERM_CONTRACT_UID_COL})
    dayk['trading_day'] = pd.to_datetime(dayk['trading_day'])

    merged = dayk.merge(
        mapping[['PRODUCT', 'CONTRACT', TERM_CONTRACT_UID_COL, 'ENDDATE']],
        on=TERM_CONTRACT_UID_COL,
        how='inner',
    )
    merged = merged[merged['trading_day'] <= merged['ENDDATE']]

    out = pd.DataFrame({
        TERM_PRODUCT_COL: merged['PRODUCT'],
        TERM_TRADING_DAY_COL: merged['trading_day'].dt.normalize(),
        TERM_CONTRACT_UID_COL: merged[TERM_CONTRACT_UID_COL],
        TERM_CONTRACT_COL: merged['CONTRACT'],
        TERM_MATURITY_COL: merged['ENDDATE'].dt.normalize(),
        TERM_DAYS_TO_MATURITY_COL: (merged['ENDDATE'].dt.normalize() - merged['trading_day'].dt.normalize()).dt.days,
        'OPEN': merged.get('open_price'),
        'HIGH': merged.get('highest_price'),
        'LOW': merged.get('lowest_price'),
        'CLOSE': merged.get('close_price'),
        'VOLUME': merged.get('volume'),
        'OPEN_INTEREST': merged.get('open_interest'),
    })
    out = out.dropna(subset=[TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_CONTRACT_UID_COL, TERM_MATURITY_COL])
    out = out.sort_values([TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_MATURITY_COL, TERM_CONTRACT_UID_COL])
    out[TERM_RANK_COL] = out.groupby([TERM_PRODUCT_COL, TERM_TRADING_DAY_COL]).cumcount()

    if os.path.exists(main_roller_info_path):
        roller = pd.read_parquet(main_roller_info_path)
        roller['STARTDATE'] = pd.to_datetime(roller['STARTDATE']).dt.normalize()
        roller['ENDDATE'] = pd.to_datetime(roller['ENDDATE']).dt.normalize()
        main_pairs = []
        for _, row in roller.iterrows():
            days = pd.date_range(row['STARTDATE'], row['ENDDATE'], freq='D')
            main_pairs.append(pd.DataFrame({
                TERM_PRODUCT_COL: row['PRODUCT'],
                TERM_TRADING_DAY_COL: days,
                TERM_CONTRACT_UID_COL: row.get('CONTRACT_UID'),
            }))
        if main_pairs:
            main_df = pd.concat(main_pairs, ignore_index=True)
            main_df[TERM_IS_MAIN_COL] = True
            out = out.merge(main_df, on=[TERM_PRODUCT_COL, TERM_TRADING_DAY_COL, TERM_CONTRACT_UID_COL], how='left')
            out[TERM_IS_MAIN_COL] = out[TERM_IS_MAIN_COL].fillna(False)
        else:
            out[TERM_IS_MAIN_COL] = False
    else:
        out[TERM_IS_MAIN_COL] = False

    out.to_parquet(output_path, index=False)
    return out


if __name__ == '__main__':
    df = generate_cn_futures_term_structure()
    print(df)
