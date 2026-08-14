"""Safe Profile metadata projections for Manager and peer responses."""

from __future__ import annotations

from typing import Any


_PROFILE_BLOCKED_KEYS = {
    "password", "password_hash", "secret", "token", "access_token",
    "workspace_root", "worktree_path", "git_common_dir", "research_root",
    "strategy_root", "path", "absolute_path", "local_path", "source_code",
    "session_ref",
}


def safe_profile_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Remove device-local paths and credentials from a profile projection."""
    if depth > 8:
        return None
    normalized_key = str(key or "").strip().lower()
    if normalized_key in _PROFILE_BLOCKED_KEYS or normalized_key.endswith("_path"):
        return None
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child_value in value.items():
            cleaned = safe_profile_value(
                child_value, key=str(child_key), depth=depth + 1,
            )
            if cleaned is not None:
                result[str(child_key)] = cleaned
        return result
    if isinstance(value, (list, tuple)):
        return [
            cleaned
            for child in list(value)[:256]
            if (cleaned := safe_profile_value(
                child, depth=depth + 1,
            )) is not None
        ]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def control_profile_projection(
    row: dict[str, Any], principal: str,
) -> dict[str, Any]:
    """Build a Profile object from one PostgreSQL control row."""
    payload = row.get("payload")
    value = dict(payload) if isinstance(payload, dict) else {}
    profile_id = str(row.get("profile_id") or value.get("profile_id") or "")
    display_name = str(
        row.get("display_name") or value.get("display_name") or profile_id
    )
    value.update({
        "profile_id": profile_id,
        "display_name": display_name,
        "session_binding": {"principal_ref": str(principal)},
    })
    if row.get("updated_at") is not None:
        value["updated_at"] = str(row["updated_at"])
    return value
