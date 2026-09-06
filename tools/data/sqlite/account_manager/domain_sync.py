"""Low-level hooks that enqueue local account metadata without networking."""

from __future__ import annotations

import os
import json
from typing import Any, Mapping

import settings as Settings


def overlay_entities(principal: str, entity_type: str, values: list[dict], *, id_key: str) -> list[dict]:
    """Use the same mirror for editing and listing; retain legacy-only rows.

    A peer row need not exist in the local authoring table. Tombstones must
    also shadow that table so a stale local copy cannot resurrect a deletion.
    This read performs no network access or schema writes.
    """
    from tools.data.sqlite.db import connect_sqlite

    merged = {str(value.get(id_key) or f'legacy:{index}'): value
              for index, value in enumerate(values)}
    with connect_sqlite(Settings.CACHE_DB_PATH, readonly=True) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_domain_entities'").fetchone():
            return values
        rows = conn.execute(
            'SELECT entity_id,payload_json,deleted FROM account_domain_entities WHERE principal=? AND entity_type=?',
            (principal, entity_type),
        ).fetchall()
    for row in rows:
        key = row['entity_id']
        if row['deleted']:
            merged.pop(key, None)
        else:
            value = json.loads(row['payload_json'])
            if isinstance(value, dict):
                merged[key] = value
    return list(merged.values())


def enqueue_entity(
    principal: str,
    entity_type: str,
    entity_id: str,
    payload: Mapping[str, Any] | None,
    *,
    deleted: bool = False,
) -> None:
    """Best-effort local enqueue used by CLI/data helpers.

    The helper deliberately does not contact PostgreSQL. The Manager service
    flushes this same SQLite outbox when a user next opens an affected view.
    """
    try:
        from server.manager.storage.account_domain.local import LocalAccountDomainStore
        from server.manager.storage.account_domain.payloads import public_payload

        store = LocalAccountDomainStore(Settings.CACHE_DB_PATH)
        store.upsert_local(
            principal=str(principal or "").strip(),
            entity_type=entity_type,
            entity_id=str(entity_id or "").strip(),
            payload=public_payload(payload),
            manager_id=str(os.environ.get("FACTORTESTER_SERVER_ID") or "local"),
            deleted=deleted,
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        # The account store remains usable in small CLI/test installations
        # that do not load the Manager package.
        return


def replace_entities(
    principal: str,
    entity_type: str,
    values: list[Mapping[str, Any]],
    *,
    id_key: str,
) -> None:
    """Enqueue a local collection without deleting rows from another Manager.

    Collection APIs do not know whether a missing row was deleted locally or
    simply has not been pulled yet. Explicit delete APIs create tombstones;
    this helper only upserts the rows present in the local collection.
    """
    try:
        from server.manager.storage.account_domain.local import LocalAccountDomainStore
        from server.manager.storage.account_domain.payloads import public_payload

        store = LocalAccountDomainStore(Settings.CACHE_DB_PATH)
        current: dict[str, Mapping[str, Any]] = {
            str(value.get(id_key) or "").strip(): value
            for value in values
            if str(value.get(id_key) or "").strip()
        }
        for identifier, value in current.items():
            store.upsert_local(
                principal=principal,
                entity_type=entity_type,
                entity_id=identifier,
                payload=public_payload(value),
                manager_id=str(os.environ.get("FACTORTESTER_SERVER_ID") or "local"),
            )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return
