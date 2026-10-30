"""Storage helpers for factor-library parameter configs."""

from tools.data.account_manage import (
    DEFAULT_SCOPE_KEY,
    delete_scope,
    ensure_scope_exists,
    list_all_factor_param_aliases_across_scopes,
    list_factor_param_config_aliases,
    list_factor_param_config_scopes,
    load_factor_param_config as _load_authored_factor_param_config,
    normalize_product_group,
    rename_scope,
    save_factor_param_config,
)


def delete_factor_param_config(username, ff_alias, scope_key=DEFAULT_SCOPE_KEY):
    """Delete received registrations even when this node has no authored row."""
    import os
    import settings as Settings
    from tools.data.sqlite.db import connect_sqlite
    from tools.data.sqlite.account_manager.factor_param_config import ensure_factor_param_config_schema
    from server.manager.storage.account_domain.local import LocalAccountDomainStore

    scope_key = normalize_product_group(scope_key)
    mirror = LocalAccountDomainStore(Settings.CACHE_DB_PATH)
    identifier = f'{scope_key}:{ff_alias}'
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute(
            "SELECT deleted FROM account_domain_entities WHERE principal=? AND entity_type='factor_param_config' AND entity_id=?",
            (username, identifier),
        ).fetchone()
        removed = conn.execute(
            'DELETE FROM account_factor_param_configs WHERE username=? AND scope_key=? AND ff_alias=?',
            (username, scope_key, ff_alias),
        ).rowcount
        exists = bool(removed or (current is not None and not current['deleted']))
        if exists:
            mirror.upsert_local(principal=username, entity_type='factor_param_config',
                                entity_id=identifier, payload={}, deleted=True,
                                manager_id=os.environ.get('FACTORTESTER_SERVER_ID') or 'local',
                                connection=conn)
        return exists


def load_factor_param_config(username, ff_alias, scope_key=DEFAULT_SCOPE_KEY):
    """Use the current local mirror for edits, including remote deletions.

    An authored row is a legacy fallback, not permission to overwrite a more
    recent registration received from another Manager.
    """
    import json
    import sqlite3
    import settings as Settings
    from tools.data.sqlite.db import connect_sqlite

    scope_key = normalize_product_group(scope_key)
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH, readonly=True) as conn:
            row = conn.execute(
                "SELECT payload_json, deleted FROM account_domain_entities "
                "WHERE principal=? AND entity_type='factor_param_config' AND entity_id=?",
                (username, f'{scope_key}:{ff_alias}'),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table' not in str(exc) and 'unable to open database' not in str(exc):
            raise
        row = None
    if row is not None:
        return None if row['deleted'] else json.loads(row['payload_json'])
    return _load_authored_factor_param_config(username, ff_alias, scope_key)

__all__ = [
    "DEFAULT_SCOPE_KEY",
    "delete_factor_param_config",
    "delete_scope",
    "ensure_scope_exists",
    "list_all_factor_param_aliases_across_scopes",
    "list_factor_param_config_aliases",
    "list_factor_param_config_scopes",
    "load_factor_param_config",
    "list_factor_param_config_refs",
    "normalize_product_group",
    "rename_scope",
    "save_factor_param_config",
]


def list_factor_param_config_refs(
    *,
    owner_username: str | None = None,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> list[tuple[str, str, str]]:
    """List config identities without loading their parameter payloads.

    These refs are a storage index only. Callers must authorize each owner's
    factor-library resource through Keycloak before loading config contents or
    resolving any referenced factor family.
    """
    import json
    import sqlite3
    import settings as Settings
    from tools.data.sqlite.db import connect_sqlite

    filters = []
    args: list[str] = []
    if owner_username is not None:
        filters.append("username=?")
        args.append(str(owner_username))
    if ff_alias is not None:
        filters.append("ff_alias=?")
        args.append(str(ff_alias))
    if scope_key is not None:
        filters.append("scope_key=?")
        args.append(normalize_product_group(scope_key))
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    refs: set[tuple[str, str, str]] = set()
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH, readonly=True) as conn:
            rows = conn.execute(
                "SELECT username, ff_alias, scope_key "
                f"FROM account_factor_param_configs{where}",
                tuple(args),
            ).fetchall()
        refs.update((str(row[0]), str(row[1]), str(row[2])) for row in rows)
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc) and "unable to open database" not in str(exc):
            raise

    # Replicated configs may have no authored row on this Manager. Their
    # compact account-domain mirror still contains the family/scope metadata.
    mirror_filters = ["entity_type='factor_param_config'"]
    mirror_args: list[str] = []
    if owner_username is not None:
        mirror_filters.append("principal=?")
        mirror_args.append(str(owner_username))
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH, readonly=True) as conn:
            rows = conn.execute(
                "SELECT principal, entity_id, payload_json, deleted "
                "FROM account_domain_entities WHERE "
                + " AND ".join(mirror_filters),
                tuple(mirror_args),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc) and "unable to open database" not in str(exc):
            raise
        rows = ()
    for row in rows:
        owner = str(row[0] or "").strip()
        identifier = str(row[1] or "").strip()
        if not owner or not identifier or bool(row[3]):
            continue
        try:
            payload = json.loads(row[2] or "{}")
        except (TypeError, ValueError):
            payload = {}
        family = str(
            payload.get("factor_family_alias")
            or identifier.rsplit(":", 1)[-1]
        ).strip() if isinstance(payload, dict) else identifier.rsplit(":", 1)[-1]
        scope = str(
            payload.get("scope_key") or payload.get("product_group")
            or identifier[:-len(family) - 1]
        ).strip() if isinstance(payload, dict) else identifier[:-len(family) - 1]
        if not family or not scope:
            continue
        if ff_alias is not None and family != str(ff_alias):
            continue
        if scope_key is not None and scope != normalize_product_group(scope_key):
            continue
        refs.add((owner, family, scope))
    return sorted(refs)
