"""Small owner-scoped FTClient preferences stored by Manager 7998."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SUPPORTED_LANGUAGES = {"system", "zh-Hans", "en"}


class UserPreferenceStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, principal: str) -> dict[str, Any]:
        path = self._path(principal)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            value = {}
        language = str(value.get("language") or "system")
        if language not in SUPPORTED_LANGUAGES:
            language = "system"
        return {"schema_version": 1, "language": language}

    def update(self, principal: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.read(principal)
        if "language" in payload:
            language = str(payload["language"] or "").strip()
            if language not in SUPPORTED_LANGUAGES:
                raise ValueError("language preference is invalid")
            current["language"] = language
        self._atomic_write(self._path(principal), current)
        return current

    def _path(self, principal: str) -> Path:
        value = str(principal or "").strip()
        if not value:
            raise ValueError("preference principal is required")
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
