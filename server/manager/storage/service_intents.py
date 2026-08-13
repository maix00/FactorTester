"""Durable desired-running state for Manager-owned execution services."""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path


SERVICE_INTENT_SCHEMA_VERSION = 1


class ServiceIntentStore:
    """Persist only services a user explicitly asked the Manager to run."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._services = self._load()

    def _load(self) -> dict[str, int]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return {}
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != SERVICE_INTENT_SCHEMA_VERSION
            or not isinstance(payload.get("services"), list)
        ):
            return {}
        services: dict[str, int] = {}
        for item in payload["services"]:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            try:
                port = int(item.get("port") or 0)
            except (TypeError, ValueError):
                continue
            if path and 1 <= port <= 65535:
                services[str(Path(path).expanduser().resolve())] = port
        return services

    def _save(self) -> None:
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        payload = {
            "schema_version": SERVICE_INTENT_SCHEMA_VERSION,
            "services": [
                {"path": path, "port": port}
                for path, port in sorted(
                    self._services.items(), key=lambda item: (item[1], item[0]),
                )
            ],
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def services(self) -> list[dict[str, object]]:
        with self._lock:
            return [
                {"path": path, "port": port}
                for path, port in sorted(
                    self._services.items(), key=lambda item: (item[1], item[0]),
                )
            ]

    def mark_running(self, path: str | Path, port: int) -> None:
        resolved = str(Path(path).expanduser().resolve())
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError("service intent port must be between 1 and 65535")
        with self._lock:
            if self._services.get(resolved) == port:
                return
            self._services[resolved] = port
            self._save()

    def mark_stopped(self, path: str | Path) -> None:
        resolved = str(Path(path).expanduser().resolve())
        with self._lock:
            if self._services.pop(resolved, None) is not None:
                self._save()
