"""Owner-only persisted settings for a Manager's PostgreSQL control plane."""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from typing import Mapping
from urllib.parse import quote, unquote, urlencode, urlsplit, urlunsplit

from server.manager.storage.control_db import (
    CONTROL_DATABASE_ENV,
    DEFAULT_CONTROL_DATABASE_PORT,
    DEFAULT_CONTROL_DATABASE_SSLMODE,
    DEFAULT_CONTROL_DATABASE_TIMEOUT,
    ControlDatabaseConfig,
    control_database_status,
)


class ControlDatabaseSettingsStore:
    """Persist a validated URL without ever projecting its password."""

    def __init__(
        self,
        path: str | Path,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._environment = dict(os.environ if environ is None else environ)

    @property
    def environment_managed(self) -> bool:
        return bool(str(self._environment.get(CONTROL_DATABASE_ENV) or "").strip())

    def _stored_url(self) -> str:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return ""
        if not isinstance(value, dict):
            return ""
        return str(value.get("url") or "").strip()

    def effective_url(self) -> str:
        configured = str(
            self._environment.get(CONTROL_DATABASE_ENV) or ""
        ).strip()
        return configured or self._stored_url()

    def effective_environ(self) -> dict[str, str]:
        values = dict(self._environment)
        effective = self.effective_url()
        if effective:
            values[CONTROL_DATABASE_ENV] = effective
        else:
            values.pop(CONTROL_DATABASE_ENV, None)
        return values

    def status(self) -> dict[str, object]:
        values = self.effective_environ()
        result = control_database_status(values)
        raw = str(values.get(CONTROL_DATABASE_ENV) or "").strip()
        parsed = urlsplit(raw) if raw else None
        return {
            **result,
            "managed_by": (
                "environment"
                if self.environment_managed
                else "settings" if raw else "none"
            ),
            "user": unquote(parsed.username or "") if parsed else "",
            "password_configured": bool(parsed and parsed.password),
        }

    def candidate(self, payload: dict[str, object]) -> ControlDatabaseConfig:
        if self.environment_managed:
            raise PermissionError("control database is managed by the server environment")
        if not isinstance(payload, dict):
            raise ValueError("control database settings must be an object")
        allowed = {
            "host", "port", "database", "user", "password",
            "sslmode", "connect_timeout",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(
                "unknown control database fields: " + ", ".join(unknown)
            )

        existing_raw = self._stored_url()
        existing = urlsplit(existing_raw) if existing_raw else None
        host = str(
            payload.get("host")
            or (existing.hostname if existing else "")
        ).strip()
        database = str(
            payload.get("database")
            or (unquote(existing.path.lstrip("/")) if existing else "")
        ).strip()
        user = str(
            payload.get("user")
            or (unquote(existing.username or "") if existing else "")
        ).strip()
        supplied_password = str(payload.get("password") or "")
        password = supplied_password or (
            unquote(existing.password or "") if existing else ""
        )
        host = host.removeprefix("[").removesuffix("]")
        if not host or not re.fullmatch(r"[A-Za-z0-9._:-]+", host):
            raise ValueError("control database host is required")
        if not database:
            raise ValueError("control database name is required")
        if not user:
            raise ValueError("control database user is required")
        if not password:
            raise ValueError("control database password is required")

        raw_port = payload.get("port")
        port = int(
            raw_port
            or (existing.port if existing else DEFAULT_CONTROL_DATABASE_PORT)
        )
        sslmode = str(
            payload.get("sslmode")
            or (
                dict(
                    item.split("=", 1)
                    for item in existing.query.split("&")
                    if "=" in item
                ).get("sslmode")
                if existing else ""
            )
            or DEFAULT_CONTROL_DATABASE_SSLMODE
        ).strip().lower()
        connect_timeout = int(
            payload.get("connect_timeout") or DEFAULT_CONTROL_DATABASE_TIMEOUT
        )
        encoded_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        netloc = (
            f"{quote(user, safe='')}:{quote(password, safe='')}"
            f"@{encoded_host}:{port}"
        )
        url = urlunsplit((
            "postgresql",
            netloc,
            "/" + quote(database, safe=""),
            urlencode({
                "sslmode": sslmode,
                "connect_timeout": connect_timeout,
            }),
            "",
        ))
        return ControlDatabaseConfig.from_url(url)

    def save(self, config: ControlDatabaseConfig) -> None:
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        temporary.write_text(
            json.dumps(
                {"schema_version": 1, "url": config.url},
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
