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
                evidence=evidence,
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


def contract_for_edge(edge: dict[str, Any]) -> dict[str, str] | None:
    """Describe a declared server action without exposing its implementation.

    The actual, branch-bound request schema remains an on-demand
    ``research step inspect`` response. This compact descriptor tells an Agent
    that it must fetch that contract instead of relying on a Skill example.
    """
    action = str(edge.get("server_action") or "")
    for handler in _HANDLERS:
        if action == handler.SERVER_ACTION:
            if action == data_contract.SERVER_ACTION:
                return {
                    "request_field": "evidence_refs",
                    "contract_command": (
                        "factortester research evidence source "
                        "capture-terminal -- factortester products availability "
                        "<scope> --json"
                    ),
                    "submission": (
                        "bind the resulting Terminal Evidence; node advance "
                        "reuses its frozen profile"
                    ),
                }
            if action == factor_semantics.SERVER_ACTION:
                return {
                    "mode": "automatic",
                    "factor_subject_source": (
                        "current_report_requirement_bindings"
                    ),
                    "submission": (
                        "node advance sends the typed factors bound to this "
                        "transition's report components; the server validates "
                        "their exact frozen identities"
                    ),
                }
            return {
                "request_field": handler.REQUEST_FIELD,
                "contract_command": (
                    "factortester research step inspect "
                    "<instance-id> <branch-id> --output <file>"
                ),
                "submission": "include the request only in transition evidence",
            }
    return None
