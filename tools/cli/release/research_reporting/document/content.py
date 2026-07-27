"""Bounded content validation for report components."""

from __future__ import annotations

from typing import Any

from .validation_limits import MAX_TEXT

# Relationship metadata is represented by the adjacent bindings document.
# Rejecting it here keeps the content-only invariant true for newly authored
# reports as well as for the one-shot legacy migration.
_EXTERNAL_KEYS = {
    "graph_ref", "graph_id", "branch_ref", "branch_id", "checkpoint_ref",
    "checkpoint_id", "source_branch_ref", "source_graph_ref",
    "evidence_ref", "evidence_refs", "job_ref", "job_refs", "task_ref",
    "task_refs", "obligation_ref", "obligation_refs", "claim_ref",
    "claim_refs", "report_binding", "link", "links", "link_id",
    "link_ids", "target_ref", "source_ref", "run_ref", "run_refs",
}


def component_content(kind: str, value: Any) -> Any:
    _reject_external_keys(value)
    if kind == "code":
        _validate_code(value)
    elif kind == "math":
        _validate_math(value)
    elif kind == "table":
        if not isinstance(value, dict) or set(value) != {"columns", "rows"}:
            raise ValueError("table content must contain columns and rows")
        columns, rows = value["columns"], value["rows"]
        if not isinstance(columns, list) or not columns or len(columns) > 32:
            raise ValueError("table columns are invalid")
        if not isinstance(rows, list) or len(rows) > 4096:
            raise ValueError("table rows are invalid")
        for item in columns:
            _text(item, "table.column", maximum=256)
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ValueError("table row width is invalid")
            for cell in row:
                _text(str(cell), "table.cell", maximum=2048)
    elif kind == "image":
        if not isinstance(value, dict) or not value.get("asset_ref"):
            raise ValueError("image content requires asset_ref")
    elif value is not None and not isinstance(value, (dict, list, str, int, float, bool)):
        raise ValueError("component content is not JSON-compatible")
    if isinstance(value, str) and len(value.encode()) > MAX_TEXT:
        raise ValueError("component content is too large")
    return value


def _validate_code(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"language", "code"}:
        raise ValueError("code content must contain language and code")
    language = value["language"]
    if (
        not isinstance(language, str)
        or not language.strip()
        or any(character.isspace() for character in language)
        or len(language.encode()) > 64
    ):
        raise ValueError("code.language must be a single bounded token")
    _text(value["code"], "code.body", maximum=MAX_TEXT, allow_empty=True)


def _validate_math(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"latex", "fallback"}:
        raise ValueError("math content must contain latex and fallback")
    _text(value["latex"], "math.latex", maximum=MAX_TEXT)
    _text(value["fallback"], "math.fallback", maximum=MAX_TEXT, allow_empty=True)


def _reject_external_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in _EXTERNAL_KEYS:
                raise ValueError(
                    f"component content cannot contain external binding field: {key}"
                )
            _reject_external_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_external_keys(item)


def _text(
    value: Any, field: str, *, maximum: int, allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value.strip())
        or len(value.encode()) > maximum
    ):
        raise ValueError(f"{field} must be bounded text")
    return value
