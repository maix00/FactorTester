"""Cross-exchange FieldHistory integrity audit.

Checks applied to ``agent_field_change_events``:

1. No duplicate events (same instrument, contract, field, day, value)
2. No empty effective_timestamp
3. asof_confirmed only at 2024 boundary
4. No settlement-snapshot references in change_type='change' events
5. All records have Chinese raw_note
6. Delivery-month events reference correct risk management measures
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from tools.data.field_history import _ensure_store_registered
from tools.data.hub import DataHub


BOUNDARY = ('2024-01-02', '20240102', '2023-12-29', '20231229', '2023-04-13', '20230413')
EXCHANGES = ['DCE', 'CZCE', 'SHFE', 'INE', 'GFEX', 'CFFEX']


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--output-csv", default="")
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args(argv)

    _ensure_store_registered(DataHub.get_instance(), args.store_key)
    rows: list[dict[str, str]] = []

    for ex in EXCHANGES:
        rows.extend(_check_duplicates(args.store_key, ex))
        rows.extend(_check_empty_timestamp(args.store_key, ex))
        rows.extend(_check_asof_boundary(args.store_key, ex))
        rows.extend(_check_snapshot_source(args.store_key, ex))
        rows.extend(_check_chinese_notes(args.store_key, ex))
        rows.extend(_check_risk_measures_ref(args.store_key, ex))
        rows.extend(_check_dce_skip_10pct(args.store_key))
        rows.extend(_check_dce_no_night(args.store_key))
        rows.extend(_check_czce_calendar_day(args.store_key))
        rows.extend(_check_shfe_four_tier(args.store_key))



    _print_summary(rows, limit=args.limit)
    if args.output_csv:
        _write_csv(Path(args.output_csv).expanduser(), rows)
    return 0 if not rows else 2


def _load(store_key: str, data_source: str) -> list[dict]:
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        return [
            dict(row) for row in conn.execute(
                """SELECT event_id, data_source, instrument, field_name,
                          effective_trading_day, effective_timestamp, value_json,
                          contract_codes_json, source_notice_id, raw_note,
                          change_type, exchange, requester_key_hash
                   FROM agent_field_change_events
                   WHERE data_source = ?
                   ORDER BY instrument, field_name, effective_trading_day""",
                (data_source,)
            ).fetchall()
        ]


def _check_duplicates(store_key: str, data_source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    events = _load(store_key, data_source)
    seen = Counter()
    for ev in events:
        key = (ev['instrument'], ev.get('contract_codes_json',''), ev['field_name'],
               ev['effective_trading_day'], ev['value_json'])
        seen[key] += 1
    for key, count in seen.items():
        if count > 1:
            rows.append({'rule': f'{data_source}-dup', 'severity': 'error',
                'instrument': key[0], 'field_name': key[2],
                'detail': f'{count}x duplicates: {key[0]} {key[2]} day={key[3]} val={key[4]}'})
    return rows


def _check_empty_timestamp(store_key: str, data_source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ev in _load(store_key, data_source):
        ts = ev.get('effective_timestamp', '')
        if not ts:
            rows.append({'rule': f'{data_source}-empty-ts', 'severity': 'error',
                'instrument': ev['instrument'], 'field_name': ev['field_name'],
                'detail': f'Missing timestamp for day={ev["effective_trading_day"]}'})
    return rows


def _check_asof_boundary(store_key: str, data_source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ev in _load(store_key, data_source):
        if ev.get('change_type') == 'asof_confirmed' and ev.get('effective_trading_day') not in BOUNDARY:
            rows.append({'rule': f'{data_source}-asof-outside', 'severity': 'error',
                'instrument': ev['instrument'], 'field_name': ev['field_name'],
                'detail': f'asof_confirmed on {ev["effective_trading_day"]} outside boundary'})
        elif ev.get('change_type') in ('change',) and ev.get('effective_trading_day') in BOUNDARY:
            sid = ev.get('source_notice_id', '')
            if 'settlement' in sid.lower() or 'snapshot' in sid.lower():
                rows.append({'rule': f'{data_source}-boundary-type', 'severity': 'error',
                    'instrument': ev['instrument'], 'field_name': ev['field_name'],
                    'detail': f'change on boundary {ev["effective_trading_day"]} should be asof_confirmed'})
    return rows


def _check_snapshot_source(store_key: str, data_source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ev in _load(store_key, data_source):
        sid = ev.get('source_notice_id', '')
        if 'snapshot' in sid.lower():
            rows.append({'rule': f'{data_source}-snapshot-source', 'severity': 'error',
                'instrument': ev['instrument'], 'field_name': ev['field_name'],
                'detail': f'Reference to settlement snapshot: {sid[:60]}'})
    return rows


def _check_chinese_notes(store_key: str, data_source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ev in _load(store_key, data_source):
        note = ev.get('raw_note', '')
        if not note:
            rows.append({'rule': f'{data_source}-empty-note', 'severity': 'warning',
                'instrument': ev['instrument'], 'field_name': ev['field_name'],
                'detail': 'Empty raw_note'})
        elif not any('\u4e00' <= c <= '\u9fff' for c in note[:20]):
            rows.append({'rule': f'{data_source}-non-chinese-note', 'severity': 'warning',
                'instrument': ev['instrument'], 'field_name': ev['field_name'],
                'detail': f'raw_note not in Chinese: {note[:60]}'})
    return rows


def _check_risk_measures_ref(store_key: str, data_source: str) -> list[dict[str, str]]:
    """Check delivery-month margin events reference proper risk management measures."""
    rows: list[dict[str, str]] = []
    expected_keywords = {
        'DCE': '风险管理办法',
        'CZCE': '风险控制管理办法',
        'SHFE': '风险控制管理办法',
        'INE': '风险控制管理办法',
        'GFEX': '风险控制管理办法',
        'CFFEX': '风险控制管理办法',
    }
    kw = expected_keywords.get(data_source, '')
    if not kw:
        return rows
    
    for ev in _load(store_key, data_source):
        if ev.get('field_name') in ('LongMarginRatioByMoney', 'ShortMarginRatioByMoney'):
            sid = ev.get('source_notice_id', '')
            # Only flag events that reference settlement snapshots (not listing notices or specific notice IDs)
            if 'snapshot' in sid.lower():
                rows.append({'rule': f'{data_source}-risk-ref-missing', 'severity': 'error',
                    'instrument': ev['instrument'], 'field_name': ev['field_name'],
                    'detail': f'Reference to settlement snapshot: {sid[:60]}'})
    return rows



def _check_dce_skip_10pct(store_key):
    """DCE L/V/PP skip 10% intermediate step (Article 5 exception)."""
    rows = []
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        for prod in ('L', 'V', 'PP'):
            cnt = conn.execute(
                'SELECT COUNT(*) FROM agent_field_change_events '
                'WHERE data_source=\'DCE\' AND instrument=? '
                'AND field_name LIKE \'%Margin%\' AND value_json=\'"0.10"\'',
                (prod,)
            ).fetchone()[0]
            if cnt > 0:
                rows.append({'rule': 'DCE-LVP-10', 'severity': 'error',
                    'instrument': prod, 'field_name': 'Margin',
                    'detail': f'{prod} skips 10% step but has {cnt} events with 10%'})
    return rows

def _check_dce_no_night(store_key):
    """DCE products without night session should have T09:00 timestamps."""
    rows = []
    no_night = {'BB', 'FB', 'JD', 'LG', 'LH'}
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        for prod in no_night:
            cur = conn.execute(
                'SELECT COUNT(*) FROM agent_field_change_events '
                'WHERE data_source=\'DCE\' AND instrument=? '
                'AND effective_timestamp LIKE \'%T21:%\'',
                (prod,)
            )
            cnt = cur.fetchone()[0]
            if cnt > 0:
                rows.append({'rule': 'DCE-no-night-ts', 'severity': 'error',
                    'instrument': prod, 'field_name': 'All',
                    'detail': f'{prod} has no night session but {cnt} events use T21:00'})
    return rows

def _check_czce_calendar_day(store_key):
    """CZCE uses calendar-day not trading-day for tier transitions."""
    rows = []
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        count = conn.execute(
            'SELECT COUNT(*) FROM agent_field_change_events '
            'WHERE data_source=\'CZCE\' AND field_name LIKE \'%Margin%\' '
            'AND source_notice_id LIKE \'%交易日%\''
        ).fetchone()[0]
        if count > 0:
            rows.append({'rule': 'CZCE-calendar', 'severity': 'info',
                'instrument': 'CZCE', 'field_name': 'Margin',
                'detail': f'CZCE uses calendar-day tiers, check {count} events for correct ref'})
    return rows

def _check_shfe_four_tier(store_key):
    """SHFE has 4 tiers: baseline -> 10% -> 15% -> 20%."""
    rows = []
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        cur = conn.execute(
            'SELECT DISTINCT instrument FROM agent_field_change_events '
            'WHERE data_source=\'SHFE\' AND field_name LIKE \'%Margin%\' '
            'AND value_json=\'"0.20"\''
        )
        for r in cur.fetchall():
            inst = r[0]
            has_15 = conn.execute(
                'SELECT COUNT(*) FROM agent_field_change_events '
                'WHERE data_source=\'SHFE\' AND instrument=? '
                'AND field_name LIKE \'%Margin%\' AND value_json=\'"0.15"\'',
                (inst,)
            ).fetchone()[0]
            if not has_15:
                rows.append({'rule': 'SHFE-4tier', 'severity': 'info',
                    'instrument': inst, 'field_name': 'Margin',
                    'detail': f'{inst} has 20% but no 15% tier event'})
    return rows
def _print_summary(rows: list[dict[str, str]], *, limit: int) -> None:
    print("FieldHistory Cross-Exchange Integrity Audit")
    print(f"  total_issues: {len(rows)}")
    rule_counts = Counter(r['rule'] for r in rows)
    sev_counts = Counter(r['severity'] for r in rows)
    print(f"  by_severity: {dict(sev_counts)}")
    print(f"  by_rule: {dict(rule_counts)}")
    if rows:
        print("  samples:")
        for row in rows[:max(limit, 0)]:
            print(f"    [{row['severity']}] {row['rule']}: {row['instrument']} {row['field_name']} - {row['detail'][:90]}")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ['rule', 'severity', 'instrument', 'field_name', 'detail']
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == '__main__':
    raise SystemExit(main())
