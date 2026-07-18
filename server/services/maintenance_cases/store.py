"""One durable owner for the cross-kind Maintenance Case queue."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any

import orjson

from .schema import connect_maintenance_cases, ensure_schema


_MAX_REFS = 16
_MAX_REF_LENGTH = 512
_MAX_REFS_JSON_BYTES = 8192


class MaintenanceCaseStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        ensure_schema(self.db_path)

    def open_case(
        self,
        *,
        owner_user_id: str,
        kind: str,
        descriptor_hash: str,
        affected_refs: list[str],
        change_refs: list[str],
        conversation_ref: str = "",
    ) -> dict[str, Any]:
        now = time.time()
        with connect_maintenance_cases(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            return open_case_in_connection(
                conn,
                owner_user_id=owner_user_id,
                kind=kind,
                descriptor_hash=descriptor_hash,
                affected_refs=affected_refs,
                change_refs=change_refs,
                conversation_ref=conversation_ref,
                now=now,
            )

    def load_case(
        self,
        *,
        owner_user_id: str,
        case_id: str,
    ) -> dict[str, Any]:
        with connect_maintenance_cases(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM research_maintenance_cases
                WHERE owner_user_id=? AND case_id=?
                """,
                (owner_user_id, case_id),
            ).fetchone()
        if row is None:
            raise KeyError("Maintenance Case not found")
        return _case_value(row)

    def list_cases(
        self,
        *,
        owner_user_id: str,
        status: str = "",
        kind: str = "",
    ) -> list[dict[str, Any]]:
        predicates = ["owner_user_id=?"]
        parameters: list[str] = [owner_user_id]
        if status:
            predicates.append("status=?")
            parameters.append(status)
        if kind:
            predicates.append("kind=?")
            parameters.append(kind)
        where = "WHERE " + " AND ".join(predicates) if predicates else ""
        with connect_maintenance_cases(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM research_maintenance_cases
                {where}
                ORDER BY updated_at, case_id
                """,
                parameters,
            ).fetchall()
        return [_case_value(row) for row in rows]

    def claim_case(
        self,
        *,
        owner_user_id: str,
        case_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        _require_text("agent_id", agent_id, max_length=128)
        now = time.time()
        with connect_maintenance_cases(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _load_case_row(conn, owner_user_id, case_id)
            status = str(row["status"])
            claimed_agent = str(row["claimed_agent_id"])
            if status in {"claimed", "blocked"} and claimed_agent == agent_id:
                return _case_value(row)
            if status != "open":
                if claimed_agent and claimed_agent != agent_id:
                    raise ValueError(
                        "Maintenance Case is claimed by another Agent"
                    )
                raise ValueError("Maintenance Case cannot be claimed")
            row = conn.execute(
                """
                UPDATE research_maintenance_cases
                SET status='claimed', claimed_agent_id=?, claimed_at=?,
                    updated_at=?
                WHERE owner_user_id=? AND case_id=? AND status='open'
                RETURNING *
                """,
                (agent_id, now, now, owner_user_id, case_id),
            ).fetchone()
        return _case_value(row)

    def block_case(
        self,
        *,
        owner_user_id: str,
        case_id: str,
        agent_id: str,
        result_ref: str,
        change_refs: list[str],
    ) -> dict[str, Any]:
        return self._change_status(
            case_id=case_id,
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            target_status="blocked",
            result_ref=result_ref,
            change_refs=change_refs,
        )

    def resolve_case(
        self,
        *,
        owner_user_id: str,
        case_id: str,
        agent_id: str,
        result_ref: str,
        change_refs: list[str],
    ) -> dict[str, Any]:
        return self._change_status(
            case_id=case_id,
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            target_status="resolved",
            result_ref=result_ref,
            change_refs=change_refs,
        )

    def reject_case(
        self,
        *,
        owner_user_id: str,
        case_id: str,
        agent_id: str,
        result_ref: str,
        change_refs: list[str],
    ) -> dict[str, Any]:
        return self._change_status(
            case_id=case_id,
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            target_status="rejected",
            result_ref=result_ref,
            change_refs=change_refs,
        )

    def _change_status(
        self,
        *,
        owner_user_id: str,
        case_id: str,
        agent_id: str,
        target_status: str,
        result_ref: str,
        change_refs: list[str],
    ) -> dict[str, Any]:
        _require_text("agent_id", agent_id, max_length=128)
        _require_text(
            "result_ref",
            result_ref,
            max_length=_MAX_REF_LENGTH,
        )
        new_refs = _bounded_refs("change_refs", change_refs)
        now = time.time()
        with connect_maintenance_cases(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _load_case_row(conn, owner_user_id, case_id)
            if str(row["claimed_agent_id"]) != agent_id:
                raise ValueError(
                    "Maintenance Case transition requires its claimed Agent"
                )
            merged_refs = _bounded_refs(
                "change_refs",
                orjson.loads(row["change_refs_json"]) + new_refs,
            )
            if (
                str(row["status"]) == target_status
                and str(row["latest_result_ref"]) == result_ref
                and merged_refs == orjson.loads(row["change_refs_json"])
            ):
                return _case_value(row)
            if str(row["status"]) not in {"claimed", "blocked"}:
                raise ValueError(
                    "Maintenance Case is not open for this transition"
                )
            closed_at = (
                now if target_status in {"resolved", "rejected"} else None
            )
            row = conn.execute(
                """
                UPDATE research_maintenance_cases
                SET status=?, change_refs_json=?, latest_result_ref=?,
                    updated_at=?, closed_at=?
                WHERE owner_user_id=? AND case_id=?
                RETURNING *
                """,
                (
                    target_status,
                    _dump_refs(merged_refs),
                    result_ref,
                    now,
                    closed_at,
                    owner_user_id,
                    case_id,
                ),
            ).fetchone()
        return _case_value(row)


def _case_value(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "case_id": str(row["case_id"]),
        "owner_user_id": str(row["owner_user_id"]),
        "kind": str(row["kind"]),
        "descriptor_hash": str(row["descriptor_hash"]),
        "status": str(row["status"]),
        "affected_refs": orjson.loads(row["affected_refs_json"]),
        "change_refs": orjson.loads(row["change_refs_json"]),
        "conversation_ref": str(row["conversation_ref"]),
        "claimed_agent_id": str(row["claimed_agent_id"]),
        "latest_result_ref": str(row["latest_result_ref"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "claimed_at": (
            float(row["claimed_at"])
            if row["claimed_at"] is not None else None
        ),
        "closed_at": (
            float(row["closed_at"])
            if row["closed_at"] is not None else None
        ),
    }


def open_case_in_connection(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    kind: str,
    descriptor_hash: str,
    affected_refs: list[str],
    change_refs: list[str],
    conversation_ref: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Open or deduplicate a case inside a caller-owned transaction."""
    _require_text("owner_user_id", owner_user_id, max_length=128)
    _require_text("kind", kind, max_length=64)
    _require_sha256(descriptor_hash)
    affected = _bounded_refs("affected_refs", affected_refs)
    changes = _bounded_refs("change_refs", change_refs)
    _require_optional_ref("conversation_ref", conversation_ref)
    timestamp = time.time() if now is None else now
    existing = conn.execute(
        """
        SELECT * FROM research_maintenance_cases
        WHERE owner_user_id=? AND descriptor_hash=?
        """,
        (owner_user_id, descriptor_hash),
    ).fetchone()
    if existing is not None:
        return _case_value(existing)
    row = conn.execute(
        """
        INSERT INTO research_maintenance_cases (
            case_id, owner_user_id, kind, descriptor_hash, status,
            affected_refs_json, change_refs_json, conversation_ref,
            claimed_agent_id, latest_result_ref, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?, '', '', ?, ?)
        RETURNING *
        """,
        (
            uuid.uuid4().hex,
            owner_user_id,
            kind,
            descriptor_hash,
            _dump_refs(affected),
            _dump_refs(changes),
            conversation_ref,
            timestamp,
            timestamp,
        ),
    ).fetchone()
    return _case_value(row)


def _load_case_row(
    conn: sqlite3.Connection,
    owner_user_id: str,
    case_id: str,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT * FROM research_maintenance_cases
        WHERE owner_user_id=? AND case_id=?
        """,
        (owner_user_id, case_id),
    ).fetchone()
    if row is None:
        raise KeyError("Maintenance Case not found")
    return row


def _bounded_refs(field: str, refs: list[str]) -> list[str]:
    if not isinstance(refs, list):
        raise ValueError(f"{field} must be an array of references")
    result = []
    for ref in refs:
        _require_text(field, ref, max_length=_MAX_REF_LENGTH)
        if ref not in result:
            result.append(ref)
    if len(result) > _MAX_REFS:
        raise ValueError(f"{field} exceeds {_MAX_REFS} references")
    if len(_dump_refs(result).encode()) > _MAX_REFS_JSON_BYTES:
        raise ValueError(f"{field} exceeds the serialized size limit")
    return result


def _dump_refs(refs: list[str]) -> str:
    return orjson.dumps(refs).decode()


def _require_text(field: str, value: str, *, max_length: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    if len(value) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")


def _require_optional_ref(field: str, value: str) -> None:
    if not isinstance(value, str) or len(value) > _MAX_REF_LENGTH:
        raise ValueError(f"{field} must be a bounded reference")


def _require_sha256(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("descriptor_hash must be sha256")
