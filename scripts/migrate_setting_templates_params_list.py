"""One-off migration for saved single-factor setting templates.

Moves the legacy top-level ``params_list`` snapshot field to
``parameters.params_list`` (the shape used by window.Panels /
panel_registry.js). After this runs, the frontend no longer recognizes
top-level params_list at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import settings as Settings
from server.modules.templates.params_list_migration import migrate_snapshot_params_list
from tools.data.sqlite.account_manager.user_template import TEMPLATE_TABLE, ensure_user_template_schema
from tools.data.sqlite.db import connect_sqlite


def migrate_templates(
    *,
    username: str | None = None,
    scope_key: str | None = None,
    template_id: str | None = None,
) -> dict[str, Any]:
    filters = ["kind='global'"]
    params: list[Any] = []
    if username:
        filters.append("username=?")
        params.append(username)
    if scope_key:
        filters.append("scope_key=?")
        params.append(scope_key)
    if template_id:
        filters.append("template_id=?")
        params.append(template_id)

    where = " AND ".join(filters)
    scanned = 0
    migrated = 0
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_template_schema(conn)
        rows = conn.execute(
            f'''
            SELECT username, kind, scope_key, ff_alias, template_id, payload_json
            FROM "{TEMPLATE_TABLE}"
            WHERE {where}
            ORDER BY username, scope_key, template_id
            ''',
            params,
        ).fetchall()
        for row in rows:
            scanned += 1
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("snapshot"), dict):
                continue
            snapshot, changed = migrate_snapshot_params_list(payload["snapshot"])
            if not changed:
                continue
            payload["snapshot"] = snapshot
            conn.execute(
                f'''
                UPDATE "{TEMPLATE_TABLE}"
                SET payload_json=?, updated_at=strftime('%s','now')
                WHERE username=? AND kind=? AND scope_key=? AND ff_alias=? AND template_id=?
                ''',
                (
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    row["username"],
                    row["kind"],
                    row["scope_key"],
                    row["ff_alias"],
                    row["template_id"],
                ),
            )
            migrated += 1
    return {
        "database": str(Settings.CACHE_DB_PATH),
        "scanned": scanned,
        "migrated": migrated,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--username")
    parser.add_argument("--scope-key")
    parser.add_argument("--template-id")
    args = parser.parse_args()
    result = migrate_templates(
        username=args.username,
        scope_key=args.scope_key,
        template_id=args.template_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
