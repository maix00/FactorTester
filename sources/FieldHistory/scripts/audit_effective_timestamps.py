"""Audit FieldHistory rows whose effective timestamp still needs source review."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import AGENT_EVENT_TABLE, ensure_agent_event_schema
from tools.data.hub import DataHub


DEFAULT_DB = "/Users/maxdeux/Documents/GTHT/data/sqlite/unifieddata.sqlite"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--data-source", default="", help="Optional agent data_source filter, e.g. CZCE")
    parser.add_argument("--output-csv", default="")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)

    _ensure_store_registered(DataHub.get_instance(), args.store_key)
    rows = _load_missing_agent_timestamps(args.store_key, data_source=args.data_source)
    print("FieldHistory effective timestamp audit")
    print(f"  missing_agent_event_timestamps: {len(rows)}")
    for row in rows[: max(args.limit, 0)]:
        print(
            "  "
            f"{row['data_source']} {row['instrument']} {row['field_name']} "
            f"{row['effective_trading_day']} {row['source_notice_id']} {row['event_id']}"
        )
    if args.output_csv:
        _write_csv(Path(args.output_csv).expanduser(), rows)
        print(f"wrote missing timestamp rows: {Path(args.output_csv).expanduser().resolve()}")
    return 0 if not rows else 2


def _load_missing_agent_timestamps(store_key: str, *, data_source: str = "") -> list[dict[str, Any]]:
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        clauses = ["COALESCE(effective_timestamp, '') = ''"]
        params: list[Any] = []
        if data_source:
            clauses.append("data_source = ?")
            params.append(data_source)
        rows = conn.execute(
            f"""
            SELECT event_id, data_source, field_group, instrument, instrument_label,
                   field_name, effective_trading_day, source_notice_id, source_url,
                   raw_note, parser_notes
            FROM {AGENT_EVENT_TABLE}
            WHERE {" AND ".join(clauses)}
            ORDER BY data_source, instrument, field_name, effective_trading_day, event_id
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "event_id",
        "data_source",
        "field_group",
        "instrument",
        "instrument_label",
        "field_name",
        "effective_trading_day",
        "source_notice_id",
        "source_url",
        "raw_note",
        "parser_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
