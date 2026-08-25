"""Canonical editable and reusable research configurations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from copy import deepcopy
from typing import Any

import orjson

import settings as Settings
from tools.data.sqlite.db import connect_sqlite
from tools.data.types.object_identity import unique_frozen_identities

SCHEMA_VERSION = 2
ROLES = {"workspace", "template"}


class ConfigurationRevisionConflict(RuntimeError):
    def __init__(self, current_revision: int) -> None:
        super().__init__(f"configuration revision changed to {current_revision}")
        self.current_revision = current_revision


def _dumps(value: Any) -> str:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS).decode()


def _loads(value: str | None) -> Any:
    return orjson.loads(value) if value else None


def empty_payload(
    *,
    factors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "shared": {
            "factors": deepcopy(factors or []),
        },
        "analyses": {},
        "ui": {},
    }


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("configuration payload must be an object")
    if int(payload.get("schema_version") or 0) != SCHEMA_VERSION:
        raise ValueError(f"unsupported configuration schema: {payload.get('schema_version')!r}")
    shared = payload.get("shared")
    analyses = payload.get("analyses")
    ui = payload.get("ui")
    if not isinstance(shared, dict) or not isinstance(analyses, dict) or not isinstance(ui, dict):
        raise ValueError("configuration requires object shared, analyses, and ui sections")
    shared = deepcopy(shared)
    # Family catalogs belong to the factor-create overlay, not to a reusable
    # test configuration.  Loading an existing workspace opportunistically
    # retires the old duplicate projection on its next save.
    shared.pop("factor_families", None)
    payload = {**payload, "shared": shared}
    factors = unique_frozen_identities(shared.get("factors"))
    shared["factors"] = factors
    factor_aliases: set[str] = set()
    for factor in factors:
        alias = factor["alias"]
        if alias in factor_aliases:
            raise ValueError(f"factor alias must be unique: {alias}")
        factor_aliases.add(alias)
    external_artifacts = shared.get("external_factor_artifacts", [])
    if not isinstance(external_artifacts, list) or not all(
        isinstance(item, dict) for item in external_artifacts
    ):
        raise ValueError("shared.external_factor_artifacts must be an array of objects")
    for artifact in external_artifacts:
        if not str(artifact.get("manifest_path") or "").strip():
            raise ValueError("each external factor artifact requires manifest_path")
    return deepcopy(payload)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_configurations (
            configuration_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            role TEXT NOT NULL,
            workspace_id TEXT,
            name TEXT NOT NULL DEFAULT '',
            schema_version INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            source_configuration_id TEXT,
            legacy_template_id TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            deleted_at REAL,
            CHECK (role IN ('workspace', 'template'))
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_research_config_workspace_active "
        "ON research_configurations(workspace_id) WHERE role='workspace' AND deleted_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_config_owner_role "
        "ON research_configurations(owner, role, updated_at)"
    )


def ensure_schema() -> None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)


def delete_owner_configurations(owner: str) -> int:
    """Delete reusable and workspace configuration data for a removed account."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        cursor = conn.execute("DELETE FROM research_configurations WHERE owner=?", (owner,))
    return int(cursor.rowcount)


def rename_factor_family_alias(old_alias: str, new_alias: str) -> int:
    """Keep canonical configurations aligned after a custom family rename."""
    old_alias = str(old_alias or "").strip()
    new_alias = str(new_alias or "").strip()
    if not old_alias or not new_alias or old_alias == new_alias:
        return 0

    def replace(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return new_alias if value == old_alias else value

    touched = 0
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT configuration_id, payload_json FROM research_configurations WHERE deleted_at IS NULL"
        ).fetchall()
        for row in rows:
            payload = _loads(row["payload_json"]) or {}
            updated = replace(payload)
            if updated == payload:
                continue
            validate_payload(updated)
            conn.execute(
                "UPDATE research_configurations SET payload_json=?, revision=revision+1, updated_at=? "
                "WHERE configuration_id=?",
                (_dumps(updated), now, row["configuration_id"]),
            )
            touched += 1
    return touched


def _row_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = _loads(row["payload_json"]) or {}
    if (
        int(row["schema_version"] or 0) != SCHEMA_VERSION
        or int(payload.get("schema_version") or 0) != SCHEMA_VERSION
    ):
        raise RuntimeError(
            "editable configuration requires the explicit factor formula "
            "identity migration"
        )
    raw = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return {
        "configuration_id": str(row["configuration_id"]),
        "owner": str(row["owner"]),
        "role": str(row["role"]),
        "workspace_id": str(row["workspace_id"] or ""),
        "name": str(row["name"] or ""),
        "schema_version": int(row["schema_version"]),
        "revision": int(row["revision"]),
        "payload": payload,
        "fingerprint": hashlib.sha256(raw).hexdigest(),
        "source_configuration_id": str(row["source_configuration_id"] or ""),
        "legacy_template_id": str(row["legacy_template_id"] or ""),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def create_workspace_configuration(
    *, owner: str, workspace_id: str,
    factors: list[dict[str, Any]] | None = None,
    payload: dict | None = None,
) -> dict[str, Any]:
    value = validate_payload(payload or empty_payload(
        factors=factors,
    ))
    configuration_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO research_configurations (
                configuration_id, owner, role, workspace_id,
                schema_version, revision, payload_json, created_at, updated_at
            ) VALUES (?, ?, 'workspace', ?, ?, 1, ?, ?, ?)
            """,
            (
                configuration_id, owner, workspace_id,
                SCHEMA_VERSION, _dumps(value), now, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM research_configurations WHERE configuration_id=?", (configuration_id,)
        ).fetchone()
    return _row_payload(row) or {}


def load_workspace_configuration(*, workspace_id: str, owner: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT * FROM research_configurations
            WHERE workspace_id=? AND owner=? AND role='workspace' AND deleted_at IS NULL
            """,
            (workspace_id, owner),
        ).fetchone()
    return _row_payload(row)


def update_workspace_configuration(
    *, workspace_id: str, owner: str, expected_revision: int, payload: dict,
    source_configuration_id: str | None = None,
) -> dict[str, Any]:
    value = validate_payload(payload)
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM research_configurations
            WHERE workspace_id=? AND owner=? AND role='workspace' AND deleted_at IS NULL
            """,
            (workspace_id, owner),
        ).fetchone()
        if row is None:
            raise KeyError("workspace configuration not found")
        if int(row["revision"]) != int(expected_revision):
            raise ConfigurationRevisionConflict(int(row["revision"]))
        conn.execute(
            """
            UPDATE research_configurations
            SET schema_version=?, revision=revision+1,
                payload_json=?, source_configuration_id=?, updated_at=?
            WHERE configuration_id=?
            """,
            (
                SCHEMA_VERSION,
                _dumps(value),
                source_configuration_id,
                now,
                row["configuration_id"],
            ),
        )
        updated = conn.execute(
            "SELECT * FROM research_configurations WHERE configuration_id=?",
            (row["configuration_id"],),
        ).fetchone()
    return _row_payload(updated) or {}


def save_template(
    *, workspace_id: str, owner: str, name: str,
) -> dict[str, Any]:
    source = load_workspace_configuration(workspace_id=workspace_id, owner=owner)
    if source is None:
        raise KeyError("workspace configuration not found")
    configuration_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO research_configurations (
                configuration_id, owner, role, name,
                schema_version, revision, payload_json, source_configuration_id,
                created_at, updated_at
            ) VALUES (?, ?, 'template', ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                configuration_id, owner, name,
                SCHEMA_VERSION, _dumps(source["payload"]), source["configuration_id"], now, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM research_configurations WHERE configuration_id=?", (configuration_id,)
        ).fetchone()
    return _row_payload(row) or {}


def list_templates(*, owner: str) -> list[dict[str, Any]]:
    clauses = ["owner=?", "role='template'", "deleted_at IS NULL"]
    args: list[Any] = [owner]
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            f"SELECT * FROM research_configurations WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC",
            args,
        ).fetchall()
    return [_row_payload(row) or {} for row in rows]


def load_template_into_workspace(
    *, configuration_id: str, workspace_id: str, owner: str, expected_revision: int,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT * FROM research_configurations
            WHERE configuration_id=? AND owner=? AND role='template' AND deleted_at IS NULL
            """,
            (configuration_id, owner),
        ).fetchone()
    template = _row_payload(row)
    if template is None:
        raise KeyError("template not found")
    return update_workspace_configuration(
        workspace_id=workspace_id,
        owner=owner,
        expected_revision=expected_revision,
        payload=template["payload"],
        source_configuration_id=configuration_id,
    )


def overwrite_template_from_workspace(
    *, configuration_id: str, workspace_id: str, owner: str,
) -> dict[str, Any]:
    source = load_workspace_configuration(workspace_id=workspace_id, owner=owner)
    if source is None:
        raise KeyError("workspace configuration not found")
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        cursor = conn.execute(
            """
            UPDATE research_configurations
            SET schema_version=?, revision=revision+1, payload_json=?,
                source_configuration_id=?, updated_at=?
            WHERE configuration_id=? AND owner=? AND role='template' AND deleted_at IS NULL
            """,
            (
                SCHEMA_VERSION, _dumps(source["payload"]), source["configuration_id"],
                now, configuration_id, owner,
            ),
        )
        if cursor.rowcount != 1:
            raise KeyError("template not found")
        row = conn.execute(
            "SELECT * FROM research_configurations WHERE configuration_id=?",
            (configuration_id,),
        ).fetchone()
    return _row_payload(row) or {}


def delete_template(*, configuration_id: str, owner: str) -> bool:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        cursor = conn.execute(
            """
            UPDATE research_configurations SET deleted_at=?, updated_at=?
            WHERE configuration_id=? AND owner=? AND role='template' AND deleted_at IS NULL
            """,
            (time.time(), time.time(), configuration_id, owner),
        )
        return cursor.rowcount == 1


def legacy_snapshot_to_payload(
    snapshot: dict, *, factor_family_alias: str, owner: str,
) -> dict[str, Any]:
    """One-time migration adapter. Runtime APIs never call this function."""
    source = deepcopy(snapshot)
    backtest = deepcopy(source)
    from tools.testers.settings import backtest_setting_registry

    setting_keys = set(backtest_setting_registry.get("group_test").settings)
    local_settings = deepcopy(source.get("local_settings") or {})
    for key in setting_keys:
        if key in source and key not in local_settings:
            local_settings[key] = deepcopy(source[key])
        backtest.pop(key, None)
    backtest["local_settings"] = local_settings
    group_settings = source.get("group_settings")
    if isinstance(group_settings, dict):
        groups = group_settings.get("groups")
        if isinstance(groups, list):
            submissions = {
                str(item.get("id") or ""): item
                for item in (source.get("submissions") or []) if isinstance(item, dict)
            }
            normalized = []
            selections = {}
            for item in groups:
                if not isinstance(item, dict):
                    continue
                group = deepcopy(item)
                if "splitCount" not in group and "groupCount" in group:
                    group["splitCount"] = int(group["groupCount"])
                    group["groupIndex"] = int(group.get("groupIndex") or 0) + 1
                submission = submissions.get(str(group.get("testerId") or ""))
                if not isinstance(group.get("product_path_selection"), dict) and submission:
                    selection = deepcopy(submission)
                    sid = str(selection.get("product_path_selection_id") or selection.get("id") or group.get("testerId") or "")
                    selection["product_path_selection_id"] = sid
                    group["product_path_selection"] = selection
                    selections[sid] = selection
                normalized.append(group)
            backtest["groups"] = normalized
            if selections:
                backtest["product_selections"] = selections
        if isinstance(group_settings.get("lsConfigs"), list):
            backtest["ls_configs"] = deepcopy(group_settings["lsConfigs"])
    factor_aliases: set[str] = set()
    for group in backtest.get("groups") or []:
        if isinstance(group, dict):
            candidates = group.get("factorAliases")
            if candidates is None:
                candidates = group.get("factor_aliases")
            if candidates is None:
                candidates = [group.get("factorAlias") or group.get("factor_alias")]
            if not isinstance(candidates, list):
                candidates = [candidates]
            factor_aliases.update(
                str(alias).strip() for alias in candidates if str(alias or "").strip()
            )
    for candidate in source.get("factor_candidates") or []:
        if isinstance(candidate, dict):
            alias = str(candidate.get("alias") or "").strip()
            if alias:
                factor_aliases.add(alias)
    for key in ("factor_alias", "factorAlias"):
        alias = str(source.get(key) or "").strip()
        if alias:
            factor_aliases.add(alias)
    from server.services.factor_revisions import _load_revision_definition
    from tools.factors.formula_identity import freeze_factor_identity

    frozen_by_alias: dict[str, dict[str, Any]] = {}
    aliases_by_family: dict[str, list[str]] = {}
    for alias in sorted(factor_aliases):
        family = alias.split("|", 1)[0] or factor_family_alias
        aliases_by_family.setdefault(family, []).append(alias)
    for family, aliases in aliases_by_family.items():
        definition = _load_revision_definition(
            family_ref=family,
            factor_aliases=aliases,
            owner=owner,
        )
        for resolved in definition["resolved_factors"]:
            alias = str(resolved["factor_alias"])
            frozen_by_alias[alias] = freeze_factor_identity(
                owner_ref=str(definition["factor_owner_ref"]),
                family_alias=str(definition["factor_family_alias"]),
                factor_alias=alias,
                family_formula_fingerprint=str(
                    definition["family_formula_fingerprint"]
                ),
                self_formula_fingerprint=str(
                    resolved["self_formula_fingerprint"]
                ),
                params=resolved["params"],
            )
    refs_by_alias = {
        alias: record["ref"] for alias, record in frozen_by_alias.items()
    }
    for group in backtest.get("groups") or []:
        if not isinstance(group, dict):
            continue
        aliases = group.pop("factorAliases", None)
        if aliases is None:
            aliases = group.pop("factor_aliases", None)
        primary = group.pop("factorAlias", None) or group.pop("factor_alias", None)
        values = aliases if isinstance(aliases, list) else [primary]
        group["factor_candidate_refs"] = [
            refs_by_alias[str(alias).strip()]
            for alias in values if str(alias or "").strip() in refs_by_alias
        ]
    backtest.pop("factor", None)
    backtest.pop("factor_alias", None)
    backtest.pop("factorAlias", None)
    local_settings.pop("factor", None)
    local_settings.pop("factor_candidates", None)
    backtest["local_settings"] = local_settings
    return {
        "schema_version": SCHEMA_VERSION,
        "shared": {
            "factors": [frozen_by_alias[alias] for alias in sorted(frozen_by_alias)],
        },
        "analyses": {"backtest": backtest},
        "ui": source,
    }


def _repair_registered_backtest_settings(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Repair canonical records produced by the pre-scope migration."""
    from tools.testers.settings import backtest_setting_registry

    value = deepcopy(payload)
    backtest = (value.get("analyses") or {}).get("backtest")
    if not isinstance(backtest, dict):
        return value, False
    local_settings = deepcopy(backtest.get("local_settings") or {})
    changed = False
    for key in set(backtest_setting_registry.get("group_test").settings):
        if key not in backtest:
            continue
        if key not in local_settings:
            local_settings[key] = deepcopy(backtest[key])
        backtest.pop(key, None)
        changed = True
    if changed:
        backtest["local_settings"] = local_settings
        validate_payload(value)
    return value, changed


def migrate_legacy_templates(*, apply: bool = False) -> dict[str, Any]:
    """Convert old account template rows into canonical template configurations."""
    report: dict[str, Any] = {
        "scanned": 0,
        "scanned_by_kind": {},
        "migrated": 0,
        "skipped": 0,
        "retired_legacy_components": {},
        "canonical_templates_repaired": 0,
        "errors": [],
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        if apply:
            _ensure_schema(conn)
        templates_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_templates'"
        ).fetchone() is not None
        collections_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_template_collections'"
        ).fetchone() is not None
        canonical_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_configurations'"
        ).fetchone() is not None
        if canonical_exists:
            migrated_rows = conn.execute(
                """
                SELECT configuration_id, payload_json FROM research_configurations
                WHERE role='template' AND legacy_template_id IS NOT NULL AND deleted_at IS NULL
                """
            ).fetchall()
            for migrated in migrated_rows:
                repaired, changed = _repair_registered_backtest_settings(
                    _loads(migrated["payload_json"]) or {}
                )
                if not changed:
                    continue
                report["canonical_templates_repaired"] += 1
                if apply:
                    conn.execute(
                        """
                        UPDATE research_configurations
                        SET payload_json=?, revision=revision+1, updated_at=?
                        WHERE configuration_id=?
                        """,
                        (_dumps(repaired), time.time(), migrated["configuration_id"]),
                    )
        if not templates_exists and not collections_exists:
            report["applied"] = bool(apply)
            return report
        rows: list[dict[str, Any]] = []
        if templates_exists:
            rows.extend(dict(row) for row in conn.execute(
                "SELECT * FROM account_templates ORDER BY username, scope_key, sort_order"
            ).fetchall())
        if collections_exists:
            collection_rows = conn.execute(
                "SELECT * FROM account_template_collections ORDER BY username, scope_key"
            ).fetchall()
            for collection in collection_rows:
                value = json.loads(collection["payload_json"])
                items = value.get("templates", []) if isinstance(value, dict) else value
                for sort_order, item in enumerate(items if isinstance(items, list) else []):
                    if not isinstance(item, dict):
                        continue
                    rows.append({
                        "username": collection["username"],
                        "kind": collection["kind"],
                        "scope_key": collection["scope_key"],
                        "ff_alias": collection["ff_alias"],
                        "template_id": str(item.get("id") or f"__index__:{sort_order}"),
                        "sort_order": sort_order,
                        "name": str(item.get("name") or ""),
                        "payload_json": json.dumps(item, ensure_ascii=False),
                    })
        for row in rows:
            kind = str(row["kind"])
            report["scanned_by_kind"][kind] = report["scanned_by_kind"].get(kind, 0) + 1
        report["retired_legacy_components"] = {
            kind: count
            for kind, count in report["scanned_by_kind"].items()
            if kind != "global"
        }
        report["scanned"] = sum(report["scanned_by_kind"].values())
        for row in (item for item in rows if item["kind"] == "global"):
            try:
                legacy = json.loads(row["payload_json"])
                from server.modules.products.product_group_store import (
                    load_product_groups,
                )
                from server.modules.templates.backend_settings_migration import (
                    migrate_snapshot_backend_settings,
                )
                from server.modules.templates.snapshot_product_groups import (
                    refresh_template_product_group_paths,
                )

                snapshot = deepcopy(legacy.get("snapshot") or {})
                snapshot, _ = migrate_snapshot_backend_settings(
                    snapshot, load_product_groups(str(row["username"])),
                )
                wrapped = refresh_template_product_group_paths(
                    {"snapshot": snapshot}, load_product_groups(str(row["username"])),
                )
                legacy_id = f"{row['scope_key']}:{row['template_id']}"
                already = None
                if canonical_exists:
                    already = conn.execute(
                        "SELECT 1 FROM research_configurations WHERE owner=? AND legacy_template_id=?",
                        (row["username"], legacy_id),
                    ).fetchone()
                if already is not None:
                    report["skipped"] += 1
                    continue
                payload = legacy_snapshot_to_payload(
                    wrapped.get("snapshot") or {},
                    factor_family_alias=str(row["scope_key"] or legacy.get("ff_alias") or ""),
                    owner=str(row["username"]),
                )
                validate_payload(payload)
                if apply:
                    now = time.time()
                    conn.execute(
                        """
                        INSERT INTO research_configurations (
                            configuration_id, owner, role, name,
                            schema_version, revision, payload_json, legacy_template_id,
                            created_at, updated_at
                        ) VALUES (?, ?, 'template', ?, ?, 1, ?, ?, ?, ?)
                        """,
                        (
                            uuid.uuid4().hex, row["username"], str(row["name"] or ""),
                            SCHEMA_VERSION, _dumps(payload), legacy_id, now, now,
                        ),
                    )
                report["migrated"] += 1
            except Exception as exc:
                report["errors"].append({
                    "username": str(row["username"]),
                            "template_id": str(row["template_id"]),
                            "scope_key": str(row["scope_key"]),
                    "error": str(exc),
                })
        if apply and not report["errors"]:
            conn.execute("DROP TABLE IF EXISTS account_templates")
            conn.execute("DROP TABLE IF EXISTS account_template_collections")
    report["applied"] = bool(apply)
    return report


def migrate_legacy_workspaces_and_runs(*, apply: bool = False) -> dict[str, Any]:
    """Collapse historical draft revisions and adapt pre-configuration runs."""
    report: dict[str, Any] = {
        "legacy_workspace_schema": False,
        "workspaces_scanned": 0,
        "workspace_configurations_created": 0,
        "legacy_run_schema": False,
        "runs_scanned": 0,
        "errors": [],
        "applied": bool(apply),
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        if apply:
            _ensure_schema(conn)
        canonical_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_configurations'"
        ).fetchone() is not None
        workspace_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_workspaces'"
        ).fetchone()
        if workspace_exists is not None:
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(research_workspaces)").fetchall()
            }
            legacy_workspace = "current_revision" in columns or "factor_family_alias" in columns
            report["legacy_workspace_schema"] = legacy_workspace
            rows = conn.execute("SELECT * FROM research_workspaces").fetchall()
            report["workspaces_scanned"] = len(rows)
            if legacy_workspace:
                revisions_exist = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_workspace_revisions'"
                ).fetchone() is not None
                for row in rows:
                    workspace_id = str(row["workspace_id"])
                    existing = None
                    if canonical_exists:
                        existing = conn.execute(
                            "SELECT 1 FROM research_configurations WHERE workspace_id=? AND role='workspace'",
                            (workspace_id,),
                        ).fetchone()
                    if existing is not None:
                        continue
                    try:
                        draft = {}
                        if revisions_exist:
                            revision_row = conn.execute(
                                """
                                SELECT draft_json FROM research_workspace_revisions
                                WHERE workspace_id=? AND revision=?
                                """,
                                (workspace_id, int(row["current_revision"])),
                            ).fetchone()
                            if revision_row is not None:
                                draft = _loads(revision_row["draft_json"]) or {}
                        elif "draft_json" in columns:
                            draft = _loads(row["draft_json"]) or {}
                        try:
                            payload = validate_payload(draft)
                        except ValueError:
                            family = str(row["factor_family_alias"] or "") if "factor_family_alias" in columns else ""
                            payload = legacy_snapshot_to_payload(
                                draft,
                                factor_family_alias=family,
                                owner=str(row["owner"]),
                            )
                        if apply:
                            now = time.time()
                            conn.execute(
                                """
                                INSERT INTO research_configurations (
                                    configuration_id, owner, role, workspace_id,
                                    schema_version, revision, payload_json, created_at, updated_at
                                ) VALUES (?, ?, 'workspace', ?, ?, 1, ?, ?, ?)
                                """,
                                (
                                    uuid.uuid4().hex, row["owner"], workspace_id,
                                    SCHEMA_VERSION, _dumps(payload), now, now,
                                ),
                            )
                        report["workspace_configurations_created"] += 1
                    except Exception as exc:
                        report["errors"].append({"workspace_id": workspace_id, "error": str(exc)})
                if apply and not report["errors"]:
                    conn.execute("ALTER TABLE research_workspaces RENAME TO research_workspaces_legacy")
                    conn.execute(
                        """
                        CREATE TABLE research_workspaces (
                            workspace_id TEXT PRIMARY KEY,
                            owner TEXT NOT NULL,
                            kind TEXT NOT NULL,
                            title TEXT NOT NULL,
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL,
                            deleted_at REAL
                        )
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO research_workspaces (
                            workspace_id, owner, kind, title, created_at, updated_at, deleted_at
                        )
                        SELECT workspace_id, owner, 'factor_research', title,
                               created_at, updated_at, deleted_at
                        FROM research_workspaces_legacy
                        """
                    )
                    conn.execute("DROP TABLE research_workspaces_legacy")
                    if revisions_exist:
                        conn.execute("DROP TABLE research_workspace_revisions")

        run_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_runs'"
        ).fetchone()
        if run_exists is not None:
            run_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(research_runs)").fetchall()
            }
            legacy_runs = "configuration_id" not in run_columns
            report["legacy_run_schema"] = legacy_runs
            run_rows = conn.execute("SELECT * FROM research_runs").fetchall()
            report["runs_scanned"] = len(run_rows)
            if legacy_runs and apply and not report["errors"]:
                conn.execute("ALTER TABLE research_runs RENAME TO research_runs_legacy")
                conn.execute(
                    """
                    CREATE TABLE research_runs (
                        run_id TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        configuration_id TEXT NOT NULL,
                        configuration_revision INTEGER NOT NULL,
                        kind TEXT NOT NULL,
                        run_spec_version INTEGER NOT NULL,
                        run_spec_hash TEXT NOT NULL,
                        run_spec_json TEXT NOT NULL,
                        trial_plan_id TEXT NOT NULL DEFAULT '',
                        trial_plan_hash TEXT NOT NULL DEFAULT '',
                        trial_plan_version INTEGER NOT NULL DEFAULT 0,
                        trial_role TEXT NOT NULL DEFAULT '',
                        trial_stage TEXT NOT NULL DEFAULT '',
                        comparison_id TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL
                    )
                    """
                )
                for row in run_rows:
                    config = conn.execute(
                        """
                        SELECT configuration_id, revision FROM research_configurations
                        WHERE workspace_id=? AND role='workspace' AND deleted_at IS NULL
                        """,
                        (row["workspace_id"],),
                    ).fetchone()
                    if config is None:
                        report["errors"].append({"run_id": str(row["run_id"]), "error": "workspace configuration missing"})
                        continue
                    conn.execute(
                        """
                        INSERT INTO research_runs (
                            run_id, owner, workspace_id, configuration_id,
                            configuration_revision, kind,
                            run_spec_version, run_spec_hash, run_spec_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["run_id"], row["owner"], row["workspace_id"],
                            config["configuration_id"], int(config["revision"]),
                            "factor_research", row["run_spec_version"],
                            row["run_spec_hash"], row["run_spec_json"], row["created_at"],
                        ),
                    )
                if report["errors"]:
                    raise RuntimeError("run migration failed: " + str(report["errors"]))
                conn.execute("DROP TABLE research_runs_legacy")
    return report
