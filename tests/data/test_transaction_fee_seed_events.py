from __future__ import annotations

import json
from pathlib import Path


EVENTS_PATH = Path("sources/FieldHistory/events/TransactionFee/official_seed_events.jsonl")


def _events() -> list[dict[str, object]]:
    return [json.loads(line) for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines()]


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
