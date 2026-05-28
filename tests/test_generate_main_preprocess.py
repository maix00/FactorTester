import pandas as pd
import pytest

from sources.LocalCNFutures.GenerateMain import preprocess_minute_data


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

    out_path = product_dir / f"{uid}.parquet"
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
