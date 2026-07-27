"""Ephemeral Profile Strategy Actor source bundles for one research Run."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import time
import uuid
from typing import Any, Iterable

import settings as Settings


MAX_FILES = 200
MAX_SOURCE_BYTES = 20 * 1024 * 1024
_SCOPE = re.compile(r"^[0-9a-f]{32}$")


def _root() -> Path:
    path = Path(Settings.CACHE_DB_PATH).expanduser().resolve().parent / "transient_strategy_sources"
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _path(scope_id: str) -> Path:
    if not _SCOPE.fullmatch(str(scope_id or "")):
        raise ValueError("invalid transient strategy source scope")
    return _root() / scope_id


def validate_entries(raw: Any) -> list[dict[str, str]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_FILES:
        raise ValueError("transient_strategy_sources must be a bounded array")
    result, seen, total = [], set(), 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("transient strategy source must be an object")
        name = str(item.get("path") or "").replace("\\", "/").strip()
        parts = name.split("/")
        if len(parts) < 2 or parts[0] != "strategies" or not name.endswith(".py") or ".." in parts:
            raise ValueError("transient strategy source path must be strategies/<name>.py")
        if name in seen:
            raise ValueError(f"duplicate transient strategy source: {name}")
        source = item.get("source_code")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"transient strategy source is empty: {name}")
        encoded = source.encode("utf-8")
        total += len(encoded)
        if total > MAX_SOURCE_BYTES:
            raise ValueError("transient strategy source bundle exceeds size limit")
        seen.add(name)
        result.append({"path": name, "source_code": source})
    return result


def create_scope(*, owner: str, entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    owner = str(owner or "").strip()
    if not owner:
        raise ValueError("transient strategy source owner is required")
    validated = validate_entries(list(entries))
    if not validated:
        return {"scope_id": "", "files": [], "mode": "metadata_only"}
    scope_id = uuid.uuid4().hex
    root = _path(scope_id)
    try:
        files = []
        for entry in validated:
            target = root / entry["path"]
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            root.chmod(0o700)
            target.parent.chmod(0o700)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(target, flags, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(entry["source_code"].encode("utf-8"))
            files.append({
                "path": entry["path"],
                "source_sha256": hashlib.sha256(entry["source_code"].encode()).hexdigest(),
                "source_bytes": len(entry["source_code"].encode()),
            })
        manifest = {
            "schema_version": 1,
            "scope_id": scope_id,
            "owner": owner,
            "created_at": time.time(),
            "files": files,
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return {"scope_id": scope_id, "mode": "transient_run_source", "files": files}


def load_source(scope_id: str, source_path: str, *, owner: str) -> str | None:
    try:
        root = _path(scope_id)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if str(manifest.get("scope_id") or "") != str(scope_id):
            return None
        if str(manifest.get("owner") or "") != str(owner or ""):
            return None
        item = next((value for value in manifest.get("files", []) if value.get("path") == source_path), None)
        if not item:
            return None
        relative = PurePosixPath(str(source_path).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "strategies":
            return None
        target = root.joinpath(*relative.parts)
        if not target.resolve().is_relative_to(root.resolve()):
            return None
        source = target.read_text(encoding="utf-8")
        return source if hashlib.sha256(source.encode()).hexdigest() == item.get("source_sha256") else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def cleanup_scope(scope_id: str) -> bool:
    try:
        root = _path(scope_id)
        if root.exists():
            shutil.rmtree(root)
            return True
    except (OSError, ValueError):
        return False
    return False


def scope_status(scope_id: str) -> str:
    if not scope_id:
        return "not_applicable"
    try:
        root = _path(scope_id)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("scope_id") != scope_id or not manifest.get("owner"):
            return "corrupt"
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            return "corrupt"
        for item in files:
            path = root / str(item.get("path") or "")
            if path.stat().st_size != int(item.get("source_bytes") or -1):
                return "corrupt"
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != str(item.get("source_sha256") or ""):
                return "corrupt"
        return "available"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        try:
            return "cleaned" if not _path(scope_id).exists() else "corrupt"
        except ValueError:
            return "invalid"


def cleanup_stale_scopes(repository: Any, *, max_age_seconds: float = 3600.0) -> int:
    now = time.time()
    removed = 0
    for candidate in _root().iterdir():
        if not candidate.is_dir() or not _SCOPE.fullmatch(candidate.name):
            continue
        try:
            manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
            created = float(manifest.get("created_at") or 0.0)
            if created and now - created < max_age_seconds:
                continue
            if repository.has_active_transient_scope(scope_id=candidate.name):
                continue
            shutil.rmtree(candidate)
            removed += 1
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return removed
