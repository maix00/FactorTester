from __future__ import annotations

from sources.FieldHistory.scripts.audit_transaction_fee_external_sources import (
    _audit_status,
    parse_sina_fee_html,
)


def test_parse_sina_fee_html_extracts_contract_fee_units() -> None:
    html = """
    <td class='heyuealink'>豆一2605 (<b>a2605 </b>)</td>
    <td title='开仓手续费(万分之几或者元)' >2元</td>
    <td title='平昨仓手续费(万分之几或者元)' >2元</td>
    <td title='平今仓手续费(万分之几或者元)' >2元</td>
    <td class='heyuealink'>鸡蛋2603 (<b>jd2603 </b>)</td>
    <td title='开仓手续费(万分之几或者元)' >1.5/万分之(4.7元)</td>
    <td title='平昨仓手续费(万分之几或者元)' >1.5/万分之(4.7元)</td>
    <td title='平今仓手续费(万分之几或者元)' >0元</td>
    </table>
    """

    rows = parse_sina_fee_html(html)

    assert [(row.instrument, row.contract_code, row.leg, row.unit, row.value) for row in rows] == [
        ("A", "a2605", "open", "volume", 2.0),
        ("A", "a2605", "close", "volume", 2.0),
        ("A", "a2605", "close_today", "volume", 2.0),
        ("JD", "jd2603", "open", "money", 0.00015),
        ("JD", "jd2603", "close", "money", 0.00015),
        ("JD", "jd2603", "close_today", "zero", 0.0),
    ]


def test_official_settlement_snapshot_disagreement_is_not_exchange_mismatch() -> None:
    assert _audit_status(
        "volume",
        240.0,
        "volume",
        20.0,
        exchange_source_notice_ids='["INE-settlement-parameters-20260707"]',
    ) == "secondary_disagrees_official_snapshot"
    assert _audit_status(
        "zero",
        0.0,
        "money",
        0.000025,
        exchange_source_notice_ids='["SHFE-settlement-parameters-20260707"]',
    ) == "secondary_disagrees_official_snapshot"


def test_secondary_contract_missing_from_latest_snapshot_is_not_exchange_mismatch() -> None:
    assert _audit_status(
        "volume",
        20.01,
        "volume",
        40.0,
        exchange_source_notice_ids='["上能发〔2026〕29号"]',
        missing_from_latest_snapshot=True,
    ) == "secondary_contract_not_in_latest_official_snapshot"
