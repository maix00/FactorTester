import pandas as pd
import pytest

from sources.LocalCNFutures.daily_update import (
    DAYK_COLUMNS,
    fetch_cffex_monthly_daily,
    fetch_akshare_daily_with_retries,
    normalize_akshare_daily_frame,
    normalize_contract_symbol,
    parse_akshare_trade_dates,
    update_data_dayk_from_akshare,
)


def test_normalize_contract_symbol_expands_czce_three_digit_contract():
    assert normalize_contract_symbol("AP605", "CZCE", pd.Timestamp("2026-01-09")) == ("AP", "2605")


def test_normalize_contract_symbol_keeps_dce_month_average_futures_suffix():
    assert normalize_contract_symbol("L2602F", "DCE", pd.Timestamp("2026-01-09")) == ("L", "2602F")


def test_parse_akshare_trade_dates_handles_integer_yyyymmdd():
    parsed = parse_akshare_trade_dates(pd.Series([20260109, "20260703"]))

    assert parsed.to_list() == [pd.Timestamp("2026-01-09"), pd.Timestamp("2026-07-03")]


def test_normalize_akshare_daily_frame_maps_settlement_columns():
    raw = pd.DataFrame({
        "symbol": ["LC2605"],
        "date": ["2026-01-09"],
        "open": [142000.0],
        "high": [146920.0],
        "low": [139060.0],
        "close": [143420.0],
        "volume": [469479],
        "open_interest": [510874],
        "turnover": [6722212.472],
        "settle": [143180.0],
        "pre_settle": [143400.0],
        "variety": ["LC"],
    })

    normalized = normalize_akshare_daily_frame(raw, "GFEX")

    assert normalized.loc[0, "unique_instrument_id"] == "GFEX|F|LC|2605"
    assert normalized.loc[0, "product_id"] == "LC"
    assert normalized.loc[0, "settlement_price"] == pytest.approx(143180.0)
    assert normalized.loc[0, "pre_settlement_price"] == pytest.approx(143400.0)
    assert pd.Timestamp(normalized.loc[0, "trading_day"]) == pd.Timestamp("2026-01-09")


def test_normalize_akshare_daily_frame_skips_non_standard_symbols():
    raw = pd.DataFrame({
        "symbol": ["SC_TAS2601", "CU2601"],
        "date": ["2026-01-09", "2026-01-09"],
        "open": [1.0, 70000.0],
        "high": [1.0, 70100.0],
        "low": [1.0, 69900.0],
        "close": [1.0, 70050.0],
        "settle": [1.0, 70020.0],
        "pre_settle": [1.0, 69980.0],
    })

    normalized = normalize_akshare_daily_frame(raw, "SHFE")

    assert normalized["unique_instrument_id"].to_list() == ["SHFE|F|CU|2601"]


def test_fetch_akshare_daily_with_retries_handles_transient_empty(monkeypatch):
    import sources.LocalCNFutures.daily_update as daily_update

    calls = 0
    row = {col: None for col in DAYK_COLUMNS}
    row.update({
        "trading_day": pd.Timestamp("2026-05-27"),
        "exchange_id": "GFEX",
        "unique_instrument_id": "GFEX|F|LC|2609",
    })

    def fake_fetch(date: str, market: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            return pd.DataFrame(columns=DAYK_COLUMNS)
        return pd.DataFrame([row])

    monkeypatch.setattr(daily_update, "fetch_akshare_daily", fake_fetch)
    monkeypatch.setattr(daily_update.time, "sleep", lambda _: None)

    frame = fetch_akshare_daily_with_retries("20260527", "GFEX")

    assert calls == 2
    assert frame["unique_instrument_id"].to_list() == ["GFEX|F|LC|2609"]


def test_update_dayk_uses_cffex_monthly_fetch(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake_cffex_monthly(year_month: str):
        calls.append(year_month)
        row = {col: None for col in DAYK_COLUMNS}
        row.update({
            "trading_day": pd.Timestamp("2026-07-03"),
            "trade_time": pd.Timestamp("2026-07-03"),
            "trade_timestamp": 1783036800000,
            "exchange_id": "CFFEX",
            "instrument_id": "IF2607",
            "unique_instrument_id": "CFFEX|F|IF|2607",
            "settlement_price": 4000.0,
            "pre_settlement_price": 3990.0,
        })
        return pd.DataFrame([row])

    def fail_daily(*args, **kwargs):
        raise AssertionError("CFFEX should use monthly zip fetch, not daily AKShare fetch")

    import sources.LocalCNFutures.daily_update as daily_update

    monkeypatch.setattr(daily_update, "fetch_cffex_monthly_daily", fake_cffex_monthly)
    monkeypatch.setattr(daily_update, "fetch_akshare_daily", fail_daily)
    path = tmp_path / "data_dayk.parquet"

    report = update_data_dayk_from_akshare(
        start_date="20260701",
        end_date="20260703",
        markets=("CFFEX",),
        path=path,
    )

    assert calls == ["202607"]
    assert report.fetched_rows == 1
    assert pd.read_parquet(path)["unique_instrument_id"].to_list() == ["CFFEX|F|IF|2607"]


def test_update_dayk_uses_dce_sina_fallback(monkeypatch, tmp_path):
    minute_dir = tmp_path / "data_mink"
    minute_dir.mkdir()
    pd.DataFrame({"unique_instrument_id": ["DCE|F|A|2607"]}).to_parquet(
        minute_dir / "data_qc_future_mink_202607.parquet",
        index=False,
    )

    def fake_sina(symbol: str):
        assert symbol == "A2607"
        return pd.DataFrame({
            "date": ["2026-07-02", "2026-07-03"],
            "open": [4700.0, 4710.0],
            "high": [4720.0, 4730.0],
            "low": [4690.0, 4700.0],
            "close": [4715.0, 4725.0],
            "volume": [100, 120],
            "hold": [1000, 1001],
            "settle": [4714.0, 4724.0],
        })

    import akshare as ak

    monkeypatch.setattr(ak, "futures_zh_daily_sina", fake_sina)
    path = tmp_path / "data_dayk.parquet"

    report = update_data_dayk_from_akshare(
        start_date="20260703",
        end_date="20260703",
        markets=("DCE",),
        path=path,
        minute_data_dir=minute_dir,
    )

    frame = pd.read_parquet(path)
    assert report.fetched_rows == 1
    assert frame.loc[0, "unique_instrument_id"] == "DCE|F|A|2607"
    assert frame.loc[0, "settlement_price"] == 4724.0
    assert frame.loc[0, "pre_settlement_price"] == 4714.0
