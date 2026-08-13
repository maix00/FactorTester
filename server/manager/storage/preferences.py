"""Small owner-scoped FTClient preferences stored by Manager 7998."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from server.manager.storage.control_db import ControlDatabaseError


SUPPORTED_LANGUAGES = {"system", "zh-Hans", "en"}


class UserPreferenceStore:
    def __init__(
        self,
        root: Path,
        *,
        control_store: object | None = None,
        cache_ttl_seconds: float = 300,
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.control_store = control_store
        self.cache_ttl_seconds = max(1.0, float(cache_ttl_seconds))

    def read(self, principal: str) -> dict[str, Any]:
        owner = self._principal(principal)
        local = self._read_local(owner)
        if self.control_store is not None and not self._cache_fresh(local):
            try:
                remote = self.control_store.load_user_preference(owner)
            except ControlDatabaseError:
                # Existing sessions remain usable with the last local value.
                # Do not mark the cache fresh so a later request retries PG.
                return self._public_value(local)
            language = self._language(
                remote.get("language") if isinstance(remote, dict)
                else local.get("language")
            )
            if remote is None and "language" in local:
                # One-time migration of preferences written before the shared
                # control database became authoritative.
                try:
                    migrated = self.control_store.upsert_user_preference(
                        owner, language=language,
                    )
                except ControlDatabaseError:
                    return self._public_value(local)
                if isinstance(migrated, dict):
                    language = self._language(migrated.get("language"))
            local = {
                "schema_version": 1,
                "language": language,
                "cached_at": time.time(),
            }
            self._atomic_write(self._path(owner), local)
        return self._public_value(local)

    def _read_local(self, principal: str) -> dict[str, Any]:
        path = self._path(principal)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    def update(self, principal: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner = self._principal(principal)
        current = self.read(owner)
        if "language" in payload:
            language = str(payload["language"] or "").strip()
            if language not in SUPPORTED_LANGUAGES:
                raise ValueError("language preference is invalid")
            current["language"] = language
        if self.control_store is not None:
            remote = self.control_store.upsert_user_preference(
                owner, language=current["language"],
            )
            if isinstance(remote, dict):
                current["language"] = self._language(remote.get("language"))
        cached = {**current, "cached_at": time.time()}
        self._atomic_write(self._path(owner), cached)
        return {
            "schema_version": 1,
            "language": current["language"],
        }

    def _cache_fresh(self, value: dict[str, Any]) -> bool:
        try:
            return time.time() - float(value.get("cached_at") or 0) < self.cache_ttl_seconds
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _language(value: object) -> str:
        language = str(value or "system")
        return language if language in SUPPORTED_LANGUAGES else "system"

    @classmethod
    def _public_value(cls, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "language": cls._language(value.get("language")),
        }

    @staticmethod
    def _principal(principal: str) -> str:
        value = str(principal or "").strip()
        if not value:
            raise ValueError("preference principal is required")
        return value

    def _path(self, principal: str) -> Path:
        value = self._principal(principal)
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    @staticmethod
    def _atomic_write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staging, path)
        finally:
            try:
                os.unlink(staging)
            except FileNotFoundError:
                pass
