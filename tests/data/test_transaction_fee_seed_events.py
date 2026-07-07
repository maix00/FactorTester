from __future__ import annotations

import json
from pathlib import Path


EVENTS_PATH = Path("sources/FieldHistory/events/TransactionFee/official_seed_events.jsonl")
SETTLEMENT_SNAPSHOT_PATH = Path(
    "sources/FieldHistory/events/TransactionFee/exchange_settlement_snapshots_20260309_20260623.jsonl"
)


def _events() -> list[dict[str, object]]:
    return [json.loads(line) for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines()]


def _settlement_snapshot_events() -> list[dict[str, object]]:
    return [json.loads(line) for line in SETTLEMENT_SNAPSHOT_PATH.read_text(encoding="utf-8").splitlines()]


def test_ao_2025_fee_notice_uses_official_rate_and_url() -> None:
    rows = [
        row
        for row in _events()
        if row["source_notice_id"] == "上期发〔2025〕92号" and row["instrument"] == "AO"
    ]

    assert rows
    assert {row["source_url"] for row in rows} == {
        "https://www.shfe.com.cn/publicnotice/notice/202504/t20250401_824937.html"
    }

    by_field = {row["field_name"]: row["value"] for row in rows}
    assert by_field["OpenRatioByMoney"] == 0.0001
    assert by_field["CloseRatioByMoney"] == 0.0001
    assert by_field["CloseTodayRatioByMoney"] == 0.0001
    assert by_field["OpenRatioByVolume"] == 0.0
    assert by_field["CloseRatioByVolume"] == 0.0
    assert by_field["CloseTodayRatioByVolume"] == 0.0


def test_known_exchange_notice_urls_are_official_when_available() -> None:
    rows = _events()

    zc_urls = {
        row["source_url"]
        for row in rows
        if row["source_notice_id"] == "郑商函〔2021〕191号" and row["instrument"] == "ZC"
    }
    assert zc_urls == {
        "https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2021/04/1605586112745060.htm"
    }

    shfe_urls = {
        row["source_url"]
        for row in rows
        if row["source_notice_id"] == "上期发〔2026〕3号" and row["instrument"] in {"AG", "SN"}
    }
    assert shfe_urls == {
        "https://www.shfe.com.cn/publicnotice/notice/202601/t20260107_830048.html"
    }


def test_czce_2026_fee_adjustments_are_stored_as_exchange_events() -> None:
    rows = _events()
    by_notice_instrument = {
        (row["source_notice_id"], row["instrument"], row["field_name"]): row
        for row in rows
        if row["source_notice_id"] in {"郑商函〔2026〕476号", "郑商函〔2026〕477号"}
    }

    assert by_notice_instrument[("郑商函〔2026〕476号", "FG", "OpenRatioByVolume")]["value"] == 2.0
    assert by_notice_instrument[("郑商函〔2026〕476号", "FG", "CloseTodayRatioByVolume")]["value"] == 2.0
    assert by_notice_instrument[("郑商函〔2026〕476号", "SA", "OpenRatioByMoney")]["value"] == 0.0001
    assert by_notice_instrument[("郑商函〔2026〕476号", "SA", "CloseTodayRatioByMoney")]["value"] == 0.0001

    assert by_notice_instrument[("郑商函〔2026〕477号", "PL", "OpenRatioByVolume")]["value"] == 3.0
    assert by_notice_instrument[("郑商函〔2026〕477号", "PL", "CloseRatioByVolume")]["value"] == 3.0
    assert by_notice_instrument[("郑商函〔2026〕477号", "PL", "CloseTodayRatioByVolume")]["value"] == 0.0
    assert by_notice_instrument[("郑商函〔2026〕477号", "AP", "CloseTodayRatioByVolume")]["value"] == 10.0


def test_czce_2024_close_today_zero_and_cotton_yarn_fee_events() -> None:
    rows = _events()

    close_today_zero = [
        row
        for row in rows
        if row["source_notice_id"] == "郑商函〔2024〕19号"
        and row["field_name"] in {"CloseTodayRatioByMoney", "CloseTodayRatioByVolume"}
    ]
    assert {row["instrument"] for row in close_today_zero} == {"CF", "CY", "SR", "TA", "SM", "SF"}
    assert {row["value"] for row in close_today_zero} == {0.0}

    cy_product = {
        row["field_name"]: row
        for row in rows
        if row["source_notice_id"] == "郑商函〔2024〕587号"
        and row["instrument"] == "CY"
        and row["contract_codes"] == []
    }
    assert cy_product["OpenRatioByVolume"]["value"] == 1.0
    assert cy_product["CloseRatioByVolume"]["value"] == 1.0

    cy_exception_codes = {
        tuple(row["contract_codes"])[0]
        for row in rows
        if row["source_notice_id"] == "郑商函〔2024〕587号"
        and row["instrument"] == "CY"
        and row["field_name"] == "OpenRatioByVolume"
        and row["contract_codes"]
        and row["value"] == 4.0
    }
    assert cy_exception_codes == {"2409", "2410", "2411", "2412", "2501", "2502"}


def test_shfe_ine_2026_energy_fee_adjustments_are_stored_as_exchange_events() -> None:
    rows = _events()
    by_notice_instrument = {
        (row["source_notice_id"], row["instrument"], row["field_name"]): row
        for row in rows
        if row["source_notice_id"] in {"上期发〔2026〕95号", "上能发〔2026〕24号", "上能发〔2026〕29号"}
    }

    assert by_notice_instrument[("上期发〔2026〕95号", "FU", "OpenRatioByMoney")]["value"] == 0.0001
    assert by_notice_instrument[("上期发〔2026〕95号", "FU", "CloseRatioByMoney")]["value"] == 0.0001
    assert by_notice_instrument[("上期发〔2026〕95号", "FU", "CloseTodayRatioByMoney")]["value"] == 0.0003

    assert by_notice_instrument[("上能发〔2026〕24号", "SC", "CloseTodayRatioByVolume")]["value"] == 60.0
    assert by_notice_instrument[("上能发〔2026〕24号", "LU", "CloseTodayRatioByMoney")]["value"] == 0.00003

    assert by_notice_instrument[("上能发〔2026〕29号", "SC", "OpenRatioByVolume")]["value"] == 40.0
    assert by_notice_instrument[("上能发〔2026〕29号", "SC", "CloseTodayRatioByVolume")]["value"] == 240.0
    assert by_notice_instrument[("上能发〔2026〕29号", "LU", "OpenRatioByMoney")]["value"] == 0.0001
    assert by_notice_instrument[("上能发〔2026〕29号", "LU", "CloseTodayRatioByMoney")]["value"] == 0.0003


def test_shfe_2024_asphalt_close_today_fee_is_zero() -> None:
    rows = [
        row
        for row in _events()
        if row["source_notice_id"] == "上期发〔2024〕126号" and row["instrument"] == "BU"
    ]

    assert {row["field_name"] for row in rows} == {"CloseTodayRatioByMoney", "CloseTodayRatioByVolume"}
    assert {row["value"] for row in rows} == {0.0}
    assert {row["source_url"] for row in rows} == {
        "https://www.shfe.com.cn/publicnotice/notice/202404/t20240423_801626.html"
    }


def test_shfe_new_product_fee_baselines_and_later_adjustment_are_stored() -> None:
    rows = [
        row
        for row in _events()
        if row["instrument"] in {"AD", "OP"}
        and row["source_notice_id"] in {"上期发〔2025〕157号", "上期发〔2025〕234号", "上期发〔2025〕317号"}
    ]
    by_key = {
        (row["source_notice_id"], row["instrument"], row["field_name"]): row["value"]
        for row in rows
    }

    for notice_id, instrument in [("上期发〔2025〕157号", "AD"), ("上期发〔2025〕234号", "OP")]:
        assert by_key[(notice_id, instrument, "OpenRatioByMoney")] == 0.0001
        assert by_key[(notice_id, instrument, "CloseRatioByMoney")] == 0.0001
        assert by_key[(notice_id, instrument, "CloseTodayRatioByMoney")] == 0.0001
        assert by_key[(notice_id, instrument, "OpenRatioByVolume")] == 0.0
        assert by_key[(notice_id, instrument, "CloseRatioByVolume")] == 0.0
        assert by_key[(notice_id, instrument, "CloseTodayRatioByVolume")] == 0.0

    for instrument in ["AD", "OP"]:
        assert by_key[("上期发〔2025〕317号", instrument, "OpenRatioByMoney")] == 0.00005
        assert by_key[("上期发〔2025〕317号", instrument, "CloseRatioByMoney")] == 0.00005
        assert by_key[("上期发〔2025〕317号", instrument, "CloseTodayRatioByMoney")] == 0.0


def test_exchange_settlement_snapshots_store_contract_level_fee_legs() -> None:
    rows = _settlement_snapshot_events()
    by_key = {
        (
            row["source_notice_id"],
            row["instrument"],
            tuple(row["contract_codes"]),
            row["field_name"],
        ): row
        for row in rows
    }

    assert by_key[
        ("SHFE-settlement-parameters-20260309", "CU", ("2603",), "CloseTodayRatioByMoney")
    ]["value"] == 0.000025
    assert by_key[
        ("SHFE-settlement-parameters-20260309", "RB", ("2606",), "OpenRatioByMoney")
    ]["value"] == 0.00002
    assert by_key[
        ("SHFE-settlement-parameters-20260309", "RB", ("2606",), "CloseTodayRatioByMoney")
    ]["value"] == 0.00001
    assert by_key[
        ("SHFE-settlement-parameters-20260623", "SS", ("2607",), "OpenRatioByVolume")
    ]["value"] == 2.0
    assert by_key[
        ("SHFE-settlement-parameters-20260623", "SS", ("2607",), "CloseTodayRatioByVolume")
    ]["value"] == 1.0
    assert by_key[
        ("INE-settlement-parameters-20260623", "EC", ("2607",), "CloseTodayRatioByMoney")
    ]["value"] == 0.0003
    assert by_key[
        ("CFFEX-settlement-parameters-20260623", "IC", ("2607",), "CloseTodayRatioByMoney")
    ]["value"] == 0.00023
    assert by_key[
        ("CFFEX-settlement-parameters-20260623", "T", ("2609",), "CloseTodayRatioByVolume")
    ]["value"] == 0.0
    assert by_key[
        ("CZCE-settlement-parameters-20260623", "AP", ("2610",), "CloseTodayRatioByVolume")
    ]["value"] == 10.0
    assert by_key[
        ("CZCE-settlement-parameters-20260310", "SA", ("2606",), "OpenRatioByMoney")
    ]["value"] == 0.0002
    assert by_key[
        ("CZCE-settlement-parameters-20260609", "SA", ("2606",), "OpenRatioByMoney")
    ]["value"] == 0.0001
    assert by_key[
        ("CZCE-settlement-parameters-20260623", "PL", ("2607",), "OpenRatioByVolume")
    ]["value"] == 3.0
    assert by_key[
        ("CZCE-settlement-parameters-20260623", "PL", ("2607",), "CloseTodayRatioByVolume")
    ]["value"] == 0.0
