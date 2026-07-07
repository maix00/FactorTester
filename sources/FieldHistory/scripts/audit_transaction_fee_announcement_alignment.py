"""Audit settlement-parameter fee events against exchange announcement events.

Daily exchange settlement parameter feeds are official value snapshots, but
they do not always carry the adjustment notice id.  This script checks whether
snapshot-derived TransactionFee change events are also supported by an exchange
announcement event in our event library.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


FEE_FIELDS = {
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events-dir",
        default="sources/FieldHistory/events/TransactionFee",
        help="Directory containing TransactionFee JSONL event files.",
    )
    parser.add_argument("--output-csv", required=True, help="Audit rows CSV path.")
    args = parser.parse_args(argv)

    events_dir = Path(args.events_dir).expanduser().resolve()
    events = _load_events(events_dir)
    snapshots = [event for event in events if _is_snapshot_event(event)]
    notices = [event for event in events if _is_notice_event(event)]

    rows = [_audit_snapshot(event, notices) for event in snapshots]
    output = Path(args.output_csv).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_columns())
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps({
        "output": str(output),
        "snapshot_events": len(snapshots),
        "notice_events": len(notices),
        "status_counts": Counter(row["alignment_status"] for row in rows),
        "status_counts_by_exchange": {
            exchange: Counter(row["alignment_status"] for row in rows if row["data_source"] == exchange)
            for exchange in sorted({row["data_source"] for row in rows})
        },
    }, ensure_ascii=False, indent=2, default=dict))
    return 0


def _load_events(events_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(events_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                event = json.loads(text)
                if event.get("field_group") == "TransactionFee" and event.get("field_name") in FEE_FIELDS:
                    event["_event_file"] = path.name
                    events.append(event)
    return events


def _is_snapshot_event(event: dict[str, Any]) -> bool:
    return "settlement-parameters-" in str(event.get("source_notice_id") or "")


def _is_notice_event(event: dict[str, Any]) -> bool:
    return bool(event.get("source_notice_id")) and not _is_snapshot_event(event)


def _audit_snapshot(event: dict[str, Any], notices: list[dict[str, Any]]) -> dict[str, Any]:
    exact = _find_notice(event, notices, allow_prior=False)
    if exact is not None:
        status = "aligned_exact_notice"
        match = exact
    else:
        prior = _find_notice(event, notices, allow_prior=True)
        if prior is not None:
            status = "aligned_prior_notice"
            match = prior
        else:
            status = "needs_announcement"
            match = None
    return {
        "alignment_status": status,
        "data_source": str(event.get("data_source") or ""),
        "instrument": str(event.get("instrument") or ""),
        "contract_codes": json.dumps(event.get("contract_codes") or [], ensure_ascii=False),
        "field_name": str(event.get("field_name") or ""),
        "effective_trading_day": str(event.get("effective_trading_day") or ""),
        "value": str(event.get("value")),
        "snapshot_notice_id": str(event.get("source_notice_id") or ""),
        "matched_notice_id": "" if match is None else str(match.get("source_notice_id") or ""),
        "matched_notice_day": "" if match is None else str(match.get("effective_trading_day") or ""),
        "matched_source_url": "" if match is None else str(match.get("source_url") or ""),
        "event_file": str(event.get("_event_file") or ""),
    }


def _find_notice(
    snapshot: dict[str, Any],
    notices: list[dict[str, Any]],
    *,
    allow_prior: bool,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for notice in notices:
        if str(notice.get("data_source") or "") != str(snapshot.get("data_source") or ""):
            continue
        if str(notice.get("instrument") or "") != str(snapshot.get("instrument") or ""):
            continue
        if str(notice.get("field_name") or "") != str(snapshot.get("field_name") or ""):
            continue
        if abs(float(notice.get("value") or 0.0) - float(snapshot.get("value") or 0.0)) > 1e-15:
            continue
        if not _contract_scope_covers(notice.get("contract_codes") or [], snapshot.get("contract_codes") or []):
            continue
        notice_day = str(notice.get("effective_trading_day") or "")
        snapshot_day = str(snapshot.get("effective_trading_day") or "")
        if allow_prior:
            if notice_day > snapshot_day:
                continue
        elif notice_day != snapshot_day:
            continue
        candidates.append(notice)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            str(item.get("effective_trading_day") or ""),
            len(item.get("contract_codes") or []),
            str(item.get("source_notice_id") or ""),
        ),
        reverse=True,
    )[0]


def _contract_scope_covers(notice_codes: list[Any], snapshot_codes: list[Any]) -> bool:
    notice = {str(item).strip() for item in notice_codes if str(item).strip()}
    snapshot = {str(item).strip() for item in snapshot_codes if str(item).strip()}
    if not notice:
        return True
    return bool(snapshot) and snapshot.issubset(notice)


def _columns() -> list[str]:
    return [
        "alignment_status",
        "data_source",
        "instrument",
        "contract_codes",
        "field_name",
        "effective_trading_day",
        "value",
        "snapshot_notice_id",
        "matched_notice_id",
        "matched_notice_day",
        "matched_source_url",
        "event_file",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
