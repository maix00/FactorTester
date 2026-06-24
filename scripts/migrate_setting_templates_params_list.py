"""One-off migration for saved single-factor setting templates.

Converts the legacy top-level ``params_list`` snapshot field into
``factor_candidates`` (+ ``factor``), the shape used by the factors tab /
window.Panels (panel_registry.js). After this runs, the frontend no longer
recognizes top-level params_list at all.

Each legacy params dict becomes a candidate with its computed factor alias and
a cross-reference against the owner's factor library (in_library +
library_product_group). Must run inside the project app context, e.g.:

    conda run -n GTHT python scripts/migrate_setting_templates_params_list.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import create_app  # noqa: E402  (boots import order for tools.data)
import settings as Settings  # noqa: E402
from server.modules.templates.params_list_migration import migrate_snapshot_to_factor_candidates  # noqa: E402
from server.modules.shared.param_config import normalize_param_row  # noqa: E402
from server.modules.custom_factors.param_config_service import build_param_factor_overview  # noqa: E402
from server.services.factor_registry import get_factor_family_instance  # noqa: E402
from tools.data.sqlite.account_manager.user_template import TEMPLATE_TABLE, ensure_user_template_schema  # noqa: E402
from tools.data.sqlite.db import connect_sqlite  # noqa: E402

DEFAULT_SCOPE_SENTINELS = {None, "", "default", "默认"}


def _build_resolver(username: str, ff_alias: str) -> Callable[[dict], dict] | None:
    try:
        factor_family = get_factor_family_instance(ff_alias, username=username)
    except Exception:
        factor_family = None
    if factor_family is None:
        return None

    # alias -> product group (None when unbound), from the owner's factor library.
    library_index: dict[str, Any] = {}
    try:
        overview = build_param_factor_overview(username, False, factor_family_alias=ff_alias)
        for item in overview.get("factors", []):
            alias = item.get("factor_alias")
            scope = item.get("scope_key") or item.get("product_group")
            if alias and alias not in library_index:
                library_index[alias] = None if scope in DEFAULT_SCOPE_SENTINELS else scope
    except Exception:
        library_index = {}

    def resolve(params: dict) -> dict:
        try:
            row = normalize_param_row(factor_family, params)
            alias = factor_family.get_alias(**row)
        except Exception:
            return {"alias": "", "in_library": False, "library_product_group": None}
        return {
            "alias": alias,
            "in_library": alias in library_index,
            "library_product_group": library_index.get(alias),
        }

    return resolve


def migrate_templates(
    *,
    username: str | None = None,
    scope_key: str | None = None,
    template_id: str | None = None,
    dry_run: bool = False,
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

    # Fallback for templates whose factor family no longer resolves (deleted
    # custom factors): still convert so params are not stranded in the dead
    # params_list field; alias is left empty and recomputed by /replace_params
    # on restore.
    def _null_resolve(_params: dict) -> dict:
        return {"alias": "", "in_library": False, "library_product_group": None}

    where = " AND ".join(filters)
    scanned = 0
    migrated = 0
    fallback_used = 0
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
            if not isinstance(payload["snapshot"].get("params_list"), list):
                continue
            ff_alias = payload.get("ff_alias") or row["scope_key"]
            resolve = _build_resolver(str(row["username"]), str(ff_alias))
            if resolve is None:
                resolve = _null_resolve
                fallback_used += 1
            snapshot, changed = migrate_snapshot_to_factor_candidates(payload["snapshot"], resolve)
            if not changed:
                continue
            payload["snapshot"] = snapshot
            migrated += 1
            if dry_run:
                continue
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
    return {
        "database": str(Settings.CACHE_DB_PATH),
        "scanned": scanned,
        "migrated": migrated,
        "fallback_used": fallback_used,
        "dry_run": dry_run,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--username")
    parser.add_argument("--scope-key")
    parser.add_argument("--template-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    create_app()  # boot app context (factor registry, data layer)
    result = migrate_templates(
        username=args.username,
        scope_key=args.scope_key,
        template_id=args.template_id,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
