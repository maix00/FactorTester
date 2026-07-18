"""Atomic Agent invocation reservation, claim, release, and settlement."""

from __future__ import annotations

from pathlib import Path
import time
import uuid
from typing import Any

import orjson

from .budget_periods import BudgetPeriods
from .queries import (
    invocation_value,
    reserved_invocation_value,
    settled_invocation_value,
)
from .schema import connect_agent_flow
from .validation import (
    RESERVED,
    SETTLED,
    invocation_request_hash,
    optional_hash,
    require_non_negative,
    require_sha256,
    require_text,
)


class InvocationLifecycle:
    def __init__(self, db_path: Path, budgets: BudgetPeriods) -> None:
        self.db_path = db_path
        self.budgets = budgets

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
        require_text("owner_user_id", owner_user_id)
        require_text("agent_id", agent_id)
        require_text("actor_role", actor_role)
        require_text("authority_scope", authority_scope)
        require_text("purpose", purpose)
        if (
            actor_role in {"backend_verifier", "implementation_agent"}
            and authority_scope != "server_backend_code"
        ):
            raise ValueError(
                f"{actor_role} requires server_backend_code authority"
            )
        require_sha256("agent_principal_hash", agent_principal_hash)
        require_sha256("lineage_hash", lineage_hash)
        require_non_negative("max_input_tokens", max_input_tokens)
        require_non_negative("max_output_tokens", max_output_tokens)
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
            raise ValueError(
                "context_cost values must be non-negative integers"
            )

        request_hash = invocation_request_hash({
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
        })
        now = time.time()
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
                    return reserved_invocation_value(existing)
            period = self.budgets.load_or_create_open_period(
                conn,
                owner_user_id=owner_user_id,
                agent_id=agent_id,
                now=now,
            )
            if bool(period["reset_pending"]):
                raise ValueError("budget reset is pending")
            token_limit = (
                int(period["token_limit"])
                if period["token_limit"] is not None else None
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
                    max_input_tokens, max_output_tokens, reserved_tokens,
                    context_cost_json, status, created_at
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
            "status": RESERVED,
            "token_limit": token_limit,
            "reserved_tokens": reserved_tokens,
            "created_at": now,
        }

    def release_invocation(
        self,
        *,
        owner_user_id: str,
        invocation_id: str,
    ) -> dict[str, Any]:
        now = time.time()
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM agent_invocations
                WHERE owner_user_id=?
                  AND invocation_id=?
                  AND status='reserved'
                """,
                (
                    owner_user_id,
                    invocation_id,
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
            "reservation_id": invocation_id,
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
                require_non_negative(field, value)
        if (input_tokens is None) != (output_tokens is None):
            raise ValueError(
                "input_tokens and output_tokens must both be supplied or omitted"
            )

        now = time.time()
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT i.*,
                       p.reset_pending AS period_reset_pending,
                       p.next_token_limit,
                       p.owner_user_id AS period_owner_user_id,
                       p.agent_id AS period_agent_id
                FROM agent_invocations i
                JOIN agent_budget_periods p ON p.period_id=i.period_id
                WHERE i.invocation_id=? AND i.owner_user_id=?
                """,
                (invocation_id, owner_user_id),
            ).fetchone()
            if row is None:
                raise ValueError("Agent invocation not found")

            request_hash = optional_hash(provider_request_id)
            if str(row["status"]) == SETTLED:
                requested_quality = (
                    "reserved_fallback"
                    if input_tokens is None else "provider_actual"
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
                return settled_invocation_value(row)
            if str(row["status"]) != RESERVED:
                raise ValueError("Agent invocation is not reservable")

            reserved_tokens = int(row["reserved_tokens"])
            if input_tokens is None:
                charged_tokens = reserved_tokens
                input_value = output_value = None
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
                    optional_hash(provider_attestation),
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
            if bool(row["period_reset_pending"]):
                self.budgets.finish_pending_reset(
                    conn,
                    period_row=row,
                    now=now,
                )
        return {
            "invocation_id": invocation_id,
            "period_id": str(row["period_id"]),
            "status": SETTLED,
            "charged_tokens": charged_tokens,
            "measurement_quality": measurement_quality,
            "released_tokens": reserved_tokens - charged_tokens,
            "settled_at": now,
        }
