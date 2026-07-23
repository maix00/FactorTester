"""Bind a packet calibration receipt to one exact shadow workload."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson

from server.services.research_graph.packet_calibration import (
    packet_calibration_receipt_verifier,
    verify_packet_calibration_receipt,
)
from server.services.research_graph.protocol import json_hash


PACKET_SCHEMA_HASH = hashlib.sha256(
    b"research-graph-local-packet-schema@2"
).hexdigest()
SERIALIZER_HASH = hashlib.sha256(
    f"orjson:{orjson.__version__}:sorted-server-projection@1".encode()
).hexdigest()


def bind_packet_calibration(
    *,
    graph: dict[str, Any],
    context: dict[str, Any],
    packet_budget: dict[str, Any],
    cohort: list[dict[str, Any]],
    request: dict[str, Any] | None,
) -> dict[str, Any]:
    if int(packet_budget.get("schema_version") or 0) < 2:
        return {"calibration_status": "legacy_schema_exempt"}
    if not isinstance(request, dict):
        return {"calibration_status": "missing_calibration_receipt"}
    provider_id = str(request.get("provider_id") or "")
    expected_identity = {
        "graph_hash": str(graph.get("content_hash") or ""),
        "packet_schema_hash": PACKET_SCHEMA_HASH,
        "serializer_hash": SERIALIZER_HASH,
        "provider_id": _single_identity(cohort, "provider_id"),
        "model_id": _single_identity(cohort, "model_id"),
        "tokenizer_id": str(request.get("tokenizer_id") or ""),
        "tokenizer_revision": str(
            request.get("tokenizer_revision") or ""
        ),
        "runtime_id": _single_identity(cohort, "runtime_id"),
        "capability_compatibility_hash": json_hash({
            "contract": "anonymous-capability-compatibility@1",
            "current_resolution_hash": str(
                (context.get("branch") or {}).get(
                    "capability_resolution_hash"
                ) or ""
            ),
            "capability_descriptors": graph.get("capability_descriptors") or {},
            "requirement_resolver_bindings": (
                graph.get("requirement_resolver_bindings") or {}
            ),
        }),
    }
    if provider_id != expected_identity["provider_id"]:
        raise ValueError(
            "packet calibration Provider does not match shadow cohort"
        )
    return verify_packet_calibration_receipt(
        receipt=str(request.get("receipt") or ""),
        expected_identity=expected_identity,
        policy=packet_budget,
        verifier=packet_calibration_receipt_verifier(provider_id),
    )


def _single_identity(rows: list[dict[str, Any]], field: str) -> str:
    values = {
        str(row.get(field) or "")
        for row in rows
        if str(row.get(field) or "")
    }
    if len(values) != 1:
        raise ValueError(
            f"shadow token cohort requires one {field} identity"
        )
    return next(iter(values))
