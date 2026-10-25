"""SQLite storage for user product groups."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import time
import uuid
from contextlib import nullcontext
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


_REVISION_FIELDS = (
    "id", "name", "selection_paths", "paths", "category_ids",
    "creator_kind", "creator_ref", "research_refs", "factor_refs",
    "factor_set_refs",
)


def product_group_revision_definition(group: dict[str, Any]) -> dict[str, Any]:
    value = {key: group[key] for key in _REVISION_FIELDS if key in group}
    paths = value.get("selection_paths")
    if not isinstance(paths, list):
        paths = value.get("paths")
    if isinstance(paths, list):
        value["selection_paths"] = list(paths)
    value.pop("paths", None)
    return value


def record_product_group_revision(
    username: str,
    group: dict[str, Any],
    *,
    connection: sqlite3.Connection | None = None,
    manager_id: str | None = None,
    mirror: Any = None,
    force: bool = False,
) -> str:
    """Queue the current semantic definition and return its immutable ref."""
    owner = str(username or "").strip()
    group_id = str(group.get("id") or "").strip()
    if not owner or not group_id:
        raise ValueError("product group revision requires an owner and stable id")
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    from server.services.versioning import (
        build_revision_manifest,
        canonical_sha256,
        enqueue_revision,
    )

    definition = product_group_revision_definition(group)
    digest, _ = canonical_sha256(definition)
    server_id = str(
        manager_id or os.environ.get("FACTORTESTER_SERVER_ID") or "local"
    )
    mirror = mirror or LocalAccountDomainStore(Settings.CACHE_DB_PATH)
    object_ref = f"product-group:{group_id}"
    with (nullcontext(connection) if connection is not None else connect_sqlite(Settings.CACHE_DB_PATH)) as conn:
        exists = conn.execute(
            """SELECT json_extract(payload_json, '$.revision_manifest.revision_ref') AS revision_ref
               FROM account_domain_entities
               WHERE principal=? AND entity_type='versioned_object_revision'
                 AND deleted=0
                 AND json_extract(payload_json, '$.revision_manifest.object_ref')=?
                 AND json_extract(payload_json, '$.revision_manifest.content_sha256')=?
               ORDER BY CAST(json_extract(payload_json, '$.revision_manifest.created_at') AS REAL) DESC,
                        entity_id DESC
               LIMIT 1""",
            (owner, object_ref, digest),
        ).fetchone()
        if exists and not force:
            return str(exists["revision_ref"] or "")
        created_at = time.time()
        manifest = build_revision_manifest(
            object_kind="product_group",
            object_ref=object_ref,
            revision_ref=f"product-group-revision:{uuid.uuid4().hex}",
            content_sha256=digest,
            owner_ref=owner,
            storage_server_id=server_id,
            created_at=created_at,
            created_by=owner,
            visibility="private",
            source_entity_type="product_group",
        )
        enqueue_revision(
            mirror,
            principal=owner,
            manager_id=server_id,
            manifest=manifest,
            object_definition=definition,
            connection=conn,
        )
        return str(manifest["revision_ref"])


def current_product_group_revision_ref(
    username: str,
    group: dict[str, Any],
    *,
    connection: sqlite3.Connection | None = None,
    mirror: Any = None,
    manager_id: str | None = None,
) -> str:
    """Return or create the immutable snapshot matching the current definition."""
    return record_product_group_revision(
        username, group, connection=connection, mirror=mirror,
        manager_id=manager_id, force=False,
    )


def ensure_product_group_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_product_groups (
            username TEXT NOT NULL,
            group_name TEXT NOT NULL,
            sort_index INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (username, group_name)
        )
        """
    )


def load_product_groups(username: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_product_group_schema(conn)
        rows = conn.execute(
            """
            SELECT payload_json
            FROM account_product_groups
            WHERE username = ?
            ORDER BY sort_index, group_name
            """,
            (username,),
        ).fetchall()
    groups: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            continue
        if isinstance(payload, dict):
            groups.append(payload)
    from tools.data.sqlite.account_manager.domain_sync import overlay_entities
    return overlay_entities(username, 'product_group', groups, id_key='id')


def save_product_groups(username: str, groups: list[dict[str, Any]]) -> None:
    now = time.time()
    normalized = [dict(group) for group in groups if isinstance(group, dict)]
    from server.manager.storage.account_domain.local import LocalAccountDomainStore

    mirror = LocalAccountDomainStore(Settings.CACHE_DB_PATH)
    manager_id = str(os.environ.get("FACTORTESTER_SERVER_ID") or "local")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_product_group_schema(conn)
        previous_rows = conn.execute(
            "SELECT payload_json FROM account_product_groups WHERE username=?",
            (username,),
        ).fetchall()
        previous: dict[str, dict[str, Any]] = {}
        for row in previous_rows:
            try:
                item = json.loads(row["payload_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(item, dict):
                identifier = str(item.get("id") or "").strip()
                if identifier:
                    previous[identifier] = item

        conn.execute("DELETE FROM account_product_groups WHERE username = ?", (username,))
        current_ids: set[str] = set()
        for sort_index, group in enumerate(normalized):
            name = str(group.get("name") or "").strip()
            if not name:
                continue
            group["name"] = name
            group_id = str(group.get("id") or "").strip()
            if not group_id:
                group_id = f"pg_{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}"
                group["id"] = group_id
            current_ids.add(group_id)
            conn.execute(
                """
                INSERT INTO account_product_groups (
                    username, group_name, sort_index, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    name,
                    sort_index,
                    json.dumps(group, ensure_ascii=False, separators=(",", ":")),
                    now,
                ),
            )
            definition = product_group_revision_definition(group)
            old = previous.get(group_id)
            old_definition = product_group_revision_definition(old) if old else None
            if old_definition != definition:
                revision_ref = record_product_group_revision(
                    username, group, connection=conn, manager_id=manager_id,
                    mirror=mirror, force=old is not None,
                )
                group["current_revision_ref"] = revision_ref
            elif old:
                group["current_revision_ref"] = current_product_group_revision_ref(
                    username, group, connection=conn, mirror=mirror,
                    manager_id=manager_id,
                )
            mirror.upsert_local(
                principal=username,
                entity_type="product_group",
                entity_id=group_id,
                payload=group,
                manager_id=manager_id,
                connection=conn,
            )

        for removed_id in set(previous) - current_ids:
            mirror.upsert_local(
                principal=username,
                entity_type="product_group",
                entity_id=removed_id,
                payload={},
                manager_id=manager_id,
                deleted=True,
                connection=conn,
            )
