"""Legacy helper functions for settlement-snapshot fee audits.

Use ``audit_field_history.py`` as the public audit entrypoint.  This module
keeps older matching helpers used by
``audit_transaction_fee_settlement_snapshot_alignment.py``; settlement snapshots
are audit evidence only and must not be ingested as FieldHistory events.
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
    raise SystemExit(
        "audit_transaction_fee_announcement_alignment.py is no longer a public audit entrypoint. "
        "Use audit_field_history.py --mode full-history with --settlement-snapshot-jsonl."
    )


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


def _audit_snapshot(
    event: dict[str, Any],
    notices: list[dict[str, Any]],
    *,
    snapshot_index: dict[tuple[str, str, str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    exact = _find_notice(event, notices, allow_prior=False)
    if exact is not None:
        status = "aligned_exact_notice"
        match = exact
    else:
        prior = _find_notice(event, notices, allow_prior=True)
        if prior is not None:
            status = "aligned_prior_notice"
            match = prior
        elif _is_zero_unit_companion_aligned(event, notices, snapshot_index=snapshot_index):
            status = "aligned_unit_companion"
            match = None
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


def _audit_notice_baselines(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    baselines = [item for item in notices if str(item.get("change_type") or "").lower() == "baseline"]
    for first_change in notices:
        if str(first_change.get("change_type") or "change").lower() != "change":
            continue
        if _has_prior_baseline(first_change, baselines):
            continue
        rows.append({
            "alignment_status": "needs_baseline_before_change",
            "data_source": str(first_change.get("data_source") or ""),
            "instrument": str(first_change.get("instrument") or ""),
            "contract_codes": json.dumps(first_change.get("contract_codes") or [], ensure_ascii=False),
            "field_name": str(first_change.get("field_name") or ""),
            "effective_trading_day": str(first_change.get("effective_trading_day") or ""),
            "value": str(first_change.get("value")),
            "snapshot_notice_id": "",
            "matched_notice_id": str(first_change.get("source_notice_id") or ""),
            "matched_notice_day": str(first_change.get("effective_trading_day") or ""),
            "matched_source_url": str(first_change.get("source_url") or ""),
            "event_file": str(first_change.get("_event_file") or ""),
        })
    return rows


def _has_prior_baseline(change: dict[str, Any], baselines: list[dict[str, Any]]) -> bool:
    for baseline in baselines:
        if str(baseline.get("data_source") or "") != str(change.get("data_source") or ""):
            continue
        if str(baseline.get("instrument") or "") != str(change.get("instrument") or ""):
            continue
        if str(baseline.get("instrument_type") or "") != str(change.get("instrument_type") or ""):
            continue
        if str(baseline.get("field_name") or "") != str(change.get("field_name") or ""):
            continue
        if _event_time_key(baseline) >= _event_time_key(change):
            continue
        if not _contract_scope_covers(baseline, change):
            continue
        return True
    return False


def _event_time_key(event: dict[str, Any]) -> tuple[str, str]:
    return (
        str(event.get("effective_trading_day") or ""),
        str(event.get("effective_timestamp") or ""),
    )


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
        if not _contract_scope_covers(notice, snapshot):
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


def _contract_scope_covers(notice: dict[str, Any], snapshot_event: dict[str, Any]) -> bool:
    notice_codes = {str(item).strip().upper() for item in notice.get("contract_codes") or [] if str(item).strip()}
    snapshot = {str(item).strip().upper() for item in snapshot_event.get("contract_codes") or [] if str(item).strip()}
    scope_type = str(notice.get("contract_scope_type") or "").strip().lower()
    if not scope_type:
        scope_type = "explicit" if notice_codes else "all"
    if scope_type == "all":
        return True
    if not snapshot:
        return False
    if scope_type == "explicit":
        return snapshot.issubset(notice_codes)
    start = str(notice.get("contract_code_start") or "").strip().upper()
    end = str(notice.get("contract_code_end") or "").strip().upper()
    if scope_type in {"from_contract", "range"} and start:
        for code in snapshot:
            if _compare_contract_code(code, start) < 0:
                return False
            if scope_type == "range" and end and _compare_contract_code(code, end) > 0:
                return False
        return True
    return False


def _compare_contract_code(left: str, right: str) -> int:
    left_key = _contract_code_sort_key(left)
    right_key = _contract_code_sort_key(right)
    return (left_key > right_key) - (left_key < right_key)


def _contract_code_sort_key(value: Any) -> tuple[int, str]:
    import re

    text = str(value or "").strip().upper()
    match = re.fullmatch(r"(\d{3,4})([A-Z]*)", text)
    if not match:
        return (-1, text)
    number = match.group(1)
    if len(number) == 3:
        number = f"2{number}"
    return (int(number), match.group(2))


def _snapshot_index(snapshots: list[dict[str, Any]]) -> dict[tuple[str, str, str, str, str], dict[str, Any]]:
    return {
        _snapshot_key(event, str(event.get("field_name") or "")): event
        for event in snapshots
    }


def _snapshot_key(event: dict[str, Any], field_name: str) -> tuple[str, str, str, str, str]:
    return (
        str(event.get("data_source") or ""),
        str(event.get("instrument") or ""),
        json.dumps(event.get("contract_codes") or [], ensure_ascii=False),
        str(event.get("effective_trading_day") or ""),
        field_name,
    )


def _is_zero_unit_companion_aligned(
    event: dict[str, Any],
    notices: list[dict[str, Any]],
    *,
    snapshot_index: dict[tuple[str, str, str, str, str], dict[str, Any]],
) -> bool:
    """Treat the unused fee-unit leg as aligned when the active unit leg is supported.

    Settlement parameter feeds store each fee leg as both a money-ratio field
    and a fixed-yuan-per-lot field.  In normal exchange fee schedules exactly
    one of the pair is active, so the inactive zero field should not require a
    separate announcement.  A zero close-today fee is different: if both unit
    fields are zero, it still needs an explicit notice or prior baseline.
    """
    try:
        value = float(event.get("value") or 0.0)
    except (TypeError, ValueError):
        return False
    if abs(value) > 1e-15:
        return False
    field_name = str(event.get("field_name") or "")
    companion = _companion_fee_unit_field(field_name)
    if not companion:
        return False
    companion_event = snapshot_index.get(_snapshot_key(event, companion))
    if companion_event is None:
        return False
    try:
        companion_value = float(companion_event.get("value") or 0.0)
    except (TypeError, ValueError):
        return False
    if abs(companion_value) <= 1e-15:
        return _active_fee_unit_field_before(event, notices) == companion
    return _find_notice(companion_event, notices, allow_prior=False) is not None or _find_notice(
        companion_event,
        notices,
        allow_prior=True,
    ) is not None


def _active_fee_unit_field_before(
    snapshot: dict[str, Any],
    notices: list[dict[str, Any]],
) -> str:
    """Return the latest known active fee-unit field before the snapshot day.

    When an exchange waives a fee, settlement snapshots often show both
    `*ByMoney = 0` and `*ByVolume = 0`.  Only the active unit needs an explicit
    waiver notice.  The inactive unit remains an accounting companion zero if a
    prior baseline or notice established the companion field as the latest active
    unit.  Fee units are historical state, so an older product-level fixed-fee
    baseline must be superseded by a later notional-ratio notice, and vice versa.
    """
    snapshot_day = str(snapshot.get("effective_trading_day") or "")
    leg_fields = _fee_unit_pair_for_field(str(snapshot.get("field_name") or ""))
    if not leg_fields:
        return ""
    candidates: list[dict[str, Any]] = []
    for notice in notices:
        if str(notice.get("data_source") or "") != str(snapshot.get("data_source") or ""):
            continue
        if str(notice.get("instrument") or "") != str(snapshot.get("instrument") or ""):
            continue
        if str(notice.get("field_name") or "") not in leg_fields:
            continue
        if str(notice.get("effective_trading_day") or "") > snapshot_day:
            continue
        if not _contract_scope_covers(notice, snapshot):
            continue
        try:
            if abs(float(notice.get("value") or 0.0)) <= 1e-15:
                continue
        except (TypeError, ValueError):
            continue
        candidates.append(notice)
    if not candidates:
        return ""
    latest = sorted(
        candidates,
        key=lambda item: (
            str(item.get("effective_trading_day") or ""),
            str(item.get("effective_timestamp") or ""),
            1 if str(item.get("contract_scope_type") or "").lower() == "explicit" else 0,
            str(item.get("source_notice_id") or ""),
        ),
        reverse=True,
    )[0]
    return str(latest.get("field_name") or "")


def _fee_unit_pair_for_field(field_name: str) -> set[str]:
    pairs = [
        {"OpenRatioByMoney", "OpenRatioByVolume"},
        {"CloseRatioByMoney", "CloseRatioByVolume"},
        {"CloseTodayRatioByMoney", "CloseTodayRatioByVolume"},
    ]
    for pair in pairs:
        if field_name in pair:
            return pair
    return set()


def _companion_fee_unit_field(field_name: str) -> str:
    pairs = {
        "OpenRatioByMoney": "OpenRatioByVolume",
        "OpenRatioByVolume": "OpenRatioByMoney",
        "CloseRatioByMoney": "CloseRatioByVolume",
        "CloseRatioByVolume": "CloseRatioByMoney",
        "CloseTodayRatioByMoney": "CloseTodayRatioByVolume",
        "CloseTodayRatioByVolume": "CloseTodayRatioByMoney",
    }
    return pairs.get(field_name, "")


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
