"""Authoritative fragment extraction for captured research sources."""

from __future__ import annotations

from typing import Any

from .validation import digest


def extract_job_fragment(
    source: dict[str, Any], selector: dict[str, Any],
) -> tuple[Any, str]:
    """Resolve a small Job fragment from the immutable captured snapshot."""
    snapshot = source.get("audit")
    if not isinstance(snapshot, dict):
        raise ValueError("captured Job source has no authoritative snapshot")
    if "field" in selector:
        field = str(selector["field"] or "").strip()
        if field not in snapshot:
            raise ValueError(f"Job fragment field is unavailable: {field}")
        selected = snapshot[field]
        value = selected if isinstance(selected, dict) else {field: selected}
    elif "json_pointer" in selector:
        selected = _json_pointer(
            snapshot, str(selector["json_pointer"] or ""),
        )
        value = selected if isinstance(selected, dict) else {"value": selected}
    elif "artifact_ref" in selector:
        artifact_ref = str(selector["artifact_ref"] or "").strip()
        value = next(
            (
                item for item in snapshot.get("artifacts") or []
                if isinstance(item, dict)
                and str(item.get("name") or item.get("filename") or "")
                == artifact_ref
            ),
            None,
        )
        if value is None:
            raise ValueError(
                f"Job fragment artifact is unavailable: {artifact_ref}"
            )
    else:
        raise ValueError(
            "Job fragment selector is not available from the captured snapshot"
        )
    return value, digest(value)


def _json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError("json_pointer must start with /")
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
                continue
            except (IndexError, TypeError, ValueError):
                pass
        raise ValueError(f"Job fragment json_pointer is unavailable: {pointer}")
    return current


__all__ = ["extract_job_fragment"]
