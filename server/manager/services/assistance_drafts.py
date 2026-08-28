"""Flat, retained page-assistance drafts inside one Profile workspace."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

ASSISTANCE_DRAFT_RELATIVE_ROOT = Path("manifests/assistance-drafts")
_DRAFT_ID = re.compile(r"^[0-9a-f]{32}$")
_STATUSES = frozenset({"draft", "validated", "applied", "rejected"})


class AssistanceDraftError(ValueError):
    """A draft operation is invalid or exceeds its Profile boundary."""


def _canonical(document: object) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _slug(value: object, fallback: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return (result or fallback)[:48]


class AssistanceDraftStore:
    def __init__(
        self,
        workspace_root: str | Path,
        *,
        quota_bytes: int = 100 * 1024 * 1024,
        warning_ratio: float = 0.8,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.root = self.workspace_root / ASSISTANCE_DRAFT_RELATIVE_ROOT
        self.quota_bytes = max(1024, int(quota_bytes))
        self.warning_ratio = max(0.1, min(float(warning_ratio), 1.0))
        self._lock = RLock()

    def _ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _files(self) -> list[Path]:
        self._ensure()
        return sorted(self.root.glob("*.json"), reverse=True)

    def usage(self) -> dict[str, Any]:
        with self._lock:
            files = self._files()
            used = sum(path.stat().st_size for path in files if path.is_file())
            return {
                "used_bytes": used,
                "quota_bytes": self.quota_bytes,
                "warning": used >= int(self.quota_bytes * self.warning_ratio),
                "count": len(files),
            }

    def _path(self, draft_id: str) -> Path:
        identifier = str(draft_id or "").strip().lower()
        if not _DRAFT_ID.fullmatch(identifier):
            raise AssistanceDraftError("assistance draft identifier is invalid")
        matches = (
            list(self.root.glob(f"*-{identifier}.json")) if self.root.exists() else []
        )
        if len(matches) != 1:
            raise AssistanceDraftError("assistance draft was not found")
        return matches[0]

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssistanceDraftError("assistance draft is invalid") from exc
        if not isinstance(value, dict):
            raise AssistanceDraftError("assistance draft is invalid")
        return value

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def create(
        self,
        *,
        principal: str,
        profile_id: str,
        tab_id: str,
        page_kind: str,
        page_revision: int,
        schema_version: int,
        document: dict[str, Any],
        conversation_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure()
            encoded = _canonical(document)
            now = datetime.now().astimezone()
            draft_id = uuid.uuid4().hex
            timestamp = now.strftime("%Y%m%dT%H%M%S%z")
            filename = (
                "-".join(
                    (
                        timestamp,
                        _slug(page_kind, "page"),
                        _slug(tab_id, "tab"),
                        f"r{max(0, int(page_revision))}",
                        draft_id,
                    )
                )
                + ".json"
            )
            value = {
                "schema_version": 1,
                "draft_id": draft_id,
                "status": "draft",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "principal": str(principal),
                "profile_id": str(profile_id),
                "conversation_id": str(conversation_id),
                "session_id": str(session_id),
                "tab_id": str(tab_id),
                "page_kind": str(page_kind),
                "document_schema_version": int(schema_version),
                "page_revision": int(page_revision),
                "content_sha256": hashlib.sha256(encoded).hexdigest(),
                "content_summary": {
                    "keys": sorted(document)[:32],
                    "size_bytes": len(encoded),
                },
                "document": document,
                "application": None,
            }
            stored_size = (
                len(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")) + 1
            )
            usage = self.usage()
            if usage["used_bytes"] + stored_size > self.quota_bytes:
                raise AssistanceDraftError(
                    "Profile assistance draft quota is full; delete retained drafts first"
                )
            self._write(self.root / filename, value)
            value["workspace_path"] = str(ASSISTANCE_DRAFT_RELATIVE_ROOT / filename)
            value["quota"] = self.usage()
            return value

    def list(self) -> dict[str, Any]:
        with self._lock:
            items = []
            for path in self._files():
                value = self._read(path)
                value.pop("document", None)
                value["workspace_path"] = str(
                    ASSISTANCE_DRAFT_RELATIVE_ROOT / path.name
                )
                items.append(value)
            return {"drafts": items, "quota": self.usage()}

    def get(self, draft_id: str) -> dict[str, Any]:
        with self._lock:
            path = self._path(draft_id)
            value = self._read(path)
            value["workspace_path"] = str(ASSISTANCE_DRAFT_RELATIVE_ROOT / path.name)
            return value

    def set_status(
        self,
        draft_id: str,
        status: str,
        *,
        error: str = "",
        run_spec_ref: str = "",
        applied_revision: int | None = None,
    ) -> dict[str, Any]:
        normalized = str(status or "").strip()
        if normalized not in _STATUSES:
            raise AssistanceDraftError("assistance draft status is invalid")
        with self._lock:
            path = self._path(draft_id)
            value = self._read(path)
            now = datetime.now().astimezone().isoformat()
            value["status"] = normalized
            value["updated_at"] = now
            value["application"] = {
                "at": now,
                "error": str(error),
                "run_spec_ref": str(run_spec_ref),
                "applied_revision": applied_revision,
            }
            self._write(path, value)
            value["workspace_path"] = str(ASSISTANCE_DRAFT_RELATIVE_ROOT / path.name)
            return value

    def delete(self, draft_id: str) -> bool:
        with self._lock:
            self._path(draft_id).unlink()
            return True


__all__ = [
    "ASSISTANCE_DRAFT_RELATIVE_ROOT",
    "AssistanceDraftError",
    "AssistanceDraftStore",
]
