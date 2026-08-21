"""Safe Profile metadata projections for Manager and peer responses."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

SELF_PROFILE_ID = "self"
SELF_PROFILE_KIND = "self"


_PROFILE_BLOCKED_KEYS = {
    "password", "password_hash", "secret", "token", "access_token",
    "workspace_root", "worktree_path", "git_common_dir", "research_root",
    "strategy_root", "path", "absolute_path", "local_path", "source_code",
    "session_ref",
}


def self_profile_projection(principal: str) -> dict[str, Any]:
    """Return the minimal reserved Profile metadata for one account."""
    owner = str(principal or "").strip()
    if not owner:
        raise ValueError("profile principal is required")
    return {
        "schema_version": 9,
        "profile_id": SELF_PROFILE_ID,
        "profile_kind": SELF_PROFILE_KIND,
        "status": "active",
        "display_name": SELF_PROFILE_ID,
        "runtime_kind": "server",
        "workspaces": [],
        "agents": [],
        "research_records": [],
        "session_binding": {"principal_ref": owner},
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
    value = safe_profile_value(payload) if isinstance(payload, dict) else {}
    if not isinstance(value, dict):
        value = {}
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


class ProfileProjectionCache:
    """Durable, source-free Profile projections used during PG outages.

    The cache is deliberately separate from the user's Client root.  A public
    Manager normally cannot mount that root, and a control-database outage
    must not make an already synchronized Profile disappear.  Every value is
    sanitized before it is written, and each principal gets a hashed filename
    so usernames never become part of the filesystem layout.
    """

    SCHEMA_VERSION = 1

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self._lock = threading.RLock()

    def read(self, principal: str) -> list[dict[str, Any]]:
        with self._lock:
            document = self._read_document(principal)
            return self._profiles(document)

    def pending(self, principal: str) -> list[dict[str, Any]]:
        with self._lock:
            document = self._read_document(principal)
            pending_ids = {
                str(item).strip()
                for item in document.get("pending_profile_ids") or []
                if str(item).strip()
            }
            return [
                item for item in self._profiles(document)
                if str(item.get("profile_id") or "") in pending_ids
            ]

    def upsert(self, principal: str, profile: dict[str, Any]) -> None:
        with self._lock:
            owner = self._principal(principal)
            projection = safe_profile_value(profile)
            if not isinstance(projection, dict):
                raise ValueError("profile projection must be an object")
            profile_id = str(projection.get("profile_id") or "").strip()
            if not profile_id:
                raise ValueError("profile_id is required")
            document = self._read_document(owner)
            profiles = [
                item for item in document.get("profiles") or []
                if isinstance(item, dict)
                and str(item.get("profile_id") or "") != profile_id
            ]
            profiles.append(projection)
            pending_ids = {
                str(item).strip()
                for item in document.get("pending_profile_ids") or []
                if str(item).strip()
            }
            pending_ids.add(profile_id)
            self._write_document(owner, profiles, pending_ids)

    def mark_synced(self, principal: str, profile_id: str) -> None:
        with self._lock:
            owner = self._principal(principal)
            document = self._read_document(owner)
            wanted = str(profile_id or "").strip()
            pending_ids = {
                str(item).strip()
                for item in document.get("pending_profile_ids") or []
                if str(item).strip() and str(item).strip() != wanted
            }
            self._write_document(
                owner,
                [
                    item for item in document.get("profiles") or []
                    if isinstance(item, dict)
                ],
                pending_ids,
            )

    def _read_document(self, principal: str) -> dict[str, Any]:
        owner = self._principal(principal)
        try:
            path = self._path(owner)
            if path.stat().st_size > 4 * 1024 * 1024:
                return {"schema_version": self.SCHEMA_VERSION, "profiles": []}
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {"schema_version": self.SCHEMA_VERSION, "profiles": []}
        if not isinstance(value, dict) or value.get("principal") not in (None, owner):
            return {"schema_version": self.SCHEMA_VERSION, "profiles": []}
        return value

    @staticmethod
    def _profiles(document: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in document.get("profiles") or []:
            cleaned = safe_profile_value(item)
            if isinstance(cleaned, dict) and str(cleaned.get("profile_id") or ""):
                result.append(cleaned)
        return result

    def _write_document(
        self,
        principal: str,
        profiles: list[dict[str, Any]],
        pending_ids: set[str],
    ) -> None:
        owner = self._principal(principal)
        path = self._path(owner)
        document = {
            "schema_version": self.SCHEMA_VERSION,
            "principal": owner,
            "profiles": [
                cleaned
                for item in profiles
                if isinstance(cleaned := safe_profile_value(item), dict)
                and str(cleaned.get("profile_id") or "")
            ],
            "pending_profile_ids": sorted(pending_ids),
            "updated_at": time.time(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, staging = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent,
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staging, path)
        finally:
            try:
                os.unlink(staging)
            except FileNotFoundError:
                pass

    def _path(self, principal: str) -> Path:
        owner = self._principal(principal)
        digest = hashlib.sha256(owner.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    @staticmethod
    def _principal(principal: str) -> str:
        value = str(principal or "").strip()
        if not value:
            raise ValueError("profile principal is required")
        return value
