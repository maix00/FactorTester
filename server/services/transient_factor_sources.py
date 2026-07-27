"""Ephemeral source bundles for Profile-scoped research Runs.

The durable RunSpec stores only source hashes and the opaque scope id carried by
the Job.  Source text lives in a private filesystem scope until every attempt
of the Run reaches a terminal state, then the scope is removed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid
from typing import Any, Iterable

import settings as Settings


MAX_FILES = 200
MAX_SOURCE_BYTES = 20 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SCOPE = re.compile(r"^[0-9a-f]{32}$")


def _base_root() -> Path:
    root = Path(Settings.CACHE_DB_PATH).expanduser().resolve().parent / "transient_factor_sources"
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _scope_path(scope_id: str) -> Path:
    scope = str(scope_id or "").strip()
    if not _SCOPE.fullmatch(scope):
        raise ValueError("invalid transient factor source scope")
    return _base_root() / scope


def validate_entries(raw: Any) -> list[dict[str, Any]]:
    """Validate a bounded list of ``custom_factors/*.py`` source entries."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ValueError("transient_factor_sources must be an array")
    if len(raw) > MAX_FILES:
        raise ValueError("too many transient factor source files")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each transient factor source must be an object")
        path = str(item.get("path") or "").replace("\\", "/").strip()
        parts = path.split("/")
        if len(parts) != 2 or parts[0] != "custom_factors" or not parts[1].endswith(".py"):
            raise ValueError("transient factor source path must be custom_factors/<Factor>.py")
        factor_id = parts[1][:-3]
        if not _ID.fullmatch(factor_id):
            raise ValueError(f"invalid transient factor id: {factor_id}")
        if factor_id in seen:
            raise ValueError(f"duplicate transient factor source: {factor_id}")
        source_code = item.get("source_code")
        if not isinstance(source_code, str) or not source_code.strip():
            raise ValueError(f"transient factor source is empty: {path}")
        encoded = source_code.encode("utf-8")
        total += len(encoded)
        if total > MAX_SOURCE_BYTES:
            raise ValueError("transient factor source bundle exceeds size limit")
        seen.add(factor_id)
        entries.append({
            "factor_id": factor_id,
            "path": f"custom_factors/{factor_id}.py",
            "source_code": source_code,
            "source_sha256": hashlib.sha256(encoded).hexdigest(),
            "source_bytes": len(encoded),
        })
    return entries


def create_scope(*, owner: str, entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Persist an isolated source scope and return its source-free manifest."""
    owner = str(owner or "").strip()
    if not owner:
        raise ValueError("transient factor source owner is required")
    validated = validate_entries(list(entries))
    if not validated:
        return {"scope_id": "", "files": [], "mode": "metadata_only"}
    scope_id = uuid.uuid4().hex
    root = _scope_path(scope_id)
    custom = root / "custom_factors"
    custom.mkdir(parents=True, mode=0o700)
    manifest = {
        "schema_version": 1,
        "scope_id": scope_id,
        "owner": str(owner),
        "created_at": time.time(),
        "files": [],
    }
    try:
        for entry in validated:
            path = custom / f"{entry['factor_id']}.py"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(path, flags, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(str(entry["source_code"]).encode("utf-8"))
                fd = -1
            finally:
                if fd >= 0:
                    os.close(fd)
            metadata = {
                key: value
                for key, value in entry.items()
                if key != "source_code"
            }
            metadata["source_mtime_ns"] = path.stat().st_mtime_ns
            manifest["files"].append(metadata)
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return {
        "scope_id": scope_id,
        "mode": "transient_run_source",
        "files": manifest["files"],
    }


def load_source(scope_id: str, factor_id: str, *, owner: str = "") -> str | None:
    """Load one source only when the scope manifest belongs to *owner*."""
    owner = str(owner or "").strip()
    if not owner:
        return None
    try:
        root = _scope_path(scope_id)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if str(manifest.get("owner") or "") != owner:
            return None
        allowed = {
            str(item.get("factor_id") or "")
            for item in manifest.get("files") or []
            if isinstance(item, dict)
        }
        if factor_id not in allowed:
            return None
        path = root / "custom_factors" / f"{factor_id}.py"
        source = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        declared = next(
            (
                str(item.get("source_sha256") or "")
                for item in manifest.get("files") or []
                if isinstance(item, dict) and str(item.get("factor_id") or "") == factor_id
            ),
            "",
        )
        return source if digest == declared else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def cleanup_scope(scope_id: str) -> bool:
    try:
        root = _scope_path(scope_id)
    except ValueError:
        return False
    if not root.exists():
        return False
    try:
        shutil.rmtree(root, ignore_errors=False)
    except OSError:
        # Terminal transitions must remain durable even when a stale file
        # briefly prevents cleanup.  Startup GC can retry the scope later.
        return False
    return True


def scope_status(scope_id: str) -> str:
    if not scope_id:
        return "not_applicable"
    try:
        root = _scope_path(scope_id)
        if not root.exists():
            return "cleaned"
        manifest = json.loads(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            return "corrupt"
        for item in files:
            if not isinstance(item, dict):
                return "corrupt"
            factor_id = str(item.get("factor_id") or "")
            if not _ID.fullmatch(factor_id):
                return "corrupt"
            path = root / "custom_factors" / f"{factor_id}.py"
            stat = path.stat()
            if stat.st_size != int(item.get("source_bytes") or -1):
                return "corrupt"
            declared_mtime = int(item.get("source_mtime_ns") or 0)
            if declared_mtime and stat.st_mtime_ns != declared_mtime:
                return "corrupt"
            if not declared_mtime:
                source = path.read_text(encoding="utf-8")
                encoded = source.encode("utf-8")
                if hashlib.sha256(encoded).hexdigest() != str(
                    item.get("source_sha256") or ""
                ):
                    return "corrupt"
        return "available"
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return "invalid"


def cleanup_for_terminal_job(repository: Any, job: Any) -> bool:
    """Delete a scope after all attempts belonging to the Run are terminal."""
    factor_scope_id = str(
        (job.job_spec or {}).get("transient_factor_source_scope_id") or ""
    )
    strategy_scope_id = str(
        (job.job_spec or {}).get("transient_strategy_source_scope_id") or ""
    )
    if not factor_scope_id and not strategy_scope_id:
        return False
    if not repository.all_run_attempts_terminal(
        owner=job.owner,
        run_id=job.run_id,
    ):
        return False
    removed = cleanup_scope(factor_scope_id) if factor_scope_id else False
    if strategy_scope_id:
        from server.services.transient_strategy_sources import cleanup_scope as cleanup_strategy_scope

        removed = cleanup_strategy_scope(strategy_scope_id) or removed
    return removed


def cleanup_stale_scopes(repository: Any, *, max_age_seconds: float = 3600.0) -> int:
    """Reclaim abandoned scopes that have no active JobAttempt reference."""
    root = _base_root()
    now = time.time()
    max_age = max(0.0, float(max_age_seconds))
    removed = 0
    for candidate in root.iterdir():
        if not candidate.is_dir() or not _SCOPE.fullmatch(candidate.name):
            continue
        try:
            if now - candidate.stat().st_mtime < max_age:
                continue
            manifest = json.loads(
                (candidate / "manifest.json").read_text(encoding="utf-8")
            )
            created_at = float(manifest.get("created_at") or 0.0)
            if created_at > 0.0 and now - created_at < max_age:
                continue
            # The manifest is disposable state, not an authority for job
            # ownership.  Query every owner so a corrupted/edited owner field
            # cannot make GC delete a scope still referenced by a live job.
            if repository.has_active_transient_scope(scope_id=candidate.name):
                continue
            shutil.rmtree(candidate, ignore_errors=False)
            removed += 1
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            try:
                if repository.has_active_transient_scope(scope_id=candidate.name):
                    continue
                shutil.rmtree(candidate, ignore_errors=False)
                removed += 1
            except (OSError, TypeError, ValueError):
                continue
    return removed
