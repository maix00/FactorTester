"""Remove LocalCNFutures audit evidence from FieldHistory truth tables.

LocalCNFutures static catalog rows are useful for audit and cross-checking, but
they are not exchange source-of-truth field-change events.  This script removes
previously appended ``Agent:LocalCNFutures`` rows from both the append-only agent
event table and materialized ``historical_field_values``.
"""

from __future__ import annotations

import argparse
import json

from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import AGENT_EVENT_TABLE, ensure_agent_event_schema
from tools.data.hub import DataHub


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = prune_local_cnfutures_audit_events(store_key=args.store_key, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def prune_local_cnfutures_audit_events(*, store_key: str = "openctp", dry_run: bool = False) -> dict[str, int]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        agent_count = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {AGENT_EVENT_TABLE}
            WHERE data_source = 'LocalCNFutures'
               OR source_notice_id LIKE 'LocalCNFutures%'
            """
        ).fetchone()[0]
        history_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM historical_field_values
            WHERE provider = 'Agent:LocalCNFutures'
               OR source_key LIKE 'agent/LocalCNFutures/%'
               OR source_notice_id LIKE 'LocalCNFutures%'
            """
        ).fetchone()[0]
        if dry_run:
            return {
                "agent_field_change_events": int(agent_count),
                "historical_field_values": int(history_count),
                "deleted": 0,
            }
        conn.execute(
            f"""
            DELETE FROM {AGENT_EVENT_TABLE}
            WHERE data_source = 'LocalCNFutures'
               OR source_notice_id LIKE 'LocalCNFutures%'
            """
        )
        conn.execute(
            """
            DELETE FROM historical_field_values
            WHERE provider = 'Agent:LocalCNFutures'
               OR source_key LIKE 'agent/LocalCNFutures/%'
               OR source_notice_id LIKE 'LocalCNFutures%'
            """
        )
    return {
        "agent_field_change_events": int(agent_count),
        "historical_field_values": int(history_count),
        "deleted": int(agent_count) + int(history_count),
    }


if __name__ == "__main__":
    raise SystemExit(main())
