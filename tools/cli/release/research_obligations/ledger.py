"""Schema and atomic persistence for one branch obligation ledger."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import uuid

from tools.cli.release.research_reporting.authoring.tree_store import (
    atomic_write,
)
from tools.cli.release.research_reporting.package_layout import (
    safe_package_component,
)
from .definitions import (
    normalize_definition_history,
    validate_definition_history,
)


MAX_LEDGER_BYTES = 16 * 1024 * 1024
_TOP_FIELDS = {
    "schema_version", "generation", "branch", "current_projection", "history",
}
_BRANCH_FIELDS = {
    "branch_ref", "graph_ref", "current_node", "context_ref", "checkpoint_ref",
}
_PROJECTION_FIELDS = {
    "obligations", "evidence_uses", "requirement_coverage",
    "selected_edge", "projection_hash",
}
_EVENT_TYPES = {
    "obligation_change", "edge_selected", "advance_prepared",
    "advance_receipt", "forked", "title_migrated", "obligation_split",
    "evidence_migrated", "evidence_lifecycle",
    "scope_reconciled",
}


def ledger_path(package_root: Path, branch_id: str) -> Path:
    branch = safe_package_component(branch_id, field="branch_id")
    return Path(package_root) / "branches" / branch / "obligations.json"


def initialize_ledger(
    *,
    branch_ref: str,
    graph_ref: str,
    current_node: str,
    context_ref: str,
    checkpoint_ref: str,
    obligations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    value = {
        "schema_version": 2,
        "generation": 0,
        "branch": {
            "branch_ref": _text(branch_ref, "branch_ref"),
            "graph_ref": _text(graph_ref, "graph_ref"),
            "current_node": _text(current_node, "current_node"),
            "context_ref": _text(context_ref, "context_ref"),
            "checkpoint_ref": _checkpoint_ref(checkpoint_ref),
        },
        "current_projection": {
            "obligations": deepcopy(obligations or []),
            "evidence_uses": [],
            "requirement_coverage": [],
            "selected_edge": None,
            "projection_hash": "",
        },
        "history": [],
    }
    return validate_ledger(_rehash(value))


def load_ledger(package_root: Path, branch_id: str) -> dict[str, Any]:
    path = ledger_path(package_root, branch_id)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取义务账本: {path}") from exc
    if len(payload) > MAX_LEDGER_BYTES:
        raise ValueError("obligation ledger exceeds the 16 MiB safety limit")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("obligation ledger is not valid JSON") from exc
    upgraded = validate_ledger(_upgrade_v1(value))
    return validate_ledger(_rehash(normalize_definition_history(upgraded)))


def write_ledger(
    package_root: Path,
    branch_id: str,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    value = validate_ledger(_rehash(normalize_definition_history(ledger)))
    payload = _canonical_bytes(value) + b"\n"
    if len(payload) > MAX_LEDGER_BYTES:
        raise ValueError("obligation ledger exceeds the 16 MiB safety limit")
    atomic_write(ledger_path(package_root, branch_id), payload)
    return value


def canonicalize_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    return validate_ledger(_rehash(normalize_definition_history(ledger)))


def append_event(
    ledger: dict[str, Any],
    *,
    event_type: str,
    payload: dict[str, Any],
    created_at: float | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    if event_type not in _EVENT_TYPES:
        raise ValueError(f"unsupported obligation ledger event: {event_type}")
    if not isinstance(payload, dict):
        raise ValueError("obligation ledger event payload must be an object")
    value = normalize_definition_history(ledger)
    sequence = int(value["generation"]) + 1
    timestamp = time.time() if created_at is None else float(created_at)
    event = {
        "sequence": sequence,
        "event_id": event_id or uuid.uuid4().hex,
        "event_type": event_type,
        "created_at": timestamp,
        **deepcopy(payload),
    }
    value["history"].append(event)
    value["generation"] = sequence
    return validate_ledger(_rehash(normalize_definition_history(value)))


def projection_hash(projection: dict[str, Any]) -> str:
    value = deepcopy(projection)
    value.pop("projection_hash", None)
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def ledger_hash(ledger: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(validate_ledger(ledger))).hexdigest()


def validate_ledger(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != _TOP_FIELDS
        or value.get("schema_version") != 2
    ):
        raise ValueError("obligation ledger schema is invalid")
    generation = value.get("generation")
    if not isinstance(generation, int) or generation < 0:
        raise ValueError("obligation ledger generation is invalid")
    branch = value.get("branch")
    if not isinstance(branch, dict) or set(branch) != _BRANCH_FIELDS:
        raise ValueError("obligation ledger branch identity is invalid")
    for field in _BRANCH_FIELDS - {"checkpoint_ref"}:
        _text(branch.get(field), field)
    _checkpoint_ref(branch.get("checkpoint_ref"))
    projection = value.get("current_projection")
    if not isinstance(projection, dict) or set(projection) != _PROJECTION_FIELDS:
        raise ValueError("obligation ledger projection is invalid")
    for field in ("obligations", "evidence_uses", "requirement_coverage"):
        if not isinstance(projection.get(field), list) or any(
            not isinstance(item, dict) for item in projection[field]
        ):
            raise ValueError(f"obligation ledger {field} must be an object array")
    selected = projection.get("selected_edge")
    if selected is not None and not isinstance(selected, dict):
        raise ValueError("obligation ledger selected_edge must be an object or null")
    if projection.get("projection_hash") != projection_hash(projection):
        raise ValueError("obligation ledger projection_hash mismatch")
    history = value.get("history")
    if not isinstance(history, list) or len(history) != generation:
        raise ValueError("obligation ledger history does not match generation")
    for sequence, event in enumerate(history, start=1):
        if (
            not isinstance(event, dict)
            or event.get("sequence") != sequence
            or event.get("event_type") not in _EVENT_TYPES
            or not isinstance(event.get("event_id"), str)
            or not event["event_id"]
            or not isinstance(event.get("created_at"), (int, float))
        ):
            raise ValueError("obligation ledger event is invalid")
    validate_definition_history(history, projection["obligations"])
    _canonical_bytes(value)
    return value


def _upgrade_v1(value: Any) -> Any:
    """Upgrade the one historical ledger schema in memory exactly once."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return value
    upgraded = deepcopy(value)
    projection = upgraded.get("current_projection")
    if not isinstance(projection, dict):
        return value
    projection["evidence_uses"] = []
    upgraded["schema_version"] = 2
    return _rehash(upgraded)


def _rehash(value: dict[str, Any]) -> dict[str, Any]:
    value["current_projection"]["projection_hash"] = projection_hash(
        value["current_projection"]
    )
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def _checkpoint_ref(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("checkpoint_ref must be a string")
    return value
