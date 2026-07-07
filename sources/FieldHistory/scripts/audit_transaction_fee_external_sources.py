"""Audit exchange TransactionFee baselines against secondary public sources.

This script does not ingest fee events.  It writes an audit table that compares
the current exchange fee view against public secondary pages such as Sina's
futures fee table.  Official exchange notices remain the source of truth for
historical events; secondary pages are cross-check evidence.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sources.FieldHistory.views.TransactionFee import (  # noqa: E402
    FEE_UNIT_CLASSIFICATION_TABLE,
    save_unified_table,
)
from tools.data.field_history import _ensure_store_registered  # noqa: E402
from tools.data.hub import DataHub  # noqa: E402


AUDIT_TABLE = "field_history_transaction_fee_external_audit"
SINA_FEE_URL = "https://vip.stock.finance.sina.com.cn/q/view/vPositions_fee.php"
LEG_BY_TITLE = {
    "开仓手续费": "open",
    "平昨仓手续费": "close",
    "平今仓手续费": "close_today",
}


@dataclass(frozen=True)
class ExternalFeeRow:
    source_name: str
    source_url: str
    instrument: str
    contract_code: str
    contract_label: str
    leg: str
    unit: str
    value: float
    raw_value: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp", help="DataHub SQLite store key")
    parser.add_argument("--source", default=SINA_FEE_URL, help="Sina URL or local HTML file")
    parser.add_argument("--source-name", default="Sina", help="External source name")
    parser.add_argument("--output-csv", default="", help="Optional CSV copy of audit rows")
    args = parser.parse_args(argv)

    text, source_url = _load_html(args.source)
    external = parse_sina_fee_html(text, source_url=source_url, source_name=args.source_name)
    if not external:
        raise ValueError(f"no fee rows parsed from {args.source!r}")

    db_path = save_unified_table(store_key=args.store_key)
    audit = build_external_audit_frame(external, store_key=args.store_key)
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, args.store_key)
    with hub.connect_store(args.store_key) as conn:
        audit.to_sql(AUDIT_TABLE, conn, if_exists="replace", index=False)
    if args.output_csv:
        out = Path(args.output_csv).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        audit.to_csv(out, index=False)
    print(json.dumps({
        "db_path": db_path,
        "table": AUDIT_TABLE,
        "parsed_rows": len(external),
        "audit_rows": len(audit),
        "statuses": audit["audit_status"].value_counts().to_dict() if not audit.empty else {},
    }, ensure_ascii=False, indent=2))
    return 0


def parse_sina_fee_html(text: str, *, source_url: str = SINA_FEE_URL, source_name: str = "Sina") -> list[ExternalFeeRow]:
    rows: list[ExternalFeeRow] = []
    row_pattern = re.compile(
        r"<td class='heyuealink'>(?P<label>.*?)\(<b>(?P<contract>.*?)</b>\)</td>(?P<body>.*?)(?=<td class='heyuealink'>|</table>)",
        re.S,
    )
    fee_pattern = re.compile(r"<td[^>]*title='(?P<title>[^']*手续费[^']*)'[^>]*>(?P<value>.*?)</td>", re.S)
    for match in row_pattern.finditer(text):
        label = _clean_text(match.group("label"))
        contract_code = _clean_text(match.group("contract")).lower()
        instrument = _instrument_from_contract(contract_code)
        if not instrument:
            continue
        fee_cells = fee_pattern.findall(match.group("body"))
        for title, raw_value_html in fee_cells:
            leg = _leg_from_title(title)
            if leg is None:
                continue
            parsed = _parse_fee_cell(_clean_text(raw_value_html))
            if parsed is None:
                continue
            unit, value = parsed
            rows.append(ExternalFeeRow(
                source_name=source_name,
                source_url=source_url,
                instrument=instrument,
                contract_code=contract_code,
                contract_label=label,
                leg=leg,
                unit=unit,
                value=value,
                raw_value=_clean_text(raw_value_html),
            ))
    return rows


def build_external_audit_frame(rows: list[ExternalFeeRow], *, store_key: str = "openctp") -> pd.DataFrame:
    classification = _latest_classification(store_key=store_key)
    records: list[dict[str, Any]] = []
    for row in rows:
        contract_suffix = _contract_suffix(row.contract_code)
        match = (
            classification.get((row.instrument, contract_suffix, row.leg))
            or classification.get((row.instrument, "", row.leg))
        )
        exchange_unit = match["unit"] if match else ""
        exchange_value = match["value"] if match else None
        delta = None if exchange_value is None else row.value - float(exchange_value)
        records.append({
            "source_name": row.source_name,
            "source_url": row.source_url,
            "instrument": row.instrument,
            "contract_code": row.contract_code,
            "contract_label": row.contract_label,
            "leg": row.leg,
            "source_unit": row.unit,
            "source_value": row.value,
            "raw_value": row.raw_value,
            "exchange_unit": exchange_unit,
            "exchange_value": exchange_value,
            "delta": delta,
            "audit_status": _audit_status(row.unit, row.value, exchange_unit, exchange_value),
        })
    return pd.DataFrame(records, columns=[
        "source_name",
        "source_url",
        "instrument",
        "contract_code",
        "contract_label",
        "leg",
        "source_unit",
        "source_value",
        "raw_value",
        "exchange_unit",
        "exchange_value",
        "delta",
        "audit_status",
    ])


def _latest_classification(*, store_key: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    with hub.connect_store(store_key) as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (FEE_UNIT_CLASSIFICATION_TABLE,),
        ).fetchone()
        if table_exists is None:
            return {}
        frame = pd.read_sql_query(f"SELECT * FROM {FEE_UNIT_CLASSIFICATION_TABLE}", conn)
    if frame.empty:
        return {}
    frame["effective_trading_day"] = frame["effective_trading_day"].astype(str)
    frame["contract_key"] = frame["contract_codes"].map(_contract_key_from_json)
    frame = frame.sort_values(["instrument", "contract_key", "effective_trading_day", "effective_timestamp"])
    latest = frame.groupby(["instrument", "contract_key"], as_index=False, sort=False).tail(1)
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in latest.itertuples(index=False):
        for leg in ("open", "close", "close_today"):
            result[(str(item.instrument), str(item.contract_key), leg)] = {
                "unit": getattr(item, f"{leg}_unit"),
                "value": getattr(item, f"{leg}_{getattr(item, f'{leg}_unit')}") if getattr(item, f"{leg}_unit") in {"money", "volume"} else 0.0,
            }
    return result


def _load_html(source: str) -> tuple[str, str]:
    if source.startswith(("http://", "https://")):
        request = Request(source, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=30) as response:
            raw = response.read()
        return raw.decode("utf-8", errors="ignore"), source
    path = Path(source).expanduser().resolve()
    return path.read_text(encoding="utf-8"), str(path)


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).replace("\xa0", " ").strip()


def _instrument_from_contract(contract_code: str) -> str:
    match = re.match(r"([a-zA-Z]+)", contract_code.strip())
    return match.group(1).upper() if match else ""


def _contract_suffix(contract_code: str) -> str:
    match = re.search(r"(\d+[A-Za-z]?)$", contract_code.strip())
    return match.group(1).upper() if match else ""


def _contract_key_from_json(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"", "[]"}:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [text]
    if not isinstance(parsed, list) or not parsed:
        return ""
    suffixes = sorted({_contract_suffix(str(item)) for item in parsed if _contract_suffix(str(item))})
    return ",".join(suffixes)


def _leg_from_title(title: str) -> str | None:
    for prefix, leg in LEG_BY_TITLE.items():
        if prefix in title:
            return leg
    return None


def _parse_fee_cell(raw: str) -> tuple[str, float] | None:
    text = raw.strip()
    if not text:
        return None
    ratio_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*/\s*万分之", text)
    if ratio_match:
        value = float(ratio_match.group(1)) / 10000.0
        return ("zero", 0.0) if abs(value) <= 1e-15 else ("money", value)
    yuan_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*元", text)
    if yuan_match:
        value = float(yuan_match.group(1))
        return ("zero", 0.0) if abs(value) <= 1e-15 else ("volume", value)
    return None


def _audit_status(source_unit: str, source_value: float, exchange_unit: str, exchange_value: Any) -> str:
    if not exchange_unit:
        return "missing_exchange_baseline"
    if source_unit == "zero" and abs(float(exchange_value or 0.0)) <= 1e-15:
        return "matched"
    if exchange_unit == "zero" and abs(source_value) <= 1e-15:
        return "matched"
    if source_unit != exchange_unit:
        return "unit_mismatch"
    if exchange_value is None:
        return "missing_exchange_value"
    delta = source_value - float(exchange_value)
    if abs(delta) <= 1e-12:
        return "matched"
    addon = 0.0000008 if source_unit == "money" else 0.01
    if abs(delta - addon) <= 1e-9:
        return "matched_with_broker_addon"
    return "value_mismatch"


if __name__ == "__main__":
    raise SystemExit(main())
