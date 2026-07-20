"""Dispatch cold-path server evidence actions declared by Graph edges."""

from __future__ import annotations

from typing import Any

from . import data_contract, factor_semantics, job_attempt


_HANDLERS = (data_contract, factor_semantics, job_attempt)


def prepare(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    edge_id: str,
    evidence: dict[str, Any],
) -> list[tuple[Any, dict[str, Any] | None]]:
    return [
        (
            handler,
            handler.prepare_transition(
                instance_id=instance_id,
                branch_id=branch_id,
                owner=owner,
                edge_id=edge_id,
                request=evidence.get(handler.REQUEST_FIELD),
            ),
        )
        for handler in _HANDLERS
    ]


def bind(
    evidence: dict[str, Any],
    prepared: list[tuple[Any, dict[str, Any] | None]],
) -> dict[str, Any]:
    value = evidence
    for handler, item in prepared:
        value = handler.bind_server_evidence(value, item)
    return value


def validate(
    *,
    row: Any,
    edge: dict[str, Any],
    prepared: list[tuple[Any, dict[str, Any] | None]],
) -> None:
    for handler, item in prepared:
        handler.validate_preflight(row=row, edge=edge, prepared=item)


def guard_facts(
    prepared: list[tuple[Any, dict[str, Any] | None]],
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for _, item in prepared:
        if item is not None:
            facts.update(item["guard_facts"])
    return facts
