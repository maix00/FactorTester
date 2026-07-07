from __future__ import annotations

from sources.FieldHistory.scripts.audit_transaction_fee_external_sources import parse_sina_fee_html


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
