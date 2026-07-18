"""Provider-neutral Agent execution and token-budget lifecycle store."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from .schema import connect_agent_flow, ensure_schema


_CHARGING_POLICY_VERSION = "normalized-total@1"
_OPEN = "open"
_RESERVED = "reserved"
_SETTLED = "settled"
_STORE_CACHE: dict[str, AgentFlowStore] = {}


class AgentFlowStore:
    """Own Agent budget periods and invocations behind one small Interface."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        ensure_schema(self.db_path)

    def reserve_invocation(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        actor_role: str,
        authority_scope: str,
        purpose: str,
        runtime_id: str,
        model_id: str,
        max_input_tokens: int,
        max_output_tokens: int,
        agent_principal_hash: str,
        lineage_hash: str,
        sponsor_agent_id: str = "",
        task_ref: str = "",
        input_hash: str = "",
        context_cost: dict[str, int] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        self._require_text("owner_user_id", owner_user_id)
        self._require_text("agent_id", agent_id)
        self._require_text("actor_role", actor_role)
        self._require_text("authority_scope", authority_scope)
        self._require_text("purpose", purpose)
        if (
            actor_role in {"backend_verifier", "implementation_agent"}
            and authority_scope != "server_backend_code"
        ):
            raise ValueError(
                f"{actor_role} requires server_backend_code authority"
            )
        self._require_sha256("agent_principal_hash", agent_principal_hash)
        self._require_sha256("lineage_hash", lineage_hash)
        self._require_non_negative("max_input_tokens", max_input_tokens)
        self._require_non_negative("max_output_tokens", max_output_tokens)
        reserved_tokens = max_input_tokens + max_output_tokens
        if reserved_tokens <= 0:
            raise ValueError("Agent invocation reservation must be positive")
        context_value = context_cost or {}
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in context_value.values()
        ):
            raise ValueError("context_cost values must be non-negative integers")

        now = time.time()
        request_hash = hashlib.sha256(orjson.dumps(
            {
                "owner_user_id": owner_user_id,
                "agent_id": agent_id,
                "sponsor_agent_id": sponsor_agent_id,
                "actor_role": actor_role,
                "authority_scope": authority_scope,
                "task_ref": task_ref,
                "purpose": purpose,
                "runtime_id": runtime_id,
                "model_id": model_id,
                "max_input_tokens": max_input_tokens,
                "max_output_tokens": max_output_tokens,
                "agent_principal_hash": agent_principal_hash,
                "lineage_hash": lineage_hash,
                "input_hash": input_hash,
                "context_cost": context_value,
            },
            option=orjson.OPT_SORT_KEYS,
        )).hexdigest()
        invocation_id = uuid.uuid4().hex
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                existing = conn.execute(
                    """
                    SELECT i.*, p.token_limit AS current_token_limit
                    FROM agent_invocations i
                    JOIN agent_budget_periods p ON p.period_id=i.period_id
                    WHERE i.owner_user_id=? AND i.agent_id=?
                      AND i.idempotency_key=?
                    """,
                    (owner_user_id, agent_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_hash"]) != request_hash:
                        raise ValueError(
                            "idempotency key conflicts with another request"
                        )
                    return self._reserved_invocation_value(existing)
            period = self._load_or_create_open_period(
                conn,
                owner_user_id=owner_user_id,
                agent_id=agent_id,
                now=now,
            )
            if bool(period["reset_pending"]):
                raise ValueError("budget reset is pending")
            token_limit = (
                int(period["token_limit"])
                if period["token_limit"] is not None
                else None
            )
            if token_limit is not None:
                available = (
                    token_limit
                    - int(period["used_tokens"])
                    - int(period["reserved_tokens"])
                )
                if reserved_tokens > available:
                    raise ValueError(
                        "agent_budget_exhausted: "
                        f"requested={reserved_tokens}, "
                        f"available={max(available, 0)}"
                    )
            conn.execute(
                """
                INSERT INTO agent_invocations (
                    invocation_id, period_id, owner_user_id, agent_id,
                    idempotency_key, request_hash, sponsor_agent_id,
                    actor_role, authority_scope, task_ref, purpose, runtime_id,
                    model_id, agent_principal_hash, lineage_hash, input_hash,
                    max_input_tokens,
                    max_output_tokens, reserved_tokens, context_cost_json,
                    status, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, 'reserved', ?
                )
                """,
                (
                    invocation_id,
                    period["period_id"],
                    owner_user_id,
                    agent_id,
                    idempotency_key,
                    request_hash,
                    sponsor_agent_id,
                    actor_role,
                    authority_scope,
                    task_ref,
                    purpose,
                    runtime_id,
                    model_id,
                    agent_principal_hash,
                    lineage_hash,
                    input_hash,
                    max_input_tokens,
                    max_output_tokens,
                    reserved_tokens,
                    orjson.dumps(
                        context_value,
                        option=orjson.OPT_SORT_KEYS,
                    ).decode(),
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE agent_budget_periods
                SET reserved_tokens=reserved_tokens+?
                WHERE period_id=?
                """,
                (reserved_tokens, period["period_id"]),
            )
        return {
            "invocation_id": invocation_id,
            "period_id": str(period["period_id"]),
            "owner_user_id": owner_user_id,
            "agent_id": agent_id,
            "status": _RESERVED,
            "token_limit": token_limit,
            "reserved_tokens": reserved_tokens,
            "created_at": now,
        }

    def configure_token_limit(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        token_limit: int,
    ) -> dict[str, Any]:
        self._require_text("owner_user_id", owner_user_id)
        self._require_text("agent_id", agent_id)
        if (
            not isinstance(token_limit, int)
            or isinstance(token_limit, bool)
            or token_limit <= 0
        ):
            raise ValueError("token_limit must be a positive integer")
        now = time.time()
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT period_id, token_limit, used_tokens, reserved_tokens
                FROM agent_budget_periods
                WHERE owner_user_id=? AND agent_id=? AND status='open'
                """,
                (owner_user_id, agent_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO agent_budget_periods (
                        period_id, owner_user_id, agent_id, token_limit,
                        used_tokens, reserved_tokens,
                        charging_policy_version, revision, status, created_at
                    ) VALUES (?, ?, ?, ?, 0, 0, ?, 1, 'open', ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        owner_user_id,
                        agent_id,
                        token_limit,
                        _CHARGING_POLICY_VERSION,
                        now,
                    ),
                )
            elif token_limit < (
                int(row["used_tokens"]) + int(row["reserved_tokens"])
            ):
                raise ValueError(
                    "token_limit cannot be below used plus reserved tokens"
                )
            elif (
                int(row["token_limit"])
                if row["token_limit"] is not None
                else None
            ) != token_limit:
                conn.execute(
                    """
                    UPDATE agent_budget_periods
                    SET token_limit=?, revision=revision+1
                    WHERE period_id=?
                    """,
                    (token_limit, row["period_id"]),
                )
        period = self.load_current_budget_period(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
        )
        assert period is not None
        return period

    def reset_budget_period(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        token_limit: int | None = None,
    ) -> dict[str, Any]:
        self._require_text("owner_user_id", owner_user_id)
        self._require_text("agent_id", agent_id)
        if token_limit is not None and (
            not isinstance(token_limit, int)
            or isinstance(token_limit, bool)
            or token_limit <= 0
        ):
            raise ValueError("token_limit must be a positive integer or null")
        now = time.time()
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """
                SELECT * FROM agent_budget_periods
                WHERE owner_user_id=? AND agent_id=? AND status='open'
                """,
                (owner_user_id, agent_id),
            ).fetchone()
            if current is not None and int(current["reserved_tokens"]) > 0:
                conn.execute(
                    """
                    UPDATE agent_budget_periods
                    SET reset_pending=1, next_token_limit=?,
                        reset_requested_at=?, revision=revision+1
                    WHERE period_id=?
                    """,
                    (token_limit, now, current["period_id"]),
                )
                pending = True
            else:
                pending = False
            if current is not None and not pending:
                conn.execute(
                    """
                    UPDATE agent_budget_periods
                    SET status='closed', closed_at=?, revision=revision+1
                    WHERE period_id=?
                    """,
                    (now, current["period_id"]),
                )
            if not pending:
                conn.execute(
                """
                INSERT INTO agent_budget_periods (
                    period_id, owner_user_id, agent_id, token_limit,
                    used_tokens, reserved_tokens, charging_policy_version,
                    revision, status, created_at
                ) VALUES (?, ?, ?, ?, 0, 0, ?, 1, 'open', ?)
                """,
                    (
                        uuid.uuid4().hex,
                        owner_user_id,
                        agent_id,
                        token_limit,
                        _CHARGING_POLICY_VERSION,
                        now,
                    ),
                )
        period = self.load_current_budget_period(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
        )
        assert period is not None
        return period

    def list_budget_periods(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> list[dict[str, Any]]:
        with connect_agent_flow(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_budget_periods
                WHERE owner_user_id=? AND agent_id=?
                ORDER BY created_at DESC, period_id DESC
                """,
                (owner_user_id, agent_id),
            ).fetchall()
        return [self._budget_period_value(row) for row in rows]

    def load_invocation(
        self,
        *,
        owner_user_id: str,
        invocation_id: str,
    ) -> dict[str, Any]:
        with connect_agent_flow(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_invocations
                WHERE owner_user_id=? AND invocation_id=?
                """,
                (owner_user_id, invocation_id),
            ).fetchone()
        if row is None:
            raise KeyError("Agent invocation not found")
        return {
            key: row[key]
            for key in row.keys()
            if key != "context_cost_json"
        } | {
            "context_cost": orjson.loads(row["context_cost_json"]),
        }

    def load_invocations(
        self,
        *,
        owner_user_id: str,
        invocation_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        unique_ids = list(dict.fromkeys(invocation_ids))
        if not unique_ids:
            return {}
        placeholders = ",".join("?" for _ in unique_ids)
        with connect_agent_flow(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM agent_invocations
                WHERE owner_user_id=? AND invocation_id IN ({placeholders})
                """,
                (owner_user_id, *unique_ids),
            ).fetchall()
        return {
            str(row["invocation_id"]): {
                key: row[key]
                for key in row.keys()
                if key != "context_cost_json"
            } | {
                "context_cost": orjson.loads(row["context_cost_json"]),
            }
            for row in rows
        }

    def count_invocations(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> int:
        with connect_agent_flow(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM agent_invocations
                WHERE owner_user_id=? AND agent_id=?
                """,
                (owner_user_id, agent_id),
            ).fetchone()
        return int(row["count"])

    def count_subagent_invocations(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> int:
        with connect_agent_flow(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM agent_invocations
                WHERE owner_user_id=? AND agent_id=?
                  AND sponsor_agent_id<>''
                """,
                (owner_user_id, agent_id),
            ).fetchone()
        return int(row["count"])

    def settled_tokens_for_invocations(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        invocation_ids: list[str],
    ) -> int:
        unique_ids = list(dict.fromkeys(invocation_ids))
        if not unique_ids:
            return 0
        placeholders = ",".join("?" for _ in unique_ids)
        with connect_agent_flow(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT invocation_id, charged_tokens
                FROM agent_invocations
                WHERE owner_user_id=? AND agent_id=? AND status='settled'
                  AND invocation_id IN ({placeholders})
                """,
                (owner_user_id, agent_id, *unique_ids),
            ).fetchall()
        if len(rows) != len(unique_ids):
            raise ValueError(
                "all Agent invocations must be settled in the expected scope"
            )
        return sum(int(row["charged_tokens"]) for row in rows)

    def find_invocation_by_reference(
        self,
        *,
        invocation_or_reservation_id: str,
        owner_user_id: str = "",
    ) -> dict[str, Any]:
        predicates = (
            "AND owner_user_id=?"
            if owner_user_id
            else ""
        )
        parameters: tuple[Any, ...] = (
            invocation_or_reservation_id,
            invocation_or_reservation_id,
            *((owner_user_id,) if owner_user_id else ()),
        )
        with connect_agent_flow(self.db_path) as conn:
            row = conn.execute(
                f"""
                SELECT * FROM agent_invocations
                WHERE (
                    invocation_id=? OR legacy_reservation_id=?
                ) {predicates}
                """,
                parameters,
            ).fetchone()
        if row is None:
            raise KeyError("Agent invocation not found")
        return self.load_invocation(
            owner_user_id=str(row["owner_user_id"]),
            invocation_id=str(row["invocation_id"]),
        )

    def claim_reserved_invocation(
        self,
        *,
        owner_user_id: str,
        invocation_or_reservation_id: str,
        actor_role: str,
        authority_scope: str,
        runtime_id: str,
        model_id: str,
        agent_principal_hash: str,
        lineage_hash: str,
    ) -> dict[str, Any]:
        self._require_sha256("agent_principal_hash", agent_principal_hash)
        self._require_sha256("lineage_hash", lineage_hash)
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM agent_invocations
                WHERE owner_user_id=?
                  AND (invocation_id=? OR legacy_reservation_id=?)
                  AND status='reserved'
                """,
                (
                    owner_user_id,
                    invocation_or_reservation_id,
                    invocation_or_reservation_id,
                ),
            ).fetchone()
            if row is None:
                raise ValueError(
                    "active Agent invocation reservation is required"
                )
            conn.execute(
                """
                UPDATE agent_invocations
                SET actor_role=?, authority_scope=?, runtime_id=?, model_id=?,
                    agent_principal_hash=?, lineage_hash=?
                WHERE invocation_id=?
                """,
                (
                    actor_role,
                    authority_scope,
                    runtime_id,
                    model_id,
                    agent_principal_hash,
                    lineage_hash,
                    row["invocation_id"],
                ),
            )
        return self.load_invocation(
            owner_user_id=owner_user_id,
            invocation_id=str(row["invocation_id"]),
        )

    def release_invocation(
        self,
        *,
        owner_user_id: str,
        invocation_or_reservation_id: str,
    ) -> dict[str, Any]:
        now = time.time()
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM agent_invocations
                WHERE owner_user_id=?
                  AND (invocation_id=? OR legacy_reservation_id=?)
                  AND status='reserved'
                """,
                (
                    owner_user_id,
                    invocation_or_reservation_id,
                    invocation_or_reservation_id,
                ),
            ).fetchone()
            if row is None:
                raise ValueError("reserved Agent invocation not found")
            conn.execute(
                """
                UPDATE agent_invocations
                SET status='released', settled_at=? WHERE invocation_id=?
                """,
                (now, row["invocation_id"]),
            )
            conn.execute(
                """
                UPDATE agent_budget_periods
                SET reserved_tokens=reserved_tokens-?
                WHERE period_id=?
                """,
                (int(row["reserved_tokens"]), row["period_id"]),
            )
        return {
            "invocation_id": str(row["invocation_id"]),
            "reservation_id": invocation_or_reservation_id,
            "status": "released",
            "released_tokens": int(row["reserved_tokens"]),
        }

    def settle_invocation(
        self,
        *,
        owner_user_id: str,
        invocation_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int = 0,
        provider_request_id: str = "",
        provider_attestation: str = "",
    ) -> dict[str, Any]:
        for field, value in (
            ("cache_read_tokens", cache_read_tokens),
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        ):
            if value is not None:
                self._require_non_negative(field, value)
        if (input_tokens is None) != (output_tokens is None):
            raise ValueError(
                "input_tokens and output_tokens must both be supplied or omitted"
            )

        now = time.time()
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM agent_invocations
                WHERE invocation_id=? AND owner_user_id=?
                """,
                (invocation_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise ValueError("Agent invocation not found")

            request_hash = self._optional_hash(provider_request_id)
            if str(row["status"]) == _SETTLED:
                requested_quality = (
                    "reserved_fallback"
                    if input_tokens is None
                    else "provider_actual"
                )
                if (
                    row["input_tokens"] != input_tokens
                    or row["output_tokens"] != output_tokens
                    or int(row["cache_read_tokens"] or 0)
                    != cache_read_tokens
                    or str(row["provider_request_hash"]) != request_hash
                    or str(row["measurement_quality"]) != requested_quality
                ):
                    raise ValueError(
                        "settlement conflicts with the existing result"
                    )
                return self._settled_invocation_value(row)
            if str(row["status"]) != _RESERVED:
                raise ValueError("Agent invocation is not reservable")

            reserved_tokens = int(row["reserved_tokens"])
            if input_tokens is None:
                charged_tokens = reserved_tokens
                input_value = None
                output_value = None
                measurement_quality = "reserved_fallback"
            else:
                if input_tokens > int(row["max_input_tokens"]) or (
                    output_tokens > int(row["max_output_tokens"])
                ):
                    raise ValueError(
                        "provider usage exceeded the safe reservation"
                    )
                charged_tokens = input_tokens + output_tokens
                input_value = input_tokens
                output_value = output_tokens
                measurement_quality = "provider_actual"
            if cache_read_tokens > (input_value or 0):
                raise ValueError(
                    "cache_read_tokens cannot exceed input_tokens"
                )

            conn.execute(
                """
                UPDATE agent_invocations
                SET input_tokens=?, output_tokens=?, cache_read_tokens=?,
                    charged_tokens=?, measurement_quality=?,
                    provider_request_hash=?,
                    provider_attestation_hash=?, status='settled',
                    settled_at=?
                WHERE invocation_id=?
                """,
                (
                    input_value,
                    output_value,
                    cache_read_tokens,
                    charged_tokens,
                    measurement_quality,
                    request_hash,
                    self._optional_hash(provider_attestation),
                    now,
                    invocation_id,
                ),
            )
            conn.execute(
                """
                UPDATE agent_budget_periods
                SET used_tokens=used_tokens+?,
                    reserved_tokens=reserved_tokens-?
                WHERE period_id=?
                """,
                (charged_tokens, reserved_tokens, row["period_id"]),
            )
            period = conn.execute(
                """
                SELECT * FROM agent_budget_periods WHERE period_id=?
                """,
                (row["period_id"],),
            ).fetchone()
            if (
                period is not None
                and int(period["reserved_tokens"]) == 0
                and bool(period["reset_pending"])
            ):
                conn.execute(
                    """
                    UPDATE agent_budget_periods
                    SET status='closed', closed_at=?,
                        reset_pending=0, next_token_limit=NULL,
                        reset_requested_at=NULL, revision=revision+1
                    WHERE period_id=?
                    """,
                    (now, row["period_id"]),
                )
                conn.execute(
                    """
                    INSERT INTO agent_budget_periods (
                        period_id, owner_user_id, agent_id, token_limit,
                        used_tokens, reserved_tokens,
                        charging_policy_version, revision, status, created_at
                    ) VALUES (?, ?, ?, ?, 0, 0, ?, 1, 'open', ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        period["owner_user_id"],
                        period["agent_id"],
                        period["next_token_limit"],
                        _CHARGING_POLICY_VERSION,
                        now,
                    ),
                )
        return {
            "invocation_id": invocation_id,
            "period_id": str(row["period_id"]),
            "status": _SETTLED,
            "charged_tokens": charged_tokens,
            "measurement_quality": measurement_quality,
            "released_tokens": reserved_tokens - charged_tokens,
            "settled_at": now,
        }

    def load_current_budget_period(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> dict[str, Any] | None:
        with connect_agent_flow(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_budget_periods
                WHERE owner_user_id=? AND agent_id=? AND status='open'
                """,
                (owner_user_id, agent_id),
            ).fetchone()
        if row is None:
            return None
        return self._budget_period_value(row)

    @staticmethod
    def _budget_period_value(row: sqlite3.Row) -> dict[str, Any]:
        token_limit = (
            int(row["token_limit"])
            if row["token_limit"] is not None
            else None
        )
        used_tokens = int(row["used_tokens"])
        reserved_tokens = int(row["reserved_tokens"])
        value = {
            "period_id": str(row["period_id"]),
            "owner_user_id": str(row["owner_user_id"]),
            "agent_id": str(row["agent_id"]),
            "token_limit": token_limit,
            "used_tokens": used_tokens,
            "reserved_tokens": reserved_tokens,
            "available_tokens": (
                max(token_limit - used_tokens - reserved_tokens, 0)
                if token_limit is not None
                else None
            ),
            "charging_policy_version": str(
                row["charging_policy_version"]
            ),
            "revision": int(row["revision"]),
            "status": str(row["status"]),
        }
        if bool(row["reset_pending"]):
            value["reset_pending"] = True
            value["next_token_limit"] = (
                int(row["next_token_limit"])
                if row["next_token_limit"] is not None
                else None
            )
        return value

    @staticmethod
    def _load_or_create_open_period(
        conn: sqlite3.Connection,
        *,
        owner_user_id: str,
        agent_id: str,
        now: float,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT * FROM agent_budget_periods
            WHERE owner_user_id=? AND agent_id=? AND status='open'
            """,
            (owner_user_id, agent_id),
        ).fetchone()
        if row is not None:
            return row
        period_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO agent_budget_periods (
                period_id, owner_user_id, agent_id, token_limit,
                used_tokens, reserved_tokens, charging_policy_version,
                revision, status, created_at
            ) VALUES (?, ?, ?, NULL, 0, 0, ?, 1, 'open', ?)
            """,
            (
                period_id,
                owner_user_id,
                agent_id,
                _CHARGING_POLICY_VERSION,
                now,
            ),
        )
        return conn.execute(
            "SELECT * FROM agent_budget_periods WHERE period_id=?",
            (period_id,),
        ).fetchone()

    @staticmethod
    def _require_text(field: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} is required")

    @staticmethod
    def _require_sha256(field: str, value: str) -> None:
        if (
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"{field} must be sha256")

    @staticmethod
    def _require_non_negative(field: str, value: int) -> None:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ValueError(f"{field} must be a non-negative integer")

    @staticmethod
    def _optional_hash(value: str) -> str:
        if not value:
            return ""
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _reserved_invocation_value(row: sqlite3.Row) -> dict[str, Any]:
        token_limit = row["current_token_limit"]
        return {
            "invocation_id": str(row["invocation_id"]),
            "period_id": str(row["period_id"]),
            "owner_user_id": str(row["owner_user_id"]),
            "agent_id": str(row["agent_id"]),
            "status": str(row["status"]),
            "token_limit": (
                int(token_limit) if token_limit is not None else None
            ),
            "reserved_tokens": int(row["reserved_tokens"]),
            "created_at": float(row["created_at"]),
        }

    @staticmethod
    def _settled_invocation_value(row: sqlite3.Row) -> dict[str, Any]:
        charged_tokens = int(row["charged_tokens"])
        reserved_tokens = int(row["reserved_tokens"])
        return {
            "invocation_id": str(row["invocation_id"]),
            "period_id": str(row["period_id"]),
            "status": str(row["status"]),
            "charged_tokens": charged_tokens,
            "measurement_quality": str(row["measurement_quality"]),
            "released_tokens": reserved_tokens - charged_tokens,
            "settled_at": float(row["settled_at"]),
        }


def database_path() -> Path:
    configured = os.environ.get("AGENT_FLOW_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    cache_path = Path(Settings.CACHE_DB_PATH)
    return cache_path.with_name(
        f"{cache_path.stem}.agent-flow{cache_path.suffix or '.sqlite'}"
    )


def get_store() -> AgentFlowStore:
    path = str(database_path())
    store = _STORE_CACHE.get(path)
    if store is None:
        store = AgentFlowStore(path)
        _STORE_CACHE[path] = store
    return store


def clear_store_cache() -> None:
    _STORE_CACHE.clear()
