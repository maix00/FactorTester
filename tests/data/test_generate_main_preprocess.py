import pandas as pd
import pytest

from sources.LocalCNFutures.scripts.generate_main import (
    BACKWARD_BASE_DATE_COL,
    fill_minute_settlement_from_dayk,
    generate_main_contract_series,
    preprocess_minute_data,
)
from sources.LocalCNFutures.contract_files import resolve_contract_parquet_path


def test_generate_main_resolves_canonical_contract_file(tmp_path):
    alias = "DCE|F|BZ|2603"
    canonical_path = tmp_path / "DCE_F_BZ_2603.parquet"
    canonical_path.touch()

    assert resolve_contract_parquet_path(tmp_path, alias) == canonical_path


def _minute_frame(uid: str, start: str) -> pd.DataFrame:
    times = pd.date_range(start, periods=2, freq="min")
    return pd.DataFrame({
        "unique_instrument_id": [uid, uid],
        "trade_timestamp": [int(ts.timestamp() * 1000) for ts in times],
        "trade_time": times,
        "trading_day": [times[0].normalize(), times[0].normalize()],
        "close_price": [1.0, 2.0],
    })


def test_preprocess_minute_data_empty_dir_raises(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    product_dir = tmp_path / "product"
    with pytest.raises(ValueError, match="没有 parquet 文件"):
        preprocess_minute_data(str(raw_dir), str(product_dir), force_rebuild=True)


def test_preprocess_minute_data_appends_changed_raw_files(tmp_path):
    raw_dir = tmp_path / "raw"
    product_dir = tmp_path / "product"
    raw_dir.mkdir()

    uid = "DCE|F|A|2601"
    _minute_frame(uid, "2026-01-05 09:01").to_parquet(raw_dir / "m202601.parquet", index=False)
    preprocess_minute_data(str(raw_dir), str(product_dir), force_rebuild=False)

    out_path = resolve_contract_parquet_path(product_dir, uid)
    first = pd.read_parquet(out_path)
    assert len(first) == 2

    pd.concat([
        _minute_frame(uid, "2026-01-05 09:01"),
        _minute_frame(uid, "2026-01-06 09:01"),
    ], ignore_index=True).to_parquet(raw_dir / "m202601.parquet", index=False)
    preprocess_minute_data(str(raw_dir), str(product_dir), force_rebuild=False)

    updated = pd.read_parquet(out_path)
    assert len(updated) == 4
    assert pd.to_datetime(updated["trade_time"]).max() == pd.Timestamp("2026-01-06 09:02")


def test_fill_minute_settlement_from_dayk_fills_zero_placeholders():
    minute = pd.DataFrame({
        "contract_uid": ["GFEX|F|LC|2605", "GFEX|F|LC|2605"],
        "trading_day": [pd.Timestamp("2026-01-09"), pd.Timestamp("2026-01-09")],
        "trade_time": [pd.Timestamp("2026-01-09 14:59"), pd.Timestamp("2026-01-09 15:00")],
        "settlement_price": [0.0, 143000.0],
        "pre_settlement_price": [0.0, 142000.0],
    })
    dayk = pd.DataFrame({
        "contract_uid": ["GFEX|F|LC|2605"],
        "trading_day": [pd.Timestamp("2026-01-09")],
        "settlement_price": [143180.0],
        "pre_settlement_price": [143400.0],
    })

    filled = fill_minute_settlement_from_dayk(minute, dayk)

    assert filled["settlement_price"].to_list() == [143180.0, 143000.0]
    assert filled["pre_settlement_price"].to_list() == [143400.0, 142000.0]


def test_generate_main_fills_main_mink_settlement_from_dayk(tmp_path):
    raw_dir = tmp_path / "raw_minute"
    product_dir = tmp_path / "product_minute"
    main_mink_dir = tmp_path / "main_mink"
    main_dayk_dir = tmp_path / "main_dayk"
    raw_dir.mkdir()

    uid = _uid("A2401.DCE")
    mapping_path = tmp_path / "wind_mapping.parquet"
    dayk_path = tmp_path / "dayk.parquet"
    roller_path = tmp_path / "roller_info.parquet"
    _mapping([
        ("A.DCE", "A2401.DCE", "2024-01-01", "2024-01-02"),
    ]).to_parquet(mapping_path, index=False)

    minute = pd.DataFrame([
        {**_one_bar(uid, "2024-01-01", 95.0), "settlement_price": 0.0, "pre_settlement_price": 0.0},
        {**_one_bar(uid, "2024-01-02", 100.0), "settlement_price": 0.0, "pre_settlement_price": 0.0},
    ])
    dayk = minute.copy()
    dayk["settlement_price"] = [96.0, 101.0]
    dayk["pre_settlement_price"] = [94.0, 96.0]
    minute.drop(columns=["contract_uid"]).to_parquet(raw_dir / "minute.parquet", index=False)
    dayk.drop(columns=["contract_uid"]).to_parquet(dayk_path, index=False)

    generate_main_contract_series(
        contract_start_end_path=str(mapping_path),
        dayk_path=str(dayk_path),
        minute_data_dir=str(raw_dir),
        minute_data_preprocessed_dir=str(product_dir),
        main_mink_folder_path=str(main_mink_dir) + "/",
        main_dayk_folder_path=str(main_dayk_dir) + "/",
        roller_info_path=str(roller_path),
        rebuild_minute_product=True,
        rebuild_roller_info=True,
    )

    main_mink = pd.read_parquet(main_mink_dir / "A.DCE.parquet")
    assert main_mink["settlement_price"].to_list() == [96.0, 101.0]
    assert main_mink["pre_settlement_price"].to_list() == [94.0, 96.0]


def _mapping(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["S_INFO_WINDCODE", "FS_MAPPING_WINDCODE", "STARTDATE", "ENDDATE"],
    )


def _uid(contract: str) -> str:
    month = contract.removeprefix("A").removesuffix(".DCE")
    return f"DCE|F|A|{month}"


def _one_bar(uid: str, trading_day: str, close: float) -> dict:
    ts = pd.Timestamp(f"{trading_day} 15:00:00")
    return {
        "unique_instrument_id": uid,
        "contract_uid": uid,
        "trade_timestamp": int(ts.timestamp() * 1000),
        "trade_time": ts,
        "trading_day": ts.normalize(),
        "close_price": close,
    }


def test_generate_main_incremental_applies_last_forward_adjustment(tmp_path):
    raw_dir = tmp_path / "raw_minute"
    product_dir = tmp_path / "product_minute"
    main_mink_dir = tmp_path / "main_mink"
    main_dayk_dir = tmp_path / "main_dayk"
    raw_dir.mkdir()

    mapping_initial_path = tmp_path / "wind_mapping_initial.parquet"
    mapping_incremental_path = tmp_path / "wind_mapping_incremental.parquet"
    dayk_path = tmp_path / "dayk.parquet"
    roller_path = tmp_path / "roller_info.parquet"

    _mapping([
        ("A.DCE", "A2401.DCE", "2024-01-01", "2024-01-02"),
        ("A.DCE", "A2405.DCE", "2024-01-03", "2024-01-04"),
    ]).to_parquet(mapping_initial_path, index=False)
    _mapping([
        ("A.DCE", "A2401.DCE", "2024-01-01", "2024-01-02"),
        ("A.DCE", "A2405.DCE", "2024-01-03", "2024-01-04"),
        ("A.DCE", "A2409.DCE", "2024-01-05", "2024-01-06"),
    ]).to_parquet(mapping_incremental_path, index=False)

    rows = [
        _one_bar(_uid("A2401.DCE"), "2024-01-01", 95.0),
        _one_bar(_uid("A2401.DCE"), "2024-01-02", 100.0),
        _one_bar(_uid("A2405.DCE"), "2024-01-02", 110.0),
        _one_bar(_uid("A2405.DCE"), "2024-01-03", 115.0),
        _one_bar(_uid("A2405.DCE"), "2024-01-04", 120.0),
        _one_bar(_uid("A2409.DCE"), "2024-01-04", 90.0),
        _one_bar(_uid("A2409.DCE"), "2024-01-05", 91.0),
        _one_bar(_uid("A2409.DCE"), "2024-01-06", 92.0),
    ]
    raw_df = pd.DataFrame(rows)
    raw_df.drop(columns=["contract_uid"]).to_parquet(raw_dir / "minute.parquet", index=False)
    raw_df.drop(columns=["contract_uid"]).to_parquet(dayk_path, index=False)

    common_kwargs = dict(
        dayk_path=str(dayk_path),
        minute_data_dir=str(raw_dir),
        minute_data_preprocessed_dir=str(product_dir),
        main_mink_folder_path=str(main_mink_dir) + "/",
        main_dayk_folder_path=str(main_dayk_dir) + "/",
        roller_info_path=str(roller_path),
    )

    generate_main_contract_series(
        contract_start_end_path=str(mapping_initial_path),
        rebuild_minute_product=True,
        rebuild_roller_info=True,
        **common_kwargs,
    )
    first_mink = pd.read_parquet(main_mink_dir / "A.DCE.parquet")
    assert first_mink.groupby("contract_uid")["adjustment_mul"].first().to_dict() == {
        _uid("A2401.DCE"): pytest.approx(100.0 / 110.0),
        _uid("A2405.DCE"): pytest.approx(1.0),
    }

    info = generate_main_contract_series(
        contract_start_end_path=str(mapping_incremental_path),
        rebuild_minute_product=False,
        rebuild_roller_info=False,
        **common_kwargs,
    )

    assert BACKWARD_BASE_DATE_COL in info.columns
    assert "FORWARD_BASE_DATE" not in info.columns

    factors = info.groupby("CONTRACT")["FORWARD_FACTOR"].first().to_dict()
    assert factors["A2401.DCE"] == pytest.approx((100.0 / 110.0) * (120.0 / 90.0))
    assert factors["A2405.DCE"] == pytest.approx(120.0 / 90.0)
    assert factors["A2409.DCE"] == pytest.approx(1.0)

    updated_mink = pd.read_parquet(main_mink_dir / "A.DCE.parquet")
    assert updated_mink.groupby("contract_uid")["adjustment_mul"].first().to_dict() == {
        _uid("A2401.DCE"): pytest.approx((100.0 / 110.0) * (120.0 / 90.0)),
        _uid("A2405.DCE"): pytest.approx(120.0 / 90.0),
        _uid("A2409.DCE"): pytest.approx(1.0),
    }
