from pathlib import Path

import pandas as pd

from sources.LocalCNFutures.scripts.generate_term_structure import (
    generate_cn_futures_term_structure,
)
from tools.products.AdjustableTermStructure import (
    TERM_CONTRACT_UID_COL,
    TERM_IS_MAIN_COL,
    TERM_IS_SECONDARY_COL,
    TERM_PRODUCT_COL,
    TERM_RANK_COL,
)


def test_curve_uses_all_observed_contracts_and_continuous_series_only_as_labels(tmp_path: Path):
    day = pd.Timestamp("2025-06-24")
    dayk = pd.DataFrame([
        {"trading_day": day, "unique_instrument_id": "DCE|F|A|2509", "close_price": 4000},
        {"trading_day": day, "unique_instrument_id": "DCE|F|A|2511", "close_price": 4010},
        {"trading_day": day, "unique_instrument_id": "DCE|F|A|2601", "close_price": 4020},
    ])
    roller = pd.DataFrame([
        {"PRODUCT": "A.DCE", "CONTRACT_UID": "DCE|F|A|2509", "STARTDATE": day, "ENDDATE": day},
        {"PRODUCT": "A_S.DCE", "CONTRACT_UID": "DCE|F|A|2511", "STARTDATE": day, "ENDDATE": day},
    ])
    dayk_path = tmp_path / "dayk.parquet"
    roller_path = tmp_path / "roller.parquet"
    output_path = tmp_path / "curve.parquet"
    dayk.to_parquet(dayk_path)
    roller.to_parquet(roller_path)

    result = generate_cn_futures_term_structure(
        contract_dayk_path=str(dayk_path),
        main_roller_info_path=str(roller_path),
        output_path=str(output_path),
    )

    assert set(result[TERM_PRODUCT_COL]) == {"A.DCE"}
    assert result[TERM_CONTRACT_UID_COL].is_unique
    assert result[TERM_RANK_COL].tolist() == [0, 1, 2]
    assert result.loc[result[TERM_IS_MAIN_COL], TERM_CONTRACT_UID_COL].tolist() == ["DCE|F|A|2509"]
    assert result.loc[result[TERM_IS_SECONDARY_COL], TERM_CONTRACT_UID_COL].tolist() == ["DCE|F|A|2511"]


def test_curve_does_not_duplicate_overlapping_continuous_mapping_intervals(tmp_path: Path):
    day = pd.Timestamp("2025-06-24")
    pd.DataFrame([
        {"trading_day": day, "unique_instrument_id": "SHFE|F|RB|2510", "close_price": 3000},
    ]).to_parquet(tmp_path / "dayk.parquet")
    pd.DataFrame([
        {"PRODUCT": "RB.SHF", "CONTRACT_UID": "SHFE|F|RB|2510", "STARTDATE": day, "ENDDATE": day},
        {"PRODUCT": "RB.SHF", "CONTRACT_UID": "SHFE|F|RB|2510", "STARTDATE": day, "ENDDATE": day},
    ]).to_parquet(tmp_path / "roller.parquet")

    result = generate_cn_futures_term_structure(
        contract_dayk_path=str(tmp_path / "dayk.parquet"),
        main_roller_info_path=str(tmp_path / "roller.parquet"),
        output_path=str(tmp_path / "curve.parquet"),
    )

    assert len(result) == 1
    assert bool(result.iloc[0][TERM_IS_MAIN_COL]) is True
