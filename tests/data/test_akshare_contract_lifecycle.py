from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from sources.AKShare import client
from sources.AKShare import lifecycle as lc


def test_normalize_shfe_maps_expiry_as_last_trading_date():
    df = pd.DataFrame([{
        "合约代码": "cu2409",
        "上市日": datetime.date(2023, 9, 15),
        "到期日": datetime.date(2024, 9, 17),
        "开始交割日": datetime.date(2024, 9, 13),
        "最后交割日": datetime.date(2024, 9, 17),
        "挂牌基准价": 68960.0,
        "交易日": datetime.date(2024, 5, 13),
    }])
    rows = lc.normalize_shfe(df, "20240513")
    assert len(rows) == 1
    row = rows[0]
    assert row["exchange"] == "SHFE"
    assert row["product_code"] == "CU"
    assert row["contract_code"] == "CU2409"
    assert row["list_date"] == "2023-09-15"
    assert row["last_trading_date"] == "2024-09-17"
    assert row["delivery_start_date"] == "2024-09-13"
    assert row["last_delivery_date"] == "2024-09-17"
    assert row["listing_base_price"] == 68960.0
    assert row["source_query_date"] == "20240513"


def test_normalize_dce_has_no_delivery_start_or_base_price():
    df = pd.DataFrame([{
        "品种名称": "豆粕",
        "合约": "m2409",
        "交易单位": 10,
        "最小变动价位": 1.0,
        "开始交易日": datetime.date(2023, 9, 15),
        "最后交易日": datetime.date(2024, 9, 13),
        "最后交割日": datetime.date(2024, 9, 17),
    }])
    rows = lc.normalize_dce(df)
    assert len(rows) == 1
    row = rows[0]
    assert row["exchange"] == "DCE"
    assert row["product_code"] == "M"
    assert row["contract_code"] == "M2409"
    assert row["list_date"] == "2023-09-15"
    assert row["last_trading_date"] == "2024-09-13"
    assert row["last_delivery_date"] == "2024-09-17"
    assert row["delivery_start_date"] is None
    assert row["listing_base_price"] is None
    assert row["source_query_date"] is None


def test_normalize_czce_reads_the_holiday_caveat_column():
    df = pd.DataFrame([{
        "产品名称": "白糖",
        "合约代码": "SR409",
        "产品代码": "SR",
        lc._CZCE_LAST_TRADING_DAY_COLUMN: "2024-09-09",
        "第一交易日": "2023-10-16",
        "交割通知日": "2024-09-11",
        "最后交割日": "2024-09-12",
    }])
    rows = lc.normalize_czce(df, "20240909")
    assert len(rows) == 1
    row = rows[0]
    assert row["contract_code"] == "SR409"
    assert row["product_code"] == "SR"
    assert row["list_date"] == "2023-10-16"
    assert row["last_trading_date"] == "2024-09-09"
    assert row["delivery_notice_date"] == "2024-09-11"
    assert row["last_delivery_date"] == "2024-09-12"


def test_normalize_cffex_has_no_delivery_date():
    df = pd.DataFrame([{
        "查询交易日": datetime.date(2024, 2, 28),
        "品种": "IF",
        "合约代码": "IF2403",
        "合约月份": "2403",
        "挂盘基准价": 3400.0,
        "上市日": datetime.date(2010, 4, 16),
        "最后交易日": datetime.date(2024, 3, 15),
    }])
    rows = lc.normalize_cffex(df, "20240228")
    assert len(rows) == 1
    row = rows[0]
    assert row["exchange"] == "CFFEX"
    assert row["product_code"] == "IF"
    assert row["list_date"] == "2010-04-16"
    assert row["last_trading_date"] == "2024-03-15"
    assert row["listing_base_price"] == 3400.0
    assert row["last_delivery_date"] is None


def test_normalize_gfex_one_shot():
    df = pd.DataFrame([{
        "品种": "SI",
        "合约代码": "si2411",
        "交易单位": 30,
        "最小变动单位": 5,
        "开始交易日": datetime.date(2022, 12, 22),
        "最后交易日": datetime.date(2024, 11, 15),
        "最后交割日": datetime.date(2024, 11, 19),
    }])
    rows = lc.normalize_gfex(df)
    assert len(rows) == 1
    row = rows[0]
    assert row["exchange"] == "GFEX"
    assert row["contract_code"] == "SI2411"
    assert row["source_query_date"] is None


def test_normalize_contract_info_dispatches_by_exchange():
    empty = pd.DataFrame()
    assert lc.normalize_contract_info("SHFE", empty) == []
    with pytest.raises(ValueError):
        lc.normalize_contract_info("NOPE", pd.DataFrame([{"a": 1}]))


def test_upsert_is_insert_once_by_default(tmp_path):
    db_path = str(tmp_path / "cache.sqlite")
    df = pd.DataFrame([{
        "合约代码": "cu2409",
        "上市日": datetime.date(2023, 9, 15),
        "到期日": datetime.date(2024, 9, 17),
        "开始交割日": datetime.date(2024, 9, 13),
        "最后交割日": datetime.date(2024, 9, 17),
        "挂牌基准价": 68960.0,
        "交易日": datetime.date(2024, 5, 13),
    }])
    rows = lc.normalize_shfe(df, "20240513")

    first = lc.upsert_contract_lifecycle(rows, db_path=db_path)
    assert first == {"inserted": 1, "skipped_existing": 0}

    second = lc.upsert_contract_lifecycle(rows, db_path=db_path)
    assert second == {"inserted": 0, "skipped_existing": 1}

    assert lc.known_contract_codes("SHFE", db_path=db_path) == {"CU2409"}

    stored = lc.read_contract_lifecycle(exchange="SHFE", db_path=db_path)
    assert len(stored) == 1
    assert stored.iloc[0]["listing_base_price"] == 68960.0

    changed_rows = [dict(rows[0], listing_base_price=1.0)]
    lc.upsert_contract_lifecycle(changed_rows, db_path=db_path)
    unchanged = lc.read_contract_lifecycle(exchange="SHFE", db_path=db_path)
    assert unchanged.iloc[0]["listing_base_price"] == 68960.0

    lc.upsert_contract_lifecycle(changed_rows, overwrite=True, db_path=db_path)
    overwritten = lc.read_contract_lifecycle(exchange="SHFE", db_path=db_path)
    assert overwritten.iloc[0]["listing_base_price"] == 1.0


def test_read_contract_lifecycle_filters_by_product_and_contract(tmp_path):
    db_path = str(tmp_path / "cache.sqlite")
    gfex_df = pd.DataFrame([
        {
            "品种": "SI",
            "合约代码": "si2411",
            "交易单位": 30,
            "最小变动单位": 5,
            "开始交易日": datetime.date(2022, 12, 22),
            "最后交易日": datetime.date(2024, 11, 15),
            "最后交割日": datetime.date(2024, 11, 19),
        },
        {
            "品种": "SI",
            "合约代码": "si2412",
            "交易单位": 30,
            "最小变动单位": 5,
            "开始交易日": datetime.date(2023, 1, 20),
            "最后交易日": datetime.date(2024, 12, 16),
            "最后交割日": datetime.date(2024, 12, 20),
        },
    ])
    lc.upsert_contract_lifecycle(lc.normalize_gfex(gfex_df), db_path=db_path)

    by_product = lc.read_contract_lifecycle(exchange="GFEX", product_code="SI", db_path=db_path)
    assert len(by_product) == 2

    by_contract = lc.read_contract_lifecycle(contract_code="si2411", db_path=db_path)
    assert len(by_contract) == 1
    assert by_contract.iloc[0]["contract_code"] == "SI2411"


def test_dce_cookie_fetch_matches_akshare_column_shape():
    fake_response = MagicMock()
    fake_response.raise_for_status = lambda: None
    fake_response.json = lambda: {"data": [{
        "contractId": "m2601", "variety": "豆粕", "varietyOrder": "M", "unit": "10",
        "tick": "1.0", "startTradeDate": "20250915", "endTradeDate": "20261113",
        "endDeliveryDate": "20261117",
    }]}
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["headers"] = headers
        return fake_response

    with patch("requests.post", side_effect=fake_post):
        df = client._fetch_contract_info_dce_with_cookie("hNUS9DnJtejwS=abc; hNUS9DnJtejwT=def")

    assert captured["headers"]["Cookie"] == "hNUS9DnJtejwS=abc; hNUS9DnJtejwT=def"
    assert list(df.columns) == ["品种名称", "合约", "交易单位", "最小变动价位", "开始交易日", "最后交易日", "最后交割日"]

    rows = lc.normalize_dce(df)
    assert rows == [{
        "exchange": "DCE",
        "product_code": "M",
        "contract_code": "M2601",
        "list_date": "2025-09-15",
        "last_trading_date": "2026-11-13",
        "delivery_start_date": None,
        "delivery_notice_date": None,
        "last_delivery_date": "2026-11-17",
        "listing_base_price": None,
        "source_query_date": None,
        "source_function": "futures_contract_info_dce",
        "raw_json": rows[0]["raw_json"],
        "fetched_at": rows[0]["fetched_at"],
    }]


def test_fetch_contract_info_dce_uses_cookie_when_env_set(monkeypatch, tmp_path):
    monkeypatch.setenv(client._DCE_COOKIE_ENV, "hNUS9DnJtejwS=abc")
    calls = []
    monkeypatch.setattr(
        client, "_fetch_contract_info_dce_with_cookie",
        lambda cookie: calls.append(cookie) or pd.DataFrame(columns=[
            "品种名称", "合约", "交易单位", "最小变动价位", "开始交易日", "最后交易日", "最后交割日",
        ]),
    )
    db_path = str(tmp_path / "cache.sqlite")

    client.fetch_contract_info_dce(db_path=db_path)

    assert calls == ["hNUS9DnJtejwS=abc"]
