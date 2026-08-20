"""Manager-local storage for user-owned Agent model providers.

Provider credentials are runtime-local secrets.  They never belong in the
PostgreSQL control plane or in a Profile projection.  The Manager stores an
encrypted token beside its existing local SQLite state and exposes only
non-secret metadata to the Web client.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from tools.data.sqlite.db import connect_sqlite
from server.manager.services.agent_runtime_capabilities import (
    AgentRuntimeCapabilityError,
    validate_runtime_protocol,
)


PROVIDER_TABLE = "manager_agent_provider_connections"
SUPPORTED_RUNTIME_KINDS = frozenset({"client", "server"})
SUPPORTED_NETWORK_ROUTES = frozenset({"direct", "manager_proxy"})


class ProviderStoreError(ValueError):
    """A provider connection cannot be created or used safely."""


class AgentProviderStore:
    """Persist provider metadata and encrypted tokens in local SQLite."""

    def __init__(self, db_path: str | Path, key_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.key_path = Path(key_path).expanduser().resolve()
        self._lock = threading.RLock()
        self._cipher = Fernet(self._load_key())
        self._initialize()

    def _load_key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            key = self.key_path.read_bytes().strip()
        except FileNotFoundError:
            key = Fernet.generate_key()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            try:
                descriptor = os.open(str(self.key_path), flags, 0o600)
            except FileExistsError:
                key = self.key_path.read_bytes().strip()
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(key)
                    handle.flush()
                    os.fsync(handle.fileno())
        if not key:
            raise ProviderStoreError("provider secret key is empty")
        try:
            Fernet(key)
        except (TypeError, ValueError) as exc:
            raise ProviderStoreError("provider secret key is invalid") from exc
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = connect_sqlite(self.db_path, timeout=5.0)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {PROVIDER_TABLE} (
                    provider_id TEXT PRIMARY KEY,
                    principal TEXT NOT NULL,
                    runtime_kind TEXT NOT NULL,
                    agent_runtime TEXT NOT NULL DEFAULT 'codex',
                    server_id TEXT NOT NULL DEFAULT '',
                    label TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    default_model TEXT NOT NULL DEFAULT '',
                    network_route TEXT NOT NULL DEFAULT 'direct',
                    secret_blob BLOB NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            columns = {
                str(row[1])
                for row in db.execute(
                    f"PRAGMA table_info({PROVIDER_TABLE})"
                ).fetchall()
            }
            if "agent_runtime" not in columns:
                db.execute(
                    f"ALTER TABLE {PROVIDER_TABLE} "
                    "ADD COLUMN agent_runtime TEXT NOT NULL DEFAULT 'codex'"
                )
            if "network_route" not in columns:
                db.execute(
                    f"ALTER TABLE {PROVIDER_TABLE} "
                    "ADD COLUMN network_route TEXT NOT NULL DEFAULT 'direct'"
                )
            db.execute(
                f"UPDATE {PROVIDER_TABLE} SET protocol = 'openai_responses' "
                "WHERE protocol = 'openai_compatible'"
            )
            db.execute(
                f"""CREATE INDEX IF NOT EXISTS {PROVIDER_TABLE}_owner
                    ON {PROVIDER_TABLE}(principal, runtime_kind, server_id)"""
            )

    @staticmethod
    def _text(value: object, field: str, *, required: bool = True) -> str:
        result = str(value or "").strip()
        if required and not result:
            raise ProviderStoreError(f"{field} is required")
        if len(result) > 512:
            raise ProviderStoreError(f"{field} is too long")
        return result

    @classmethod
    def validate_runtime_kind(cls, value: object) -> str:
        runtime = cls._text(value, "runtime_kind")
        if runtime not in SUPPORTED_RUNTIME_KINDS:
            raise ProviderStoreError("runtime_kind is unsupported")
        return runtime

    @classmethod
    def validate_network_route(cls, value: object) -> str:
        route = cls._text(value or "direct", "network_route")
        if route not in SUPPORTED_NETWORK_ROUTES:
            raise ProviderStoreError("network_route is unsupported")
        return route

    @classmethod
    def validate_runtime_protocol(
        cls,
        runtime: object,
        protocol: object,
    ) -> tuple[str, str]:
        try:
            return validate_runtime_protocol(runtime, protocol)
        except AgentRuntimeCapabilityError as exc:
            raise ProviderStoreError(str(exc)) from exc

    @classmethod
    def validate_base_url(cls, value: object, *, runtime_kind: str) -> str:
        base_url = cls._text(value, "base_url").rstrip("/")
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
        except ValueError as exc:
            raise ProviderStoreError("base_url is invalid") from exc
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ProviderStoreError("base_url must use http or https")
        if parsed.username or parsed.password or parsed.fragment:
            raise ProviderStoreError("base_url must not contain credentials or fragments")
        if port is not None and not 1 <= port <= 65535:
            raise ProviderStoreError("base_url port is invalid")
        hostname = parsed.hostname.lower().rstrip(".")
        if runtime_kind == "server":
            if parsed.scheme != "https":
                raise ProviderStoreError("server provider base_url must use HTTPS")
            if hostname in {"localhost", "localhost.localdomain"}:
                raise ProviderStoreError("server provider cannot target localhost")
        return base_url

    @staticmethod
    def _row(row: sqlite3.Row, *, include_secret: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "provider_id": str(row["provider_id"] or ""),
            "label": str(row["label"] or ""),
            "runtime_kind": str(row["runtime_kind"] or ""),
            "agent_runtime": str(row["agent_runtime"] or "codex"),
            "server_id": str(row["server_id"] or ""),
            "protocol": str(row["protocol"] or ""),
            "base_url": str(row["base_url"] or ""),
            "default_model": str(row["default_model"] or ""),
            "network_route": str(row["network_route"] or "direct"),
            "enabled": bool(row["enabled"]),
            "token_configured": bool(row["secret_blob"]),
            "created_at": float(row["created_at"] or 0),
            "updated_at": float(row["updated_at"] or 0),
        }
        if include_secret:
            value["secret_blob"] = bytes(row["secret_blob"] or b"")
        return value

    def list(
        self,
        principal: str,
        *,
        runtime_kind: str | None = None,
        server_id: str | None = None,
    ) -> list[dict[str, Any]]:
        owner = self._text(principal, "principal")
        clauses = ["principal = ?"]
        parameters: list[object] = [owner]
        if runtime_kind:
            clauses.append("runtime_kind = ?")
            parameters.append(self.validate_runtime_kind(runtime_kind))
        if server_id:
            clauses.append("server_id = ?")
            parameters.append(str(server_id).strip())
        with self._connection() as db:
            rows = db.execute(
                f"""SELECT * FROM {PROVIDER_TABLE}
                    WHERE {' AND '.join(clauses)}
                    ORDER BY enabled DESC, label COLLATE NOCASE, provider_id""",
                parameters,
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, principal: str, provider_id: str, *, include_secret: bool = False) -> dict[str, Any] | None:
        owner = self._text(principal, "principal")
        identifier = self._text(provider_id, "provider_id")
        with self._connection() as db:
            row = db.execute(
                f"SELECT * FROM {PROVIDER_TABLE} WHERE principal = ? AND provider_id = ?",
                (owner, identifier),
            ).fetchone()
        if row is None:
            return None
        value = self._row(row, include_secret=include_secret)
        if include_secret:
            try:
                value["secret"] = self._cipher.decrypt(value.pop("secret_blob")).decode("utf-8")
            except (InvalidToken, UnicodeDecodeError) as exc:
                raise ProviderStoreError("provider token cannot be decrypted") from exc
        return value

    def candidate(
        self,
        principal: str,
        payload: dict[str, object],
        *,
        default_server_id: str = "",
    ) -> dict[str, Any]:
        """Validate a provider without writing it to SQLite.

        This is used by the connection test so an API Key can be checked before
        the user commits the Provider record.  The returned mapping contains a
        private ``secret`` value for the immediate health check only.
        """
        owner = self._text(principal, "principal")
        if not isinstance(payload, dict):
            raise ProviderStoreError("provider must be an object")
        provider_id = str(payload.get("provider_id") or "").strip()
        previous = None
        if provider_id:
            with self._connection() as db:
                previous = db.execute(
                    f"SELECT * FROM {PROVIDER_TABLE} WHERE provider_id = ?",
                    (provider_id,),
                ).fetchone()
            if previous is not None and str(previous["principal"]) != owner:
                raise ProviderStoreError("provider does not belong to current account")
        runtime_kind = self.validate_runtime_kind(
            payload.get("runtime_kind")
            or (previous["runtime_kind"] if previous is not None else "server")
        )
        server_id = str(
            payload.get("server_id")
            or (previous["server_id"] if previous is not None else "")
            or default_server_id
        ).strip()
        if runtime_kind == "server" and not server_id:
            raise ProviderStoreError("server provider requires server_id")
        if runtime_kind == "client":
            server_id = ""
        label = self._text(
            payload.get("label")
            or (previous["label"] if previous is not None else ""),
            "label",
        )
        agent_runtime, protocol = self.validate_runtime_protocol(
            payload.get("agent_runtime")
            or (previous["agent_runtime"] if previous is not None else "codex"),
            payload.get("protocol")
            or (previous["protocol"] if previous is not None else "openai_responses"),
        )
        base_url = self.validate_base_url(
            payload.get("base_url")
            or (previous["base_url"] if previous is not None else ""),
            runtime_kind=runtime_kind,
        )
        default_model = self._text(
            payload.get("default_model")
            or (previous["default_model"] if previous is not None else ""),
            "default_model",
            required=False,
        )
        network_route = self.validate_network_route(
            payload.get("network_route")
            or (previous["network_route"] if previous is not None else "direct")
        )
        if runtime_kind == "client" and network_route != "direct":
            raise ProviderStoreError(
                "client provider cannot use the Manager network proxy"
            )
        secret = str(payload.get("token") or "").strip()
        if not secret and previous is not None:
            try:
                secret = self._cipher.decrypt(
                    bytes(previous["secret_blob"] or b""),
                ).decode("utf-8")
            except (InvalidToken, UnicodeDecodeError) as exc:
                raise ProviderStoreError("provider token cannot be decrypted") from exc
        if not secret:
            raise ProviderStoreError("token is required")
        return {
            "provider_id": provider_id,
            "principal": owner,
            "runtime_kind": runtime_kind,
            "agent_runtime": agent_runtime,
            "server_id": server_id,
            "label": label,
            "protocol": protocol,
            "base_url": base_url,
            "default_model": default_model,
            "network_route": network_route,
            "secret": secret,
            "previous": previous,
        }

    def save(
        self,
        principal: str,
        payload: dict[str, object],
        *,
        default_server_id: str = "",
    ) -> dict[str, Any]:
        candidate = self.candidate(
            principal,
            payload,
            default_server_id=default_server_id,
        )
        owner = candidate["principal"]
        provider_id = candidate["provider_id"] or "provider_" + secrets.token_urlsafe(9)
        runtime_kind = candidate["runtime_kind"]
        agent_runtime = candidate["agent_runtime"]
        server_id = candidate["server_id"]
        label = candidate["label"]
        protocol = candidate["protocol"]
        base_url = candidate["base_url"]
        default_model = candidate["default_model"]
        network_route = candidate["network_route"]
        secret = candidate["secret"]
        previous = candidate["previous"]
        now = time.time()
        with self._connection() as db:
            secret_blob = self._cipher.encrypt(secret.encode("utf-8"))
            db.execute(
                f"""INSERT INTO {PROVIDER_TABLE} (
                    provider_id, principal, runtime_kind, agent_runtime, server_id, label,
                    protocol, base_url, default_model, network_route, secret_blob, enabled,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    runtime_kind=excluded.runtime_kind,
                    agent_runtime=excluded.agent_runtime,
                    server_id=excluded.server_id,
                    label=excluded.label,
                    protocol=excluded.protocol,
                    base_url=excluded.base_url,
                    default_model=excluded.default_model,
                    network_route=excluded.network_route,
                    secret_blob=excluded.secret_blob,
                    enabled=1,
                    updated_at=excluded.updated_at""",
                (
                    provider_id, owner, runtime_kind, agent_runtime, server_id, label,
                    protocol, base_url, default_model, network_route, secret_blob,
                    now if previous is None else float(previous["created_at"] or now),
                    now,
                ),
            )
        result = self.get(owner, provider_id)
        if result is None:  # pragma: no cover - guarded by the write above
            raise ProviderStoreError("provider was not saved")
        return result

    def delete(self, principal: str, provider_id: str) -> bool:
        owner = self._text(principal, "principal")
        identifier = self._text(provider_id, "provider_id")
        with self._connection() as db:
            cursor = db.execute(
                f"DELETE FROM {PROVIDER_TABLE} WHERE principal = ? AND provider_id = ?",
                (owner, identifier),
            )
        return bool(cursor.rowcount)

    def duplicate(self, principal: str, provider_id: str) -> dict[str, Any]:
        """Copy one owned Provider without exposing its decrypted token."""
        source = self.get(principal, provider_id, include_secret=True)
        if source is None:
            raise ProviderStoreError("provider was not found")
        label = f"{source['label'][:507]} copy"
        return self.save(
            principal,
            {
                "label": label,
                "runtime_kind": source["runtime_kind"],
                "agent_runtime": source["agent_runtime"],
                "server_id": source["server_id"],
                "protocol": source["protocol"],
                "base_url": source["base_url"],
                "default_model": source["default_model"],
                "network_route": source["network_route"],
                "token": source["secret"],
            },
        )
