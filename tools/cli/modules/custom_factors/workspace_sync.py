"""Safe, hash-bound pulls into a user's local factor workspace."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any


_ALLOWED_ROOTS = frozenset({
    "custom_factors",
    "public_factors",
    "remote_factors",
})
_MANIFEST_PATH = Path(".factor_workspace") / "source_manifest.json"


def sync_local_factor_workspace(
    client: Any,
    root: str | Path,
    *,
    include_subordinates: bool = True,
) -> dict[str, Any]:
    """Pull visible sources without overwriting dirty local files."""
    workspace = _assert_workspace_root(root)
    previous = _read_manifest(workspace / _MANIFEST_PATH)
    response = client.factor_source_sync_manifest(
        include_subordinates=include_subordinates,
    )
    remote_items = _validated_remote_items(response.get("items") or [])
    old_items = _previous_items(previous)
    cache_root = workspace / ".factor_workspace" / "objects"
    cache_root.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "workspace_root": str(workspace),
        "server_id": response.get("server_id") or "",
        "principal": response.get("principal") or "",
        "downloaded": [],
        "updated": [],
        "skipped": [],
        "removed": [],
        "conflicts": [],
    }
    next_items: list[dict[str, Any]] = []
    for item in remote_items:
        path_text = str(item["path"])
        target = workspace / path_text
        remote_hash = str(item["source_sha256"])
        current_hash = _file_hash(target) if target.is_file() else ""
        previous_item = old_items.get(path_text)
        previous_hash = str(previous_item.get("source_sha256") or "") if previous_item else ""
        next_items.append(dict(item))

        if current_hash == remote_hash:
            result["skipped"].append(path_text)
            continue

        cache_path = _ensure_cached_source(
            client,
            cache_root,
            item,
        )
        if target.exists() and (
            not target.is_file()
            or (previous_hash and current_hash != previous_hash)
            or (not previous_hash and current_hash)
        ):
            staged = _stage_conflict(workspace, path_text, remote_hash, cache_path)
            result["conflicts"].append({
                "path": path_text,
                "staged_path": str(staged),
                "reason": "local source changed since the previous sync",
            })
            continue

        _copy_atomic(cache_path, target)
        result["updated" if current_hash else "downloaded"].append(path_text)

    for path_text, old_item in old_items.items():
        if path_text in {str(item["path"]) for item in remote_items}:
            continue
        target = workspace / path_text
        previous_hash = str(old_item.get("source_sha256") or "")
        current_hash = _file_hash(target) if target.is_file() else ""
        if not target.exists():
            continue
        if target.is_file() and current_hash == previous_hash:
            target.unlink()
            result["removed"].append(path_text)
            continue
        result["conflicts"].append({
            "path": path_text,
            "staged_path": "",
            "reason": "remote source was removed while local source has changes",
        })

    tombstones = [
        {"path": str(item.get("path") or ""), "source_sha256": str(item.get("source_sha256") or "")}
        for item in old_items.values()
        if str(item.get("path") or "") not in {str(item["path"]) for item in remote_items}
        and any(conflict.get("path") == str(item.get("path") or "") for conflict in result["conflicts"])
    ]
    _write_manifest(
        workspace / _MANIFEST_PATH,
        {
            "schema_version": 1,
            "server_id": response.get("server_id") or "",
            "principal": response.get("principal") or "",
            "items": next_items,
            "tombstones": tombstones,
        },
    )
    result["counts"] = {
        "downloaded": len(result["downloaded"]),
        "updated": len(result["updated"]),
        "skipped": len(result["skipped"]),
        "removed": len(result["removed"]),
        "conflicts": len(result["conflicts"]),
    }
    return result


def _assert_workspace_root(root: str | Path) -> Path:
    target = Path(root).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise ValueError(f"local canonical factor workspace does not exist: {target}")
    parts = target.parts
    for index, part in enumerate(parts[:-2]):
        if part == "profiles" and parts[index + 2] == "factor-worktree":
            raise ValueError(
                "Profile factor-worktree cannot be used as the canonical factor workspace"
            )
    for directory in ("custom_factors", "public_factors", ".factor_workspace"):
        (target / directory).mkdir(parents=True, exist_ok=True)
    return target


def _validated_remote_items(items: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("factor source manifest item is invalid")
        path_text = _safe_relative_path(raw.get("path"))
        source_hash = str(raw.get("source_sha256") or "").strip().lower()
        if len(source_hash) != 64 or any(char not in "0123456789abcdef" for char in source_hash):
            raise ValueError(f"factor source hash is invalid for {path_text}")
        source_bytes = int(raw.get("source_bytes") or 0)
        if source_bytes < 0:
            raise ValueError(f"factor source size is invalid for {path_text}")
        if path_text in seen:
            raise ValueError(f"factor source manifest contains duplicate path: {path_text}")
        seen.add(path_text)
        item = dict(raw)
        item["path"] = path_text
        item["source_sha256"] = source_hash
        item["source_bytes"] = source_bytes
        result.append(item)
    return result


def _safe_relative_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError("factor source manifest path is unsafe")
    if len(path.parts) != 2 or path.parts[0] not in _ALLOWED_ROOTS:
        raise ValueError("factor source manifest path is outside the workspace")
    if path.suffix != ".py" or path.name in {"", ".", ".."}:
        raise ValueError("factor source manifest path must be a Python file")
    return path.as_posix()


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"local factor source manifest is unreadable: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("local factor source manifest version is unsupported")
    return value


def _previous_items(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for raw in [*(manifest.get("items") or []), *(manifest.get("tombstones") or [])]:
        if not isinstance(raw, dict):
            continue
        path_text = str(raw.get("path") or "")
        if path_text:
            values[path_text] = raw
    return values


def _ensure_cached_source(client: Any, cache_root: Path, item: dict[str, Any]) -> Path:
    source_hash = str(item["source_sha256"])
    cache_path = cache_root / f"{source_hash}.py"
    expected_size = int(item["source_bytes"])
    if cache_path.is_file() and _file_hash(cache_path) == source_hash and cache_path.stat().st_size == expected_size:
        return cache_path
    cache_path.unlink(missing_ok=True)
    access_response = client.factor_source_download_access(
        object_id=str(item["object_id"]),
        source_sha256=source_hash,
    )
    access = access_response.get("access")
    if not isinstance(access, dict):
        raise ValueError("factor source download capability is missing")
    client.capability_download_to_path(
        access,
        cache_path,
        expected_sha256=source_hash,
        content_type=str(item.get("content_type") or "text/x-python"),
    )
    if _file_hash(cache_path) != source_hash or cache_path.stat().st_size != expected_size:
        raise ValueError("factor source cache verification failed")
    return cache_path


def _stage_conflict(workspace: Path, path_text: str, source_hash: str, source: Path) -> Path:
    staged = workspace / ".factor_workspace" / "downloads" / source_hash / path_text
    _copy_atomic(source, staged)
    return staged


def _copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.part")
    shutil.copyfile(source, temporary)
    os.replace(temporary, target)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.part")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


__all__ = ["sync_local_factor_workspace"]
