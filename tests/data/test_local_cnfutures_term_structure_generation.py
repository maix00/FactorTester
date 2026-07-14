from pathlib import Path

import pandas as pd

from sources.LocalCNFutures.scripts.generate_term_structure import (
    generate_cn_futures_term_structure,
)
from tools.data.types import DataColumn
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


def test_curve_preserves_contract_settlement_prices_for_strict_dmtm(tmp_path: Path):
    day = pd.Timestamp("2024-01-04")
    pd.DataFrame([
        {
            "trading_day": day,
            "unique_instrument_id": "DCE|F|FB|2402",
            "close_price": 1229.0,
            "vwap": 1228.5,
            "settlement_price": 1230.0,
            "pre_settlement_price": 1235.0,
        },
    ]).to_parquet(tmp_path / "dayk.parquet")
    pd.DataFrame([
        {"PRODUCT": "FB.DCE", "CONTRACT_UID": "DCE|F|FB|2402", "STARTDATE": day, "ENDDATE": day},
    ]).to_parquet(tmp_path / "roller.parquet")

    result = generate_cn_futures_term_structure(
        contract_dayk_path=str(tmp_path / "dayk.parquet"),
        main_roller_info_path=str(tmp_path / "roller.parquet"),
        output_path=str(tmp_path / "curve.parquet"),
    )

    row = result.iloc[0]
    assert row[TERM_CONTRACT_UID_COL] == "DCE|F|FB|2402"
    assert row["VWAP"] == 1228.5
    assert row[DataColumn.SETTLEMENT_PRICE.name] == 1230.0
    assert row[DataColumn.SETTLEMENT_PRICE.name] != row["CLOSE"]
    assert row[DataColumn.PRE_SETTLEMENT_PRICE.name] == 1235.0


def test_cnfutures_contract_day1_view_reads_term_structure_settlement(monkeypatch, tmp_path: Path):
    from sources.LocalCNFutures.CNFutures import CNFuturesContract
    from tools.data.types import DataFreq
    from tools.products.AdjustableTermStructure import (
        TERM_CONTRACT_COL,
        TERM_DAYS_TO_MATURITY_COL,
        TERM_MATURITY_COL,
        TERM_TRADING_DAY_COL,
    )

    day = pd.Timestamp("2024-01-04")
    curve = pd.DataFrame([
        {
            TERM_PRODUCT_COL: "FB.DCE",
            TERM_TRADING_DAY_COL: day,
            TERM_CONTRACT_UID_COL: "DCE|F|FB|2402",
            TERM_CONTRACT_COL: "FB2402.DCE",
            TERM_MATURITY_COL: pd.Timestamp("2024-02-29"),
            TERM_DAYS_TO_MATURITY_COL: 56,
            "CLOSE": 1229.0,
            DataColumn.SETTLEMENT_PRICE.name: 1230.0,
            DataColumn.PRE_SETTLEMENT_PRICE.name: 1235.0,
            TERM_RANK_COL: 0,
            TERM_IS_MAIN_COL: False,
            TERM_IS_SECONDARY_COL: False,
        },
    ])
    curve_path = tmp_path / "curve.parquet"
    curve.to_parquet(curve_path)

    class _Parent:
        def get_term_structure_path(self):
            return str(curve_path)

    contract = CNFuturesContract("DCE|F|FB|2402")
    monkeypatch.setattr(contract, "get_parent_product", lambda: _Parent())

    assert DataFreq.DAY1 in contract.list_available_freqs()
    frame = contract.DAY1.get_and_adjust_cols(
        [DataColumn.CLOSE.name, DataColumn.SETTLEMENT_PRICE.name],
        start_dt="2024-01-01",
        end_dt="2024-01-31",
    )

    assert frame.index.name == DataFreq.DAY1.name
    assert frame.iloc[0][DataColumn.CLOSE.name] == 1229.0
    assert frame.iloc[0][DataColumn.SETTLEMENT_PRICE.name] == 1230.0
    assert frame.iloc[0][DataColumn.SETTLEMENT_PRICE.name] != frame.iloc[0][DataColumn.CLOSE.name]
