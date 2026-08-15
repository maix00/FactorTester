"""PostgreSQL adapter for the generic account-domain entity table."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class AccountDomainControlMixin:
    """Methods mixed into the existing PostgreSQL control repository."""

    def push_account_domain_entity(
        self,
        *,
        principal: str,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
        deleted: bool = False,
        base_revision: int | None = None,
        origin_manager_id: str = "",
        operation_id: str = "",
    ) -> dict[str, Any]:
        """Idempotently publish one local account-domain metadata row."""
        owner = str(principal or "").strip()
        kind = str(entity_type or "").strip()
        identifier = str(entity_id or "").strip()
        if not owner or not kind or not identifier:
            raise ValueError("account-domain entity identity is required")
        encoded = json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True)
        visibility = str(payload.get("visibility") or "private").strip().lower()
        if visibility not in {"private", "authorized", "public"}:
            visibility = "private"
        authorized = sorted({
            str(item).strip()
            for item in (payload.get("authorized_users") or [])
            if str(item).strip()
        })
        storage_server_id = str(
            payload.get("storage_server_id") or origin_manager_id or ""
        ).strip()
        self.ensure_schema()
        with self._connection() as connection:
            lock_key = f"factortester:account-domain:{owner}:{kind}:{identifier}"
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
            current = connection.execute(
                """
                SELECT payload, deleted, revision
                FROM control_account_domain_entities
                WHERE principal=%s AND entity_type=%s AND entity_id=%s
                """,
                (owner, kind, identifier),
            ).fetchone()
            if current is not None:
                current_payload = _row_value(current, "payload", 0, {})
                if isinstance(current_payload, str):
                    try:
                        current_payload = json.loads(current_payload)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        current_payload = {}
                current_payload = current_payload if isinstance(current_payload, dict) else {}
                current_deleted = bool(_row_value(current, "deleted", 1, False))
                current_revision = int(_row_value(current, "revision", 2, 0) or 0)
                if current_payload == dict(payload or {}) and current_deleted == bool(deleted):
                    return {
                        "status": "synced",
                        "revision": current_revision,
                        "idempotent": True,
                        "operation_id": str(operation_id or ""),
                    }
                if base_revision is None or int(base_revision) != current_revision:
                    return {
                        "status": "conflict",
                        "revision": current_revision,
                        "payload": current_payload,
                        "deleted": current_deleted,
                        "operation_id": str(operation_id or ""),
                    }
            elif base_revision not in (None, 0):
                return {
                    "status": "conflict",
                    "revision": 0,
                    "payload": {},
                    "deleted": False,
                    "operation_id": str(operation_id or ""),
                }
            revision_row = connection.execute(
                "SELECT nextval('control_account_domain_revision_seq') AS revision"
            ).fetchone()
            revision = int(_row_value(revision_row, "revision", 0, 0) or 0)
            connection.execute(
                """
                INSERT INTO control_account_domain_entities(
                    principal, entity_type, entity_id, payload, deleted,
                    visibility, authorized_users, storage_server_id,
                    origin_manager_id, revision, updated_at
                ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s,
                          %s, CURRENT_TIMESTAMP)
                ON CONFLICT(principal, entity_type, entity_id) DO UPDATE SET
                    payload=EXCLUDED.payload,
                    deleted=EXCLUDED.deleted,
                    visibility=EXCLUDED.visibility,
                    authorized_users=EXCLUDED.authorized_users,
                    storage_server_id=EXCLUDED.storage_server_id,
                    origin_manager_id=EXCLUDED.origin_manager_id,
                    revision=EXCLUDED.revision,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    owner, kind, identifier, encoded, bool(deleted), visibility,
                    json.dumps(authorized, ensure_ascii=False), storage_server_id,
                    str(origin_manager_id or ""), revision,
                ),
            )
        return {
            "status": "synced",
            "revision": revision,
            "operation_id": str(operation_id or ""),
        }

    def pull_account_domain_entities(
        self,
        *,
        after_revision: int = 0,
        principal: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """Read rows visible to one principal after a local cursor."""
        self.ensure_schema()
        owner = str(principal or "").strip()
        bounded = max(1, min(int(limit), 1000))
        with self._connection() as connection:
            head = connection.execute(
                """
                SELECT COALESCE(MAX(revision), %s) AS revision
                FROM control_account_domain_entities
                WHERE revision > %s
                """,
                (max(0, int(after_revision)), max(0, int(after_revision))),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT principal, entity_type, entity_id, payload, deleted,
                       visibility, authorized_users, storage_server_id,
                       origin_manager_id, revision, updated_at
                FROM control_account_domain_entities
                WHERE revision > %s
                  AND (
                    principal=%s
                    OR visibility='public'
                    OR (visibility='authorized' AND authorized_users ? %s)
                  )
                ORDER BY revision
                LIMIT %s
                """,
                (max(0, int(after_revision)), owner, owner, bounded),
            ).fetchall()
        entities = [self._account_domain_value(row) for row in rows]
        next_revision = max(
            [max(0, int(after_revision))]
            + [int(_row_value(head, "revision", 0, after_revision) or after_revision)]
            + [int(item.get("revision") or 0) for item in entities]
        )
        return {"entities": entities, "next_revision": next_revision}

    @staticmethod
    def _account_domain_value(row: object) -> dict[str, Any]:
        value = dict(row) if isinstance(row, Mapping) else {
            "principal": _row_value(row, "principal", 0, ""),
            "entity_type": _row_value(row, "entity_type", 1, ""),
            "entity_id": _row_value(row, "entity_id", 2, ""),
            "payload": _row_value(row, "payload", 3, {}),
            "deleted": _row_value(row, "deleted", 4, False),
            "visibility": _row_value(row, "visibility", 5, "private"),
            "authorized_users": _row_value(row, "authorized_users", 6, []),
            "storage_server_id": _row_value(row, "storage_server_id", 7, ""),
            "origin_manager_id": _row_value(row, "origin_manager_id", 8, ""),
            "revision": _row_value(row, "revision", 9, 0),
            "updated_at": _row_value(row, "updated_at", 10, None),
        }
        for key in ("payload", "authorized_users"):
            current = value.get(key)
            if isinstance(current, str):
                try:
                    current = json.loads(current)
                except (TypeError, ValueError, json.JSONDecodeError):
                    current = {} if key == "payload" else []
            value[key] = current if isinstance(current, (dict, list)) else (
                {} if key == "payload" else []
            )
        if hasattr(value.get("updated_at"), "isoformat"):
            value["updated_at"] = value["updated_at"].isoformat()
        return value


def _row_value(row: object, key: str, index: int = 0, default: object = None) -> object:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[index]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return default
