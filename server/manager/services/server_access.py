"""Server-owned access declarations exposed through the Manager API.

The Manager CLI must not guess how a host is administered.  A deployment may
put non-secret connection metadata in the server's ``.settings`` file; this
module validates and projects that metadata without ever loading credentials
or executable commands into an API response.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit


_SETTINGS_NAME = ".settings"
_ACCESS_KEY = "management_access"
_METHODS_KEYS = ("methods", "connections")
_ALLOWED_KEYS = frozenset({
    "id",
    "kind",
    "label",
    "profile",
    "endpoint",
    "host",
    "port",
    "capabilities",
    "notes",
})
_SECRET_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "private_key",
    "private-key",
    "credential",
    "command",
    "script",
)


def configured_management_access(repo: Path) -> tuple[dict[str, Any], ...]:
    """Read access metadata from the Manager's colocated ``.settings``.

    The normal deployment mounts ``.settings`` at the repository root.  Local
    worktrees historically keep it one directory above the checkout, so that
    location is accepted as a compatibility fallback.  A missing file or
    missing key means that the server advertises no host-management method;
    the CLI never invents one.
    """
    settings = _load_settings(repo)
    if not settings:
        return ()
    raw = settings.get(_ACCESS_KEY, ())
    if isinstance(raw, Mapping):
        for key in _METHODS_KEYS:
            if key in raw:
                raw = raw[key]
                break
        else:
            raw = ()
    if raw in (None, ""):
        return ()
    if not isinstance(raw, list):
        raise ValueError(".settings management_access must be a list or object")
    methods = tuple(
        _normalize_method(item, index=index)
        for index, item in enumerate(raw)
    )
    ids = [str(item["id"]) for item in methods]
    if len(ids) != len(set(ids)):
        raise ValueError(".settings management_access method ids must be unique")
    return methods


def _load_settings(repo: Path) -> dict[str, Any]:
    for candidate in _settings_candidates(repo):
        if not candidate.is_file():
            continue
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid Manager settings file: {candidate}") from exc
        if not isinstance(value, dict):
            raise ValueError(".settings must contain a JSON object")
        return value
    return {}


def _settings_candidates(repo: Path) -> tuple[Path, ...]:
    root = Path(repo).expanduser().resolve()
    candidates = [root / _SETTINGS_NAME]
    parent = root.parent / _SETTINGS_NAME
    if parent != candidates[0]:
        candidates.append(parent)
    return tuple(candidates)


def _normalize_method(value: object, *, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f".settings management_access[{index}] must be an object")
    unexpected = set(value) - _ALLOWED_KEYS
    if unexpected:
        raise ValueError(
            ".settings management_access contains unsupported fields: "
            + ", ".join(sorted(str(key) for key in unexpected))
        )
    for key in value:
        lowered = str(key).lower()
        if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
            raise ValueError(
                ".settings management_access cannot contain credentials or commands"
            )

    method_id = _text(value.get("id"), field="id", index=index, required=True)
    kind = _text(value.get("kind"), field="kind", index=index, required=True)
    result: dict[str, Any] = {"id": method_id, "kind": kind}
    for field in ("label", "profile", "endpoint", "host", "notes"):
        selected = _text(value.get(field), field=field, index=index)
        if selected:
            result[field] = selected
    if "port" in value and value.get("port") not in (None, ""):
        try:
            port = int(value["port"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f".settings management_access[{index}].port must be an integer"
            ) from exc
        if not 1 <= port <= 65535:
            raise ValueError(
                f".settings management_access[{index}].port is outside 1..65535"
            )
        result["port"] = port
    if "capabilities" in value:
        capabilities = value.get("capabilities")
        if not isinstance(capabilities, list):
            raise ValueError(
                f".settings management_access[{index}].capabilities must be a list"
            )
        result["capabilities"] = [
            _text(item, field="capabilities", index=index, required=True)
            for item in capabilities
        ]
    return result


def _text(
    value: object,
    *,
    field: str,
    index: int,
    required: bool = False,
) -> str:
    result = str(value or "").strip()
    if len(result) > 1024:
        raise ValueError(
            f".settings management_access[{index}].{field} is too long"
        )
    if required and not result:
        raise ValueError(
            f".settings management_access[{index}].{field} is required"
        )
    if field == "endpoint" and result:
        try:
            parsed = urlsplit(result)
        except ValueError as exc:
            raise ValueError(
                f".settings management_access[{index}].endpoint is invalid"
            ) from exc
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                ".settings management_access.endpoint cannot contain credentials"
            )
    return result


__all__ = ["configured_management_access"]
