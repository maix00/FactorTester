"""Validate and normalize four legacy accounting owners before cutover."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import sqlite3
from typing import Any


_VALID_RESERVATION_STATUSES = {"granted", "committed", "released"}


def prepare_legacy_accounting(
    *,
    budgets: list[sqlite3.Row],
    reservations: list[sqlite3.Row],
    receipts: list[sqlite3.Row],
    executions: list[sqlite3.Row],
    agent_id_by_scope: dict[tuple[str, str], str],
) -> dict[str, list[dict[str, Any]]]:
    budget_by_scope = _index_budgets(budgets)
    _require_explicit_agent_mappings(
        budget_by_scope=budget_by_scope,
        reservations=reservations,
        agent_id_by_scope=agent_id_by_scope,
    )
    receipt_by_id = {
        str(row["provider_receipt_id"]): row for row in receipts
    }
    execution_by_reservation = _index_executions(
        executions,
        reservations,
    )
    referenced_receipts: set[str] = set()
    aggregate_used: defaultdict[tuple[str, str], int] = defaultdict(int)
    aggregate_reserved: defaultdict[tuple[str, str], int] = defaultdict(int)
    invocation_rows = [
        _prepare_invocation(
            reservation=reservation,
            receipts=receipts,
            receipt_by_id=receipt_by_id,
            execution_by_reservation=execution_by_reservation,
            budget_by_scope=budget_by_scope,
            agent_id_by_scope=agent_id_by_scope,
            referenced_receipts=referenced_receipts,
            aggregate_used=aggregate_used,
            aggregate_reserved=aggregate_reserved,
        )
        for reservation in reservations
    ]
    orphan_receipts = set(receipt_by_id) - referenced_receipts
    if orphan_receipts:
        raise ValueError(
            "legacy provider receipt is not referenced by its reservation: "
            + sorted(orphan_receipts)[0]
        )
    period_rows = _prepare_periods(
        budget_by_scope=budget_by_scope,
        agent_id_by_scope=agent_id_by_scope,
        aggregate_used=aggregate_used,
        aggregate_reserved=aggregate_reserved,
    )
    return {"periods": period_rows, "invocations": invocation_rows}


def _index_budgets(
    budgets: list[sqlite3.Row],
) -> dict[tuple[str, str], sqlite3.Row]:
    result: dict[tuple[str, str], sqlite3.Row] = {}
    for row in budgets:
        scope_key = (str(row["owner_user_id"]), str(row["scope_id"]))
        if scope_key in result:
            raise ValueError(
                f"duplicate legacy token budget: {scope_key[0]}:{scope_key[1]}"
            )
        result[scope_key] = row
    return result


def _require_explicit_agent_mappings(
    *,
    budget_by_scope: dict[tuple[str, str], sqlite3.Row],
    reservations: list[sqlite3.Row],
    agent_id_by_scope: dict[tuple[str, str], str],
) -> None:
    required = set(budget_by_scope)
    required.update(
        (str(row["owner_user_id"]), str(row["scope_id"]))
        for row in reservations
    )
    missing = sorted(
        scope for scope in required
        if not str(agent_id_by_scope.get(scope) or "").strip()
    )
    if missing:
        owner, scope_id = missing[0]
        raise ValueError(
            "legacy Agent identity mapping is required for "
            f"{owner}:{scope_id}"
        )


def _index_executions(
    executions: list[sqlite3.Row],
    reservations: list[sqlite3.Row],
) -> dict[str, sqlite3.Row]:
    result: dict[str, sqlite3.Row] = {}
    for row in executions:
        reservation_id = str(row["reservation_id"])
        if reservation_id in result:
            raise ValueError(
                "multiple legacy Agent executions reference reservation "
                f"{reservation_id}"
            )
        result[reservation_id] = row
    reservation_ids = {
        str(row["reservation_id"]) for row in reservations
    }
    orphan_ids = set(result) - reservation_ids
    if orphan_ids:
        raise ValueError(
            "legacy Agent execution references unknown reservation "
            + sorted(orphan_ids)[0]
        )
    return result


def _prepare_invocation(
    *,
    reservation: sqlite3.Row,
    receipts: list[sqlite3.Row],
    receipt_by_id: dict[str, sqlite3.Row],
    execution_by_reservation: dict[str, sqlite3.Row],
    budget_by_scope: dict[tuple[str, str], sqlite3.Row],
    agent_id_by_scope: dict[tuple[str, str], str],
    referenced_receipts: set[str],
    aggregate_used: defaultdict[tuple[str, str], int],
    aggregate_reserved: defaultdict[tuple[str, str], int],
) -> dict[str, Any]:
    owner = str(reservation["owner_user_id"])
    scope_id = str(reservation["scope_id"])
    scope_key = (owner, scope_id)
    if scope_key not in budget_by_scope:
        raise ValueError(
            f"legacy reservation has no token budget: {owner}:{scope_id}"
        )
    reservation_id = str(reservation["reservation_id"])
    status = str(reservation["status"])
    if status not in _VALID_RESERVATION_STATUSES:
        raise ValueError(f"invalid legacy reservation status: {status}")
    max_input = int(reservation["max_input_tokens"])
    max_output = int(reservation["max_output_tokens"])
    reserved_tokens = int(reservation["max_total_tokens"])
    if reserved_tokens <= 0 or reserved_tokens != max_input + max_output:
        raise ValueError(
            f"legacy reservation total is inconsistent: {reservation_id}"
        )
    receipt_id = str(reservation["provider_receipt_id"] or "")
    receipt = _resolve_receipt(
        reservation_id=reservation_id,
        status=status,
        receipt_id=receipt_id,
        receipts=receipts,
        receipt_by_id=receipt_by_id,
        referenced_receipts=referenced_receipts,
    )
    execution = execution_by_reservation.get(reservation_id)
    if execution is not None and str(
        execution["owner_user_id"]
    ) != owner:
        raise ValueError(
            "legacy Agent execution owner does not match reservation "
            f"{reservation_id}"
        )
    lifecycle = _normalize_lifecycle(
        status=status,
        reservation_id=reservation_id,
        reserved_tokens=reserved_tokens,
        max_input=max_input,
        max_output=max_output,
        receipt=receipt,
    )
    if lifecycle["status"] == "settled":
        aggregate_used[scope_key] += int(lifecycle["charged_tokens"])
    elif lifecycle["status"] == "reserved":
        aggregate_reserved[scope_key] += reserved_tokens
    return {
        "invocation_id": (
            str(execution["execution_id"])
            if execution is not None else reservation_id
        ),
        "period_id": legacy_period_id(owner, scope_id),
        "owner_user_id": owner,
        "agent_id": str(agent_id_by_scope[scope_key]).strip(),
        "legacy_reservation_id": reservation_id,
        "legacy_provider_receipt_id": receipt_id,
        "actor_role": (
            str(execution["actor_role"])
            if execution is not None else str(reservation["work_kind"])
        ),
        "authority_scope": (
            str(execution["authority_scope"])
            if execution is not None else "local_research"
        ),
        "purpose": str(reservation["work_kind"]),
        "runtime_id": (
            str(execution["codex_version"])
            if execution is not None else "legacy"
        ),
        "model_id": (
            str(execution["model_id"]) if execution is not None else ""
        ),
        "provider_id": str(receipt["provider"]) if receipt is not None else "",
        "agent_principal_hash": (
            str(execution["agent_principal_hash"])
            if execution is not None else _hash(f"{owner}:{reservation_id}")
        ),
        "lineage_hash": (
            str(execution["lineage_hash"])
            if execution is not None
            else _hash(f"legacy:{owner}:{reservation_id}")
        ),
        "launcher_attestation_hash": (
            _hash(str(execution["launcher_attestation"]))
            if execution is not None else ""
        ),
        "max_input_tokens": max_input,
        "max_output_tokens": max_output,
        "reserved_tokens": reserved_tokens,
        "reservation_expires_at": float(reservation["expires_at"]),
        "provider_request_hash": (
            _hash(str(receipt["provider_request_id"]))
            if receipt is not None else ""
        ),
        "provider_attestation_hash": (
            _hash(str(receipt["usage_attestation"]))
            if receipt is not None else ""
        ),
        "created_at": float(reservation["created_at"]),
        "settled_at": (
            None if lifecycle["status"] == "reserved"
            else float(
                receipt["created_at"]
                if receipt is not None
                else (
                    execution["created_at"]
                    if execution is not None
                    else reservation["created_at"]
                )
            )
        ),
        **lifecycle,
    }


def _resolve_receipt(
    *,
    reservation_id: str,
    status: str,
    receipt_id: str,
    receipts: list[sqlite3.Row],
    receipt_by_id: dict[str, sqlite3.Row],
    referenced_receipts: set[str],
) -> sqlite3.Row | None:
    receipt = receipt_by_id.get(receipt_id) if receipt_id else None
    if receipt_id:
        if receipt is None:
            raise ValueError(
                "legacy provider receipt is missing: " + receipt_id
            )
        if str(receipt["reservation_id"]) != reservation_id:
            raise ValueError(
                "legacy provider receipt does not match reservation "
                f"{reservation_id}"
            )
        referenced_receipts.add(receipt_id)
    dangling = [
        str(row["provider_receipt_id"])
        for row in receipts
        if str(row["reservation_id"]) == reservation_id
        and str(row["provider_receipt_id"]) != receipt_id
    ]
    if dangling:
        raise ValueError(
            "legacy reservation has an unreferenced provider receipt: "
            + dangling[0]
        )
    if receipt is not None and status != "committed":
        raise ValueError(
            "only a committed reservation may reference provider usage"
        )
    return receipt


def _normalize_lifecycle(
    *,
    status: str,
    reservation_id: str,
    reserved_tokens: int,
    max_input: int,
    max_output: int,
    receipt: sqlite3.Row | None,
) -> dict[str, Any]:
    if status == "granted":
        return {
            "status": "reserved",
            "input_tokens": None,
            "output_tokens": None,
            "charged_tokens": None,
            "measurement_quality": "",
        }
    if status == "released":
        return {
            "status": "released",
            "input_tokens": None,
            "output_tokens": None,
            "charged_tokens": None,
            "measurement_quality": "",
        }
    if receipt is None:
        return {
            "status": "settled",
            "input_tokens": None,
            "output_tokens": None,
            "charged_tokens": reserved_tokens,
            "measurement_quality": "reserved_fallback",
        }
    input_tokens = int(receipt["input_tokens"])
    output_tokens = int(receipt["output_tokens"])
    if input_tokens > max_input or output_tokens > max_output:
        raise ValueError(
            "legacy provider usage exceeds reservation "
            f"{reservation_id}"
        )
    return {
        "status": "settled",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "charged_tokens": input_tokens + output_tokens,
        "measurement_quality": "provider_actual",
    }


def _prepare_periods(
    *,
    budget_by_scope: dict[tuple[str, str], sqlite3.Row],
    agent_id_by_scope: dict[tuple[str, str], str],
    aggregate_used: defaultdict[tuple[str, str], int],
    aggregate_reserved: defaultdict[tuple[str, str], int],
) -> list[dict[str, Any]]:
    result = []
    for scope_key, budget in budget_by_scope.items():
        owner, scope_id = scope_key
        expected_used = aggregate_used[scope_key]
        expected_reserved = aggregate_reserved[scope_key]
        if int(budget["used_tokens"]) != expected_used or int(
            budget["reserved_tokens"]
        ) != expected_reserved:
            raise ValueError(
                "legacy token budget aggregate mismatch for "
                f"{owner}:{scope_id}: expected used/reserved "
                f"{expected_used}/{expected_reserved}"
            )
        result.append({
            "period_id": legacy_period_id(owner, scope_id),
            "owner_user_id": owner,
            "agent_id": str(agent_id_by_scope[scope_key]).strip(),
            "token_limit": int(budget["token_limit"]),
            "used_tokens": expected_used,
            "reserved_tokens": expected_reserved,
            "created_at": float(budget["created_at"]),
        })
    return result


def legacy_period_id(owner_user_id: str, scope_id: str) -> str:
    return "legacy-" + _hash(f"{owner_user_id}\0{scope_id}")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
