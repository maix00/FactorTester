"""PostgreSQL control-plane storage for users, profiles, and global quotas.

The execution and artifact databases remain host-local SQLite databases.  This
module contains only the small pieces of state that must be authoritative when
more than one Manager can authenticate a user or accept a task: account
records, profile metadata, quota policies, per-server usage snapshots, and
short-lived quota reservations.

The driver is intentionally imported lazily.  A developer checkout without a
``FACTORTESTER_CONTROL_DATABASE_URL`` keeps using the existing SQLite account
store and local artifact quota, while a deployed node with the URL configured
uses the remote PostgreSQL database over TCP (5432 by default).
"""

from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import parse_qs, urlsplit, urlunsplit

from server.manager.domain.devices import PUBLIC_DEVICE_LIMIT


CONTROL_DATABASE_ENV = "FACTORTESTER_CONTROL_DATABASE_URL"
DEFAULT_CONTROL_DATABASE_PORT = 5432
DEFAULT_CONTROL_DATABASE_SSLMODE = "require"
DEFAULT_CONTROL_DATABASE_TIMEOUT = 5
CONTROL_DATABASE_SCHEMA_VERSION = 4
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ControlDatabaseError(RuntimeError):
    """Base error for control-database configuration or availability."""


class ControlDatabaseConfigurationError(ControlDatabaseError, ValueError):
    """The configured PostgreSQL URL is not safe or internally consistent."""


class ControlDatabaseUnavailable(ControlDatabaseError):
    """The PostgreSQL driver or remote database is unavailable."""


@dataclass(frozen=True, slots=True)
class ControlDatabaseConfig:
    """Validated connection settings for the remote control database."""

    url: str
    host: str
    port: int
    database: str
    user: str
    sslmode: str = DEFAULT_CONTROL_DATABASE_SSLMODE
    connect_timeout: int = DEFAULT_CONTROL_DATABASE_TIMEOUT

    @classmethod
    def from_url(cls, value: str) -> "ControlDatabaseConfig":
        raw = str(value or "").strip()
        parsed = urlsplit(raw)
        if parsed.scheme not in {"postgresql", "postgres"}:
            raise ControlDatabaseConfigurationError(
                "control database URL must use the postgresql:// scheme"
            )
        if not parsed.hostname:
            raise ControlDatabaseConfigurationError(
                "control database URL must include a remote host"
            )
        try:
            port = int(parsed.port or DEFAULT_CONTROL_DATABASE_PORT)
        except ValueError as exc:
            raise ControlDatabaseConfigurationError(
                "control database port must be an integer"
            ) from exc
        if not 1 <= port <= 65535:
            raise ControlDatabaseConfigurationError(
                "control database port must be between 1 and 65535"
            )
        database = parsed.path.lstrip("/").strip()
        if not database:
            raise ControlDatabaseConfigurationError(
                "control database URL must include a database name"
            )
        query = parse_qs(parsed.query, keep_blank_values=True)
        sslmode = str(
            (query.get("sslmode") or [DEFAULT_CONTROL_DATABASE_SSLMODE])[0]
            or DEFAULT_CONTROL_DATABASE_SSLMODE
        ).strip().lower()
        if sslmode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
            raise ControlDatabaseConfigurationError(
                "control database sslmode is invalid"
            )
        raw_timeout = str(
            (query.get("connect_timeout") or [DEFAULT_CONTROL_DATABASE_TIMEOUT])[0]
            or DEFAULT_CONTROL_DATABASE_TIMEOUT
        )
        try:
            connect_timeout = int(raw_timeout)
        except ValueError as exc:
            raise ControlDatabaseConfigurationError(
                "control database connect_timeout must be an integer"
            ) from exc
        if not 1 <= connect_timeout <= 120:
            raise ControlDatabaseConfigurationError(
                "control database connect_timeout must be between 1 and 120"
            )
        return cls(
            url=raw,
            host=str(parsed.hostname),
            port=port,
            database=database,
            user=str(parsed.username or ""),
            sslmode=sslmode,
            connect_timeout=connect_timeout,
        )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ControlDatabaseConfig | None":
        values = os.environ if environ is None else environ
        raw = str(values.get(CONTROL_DATABASE_ENV) or "").strip()
        return cls.from_url(raw) if raw else None

    @property
    def redacted_url(self) -> str:
        """Return a log-safe URL while retaining the explicit database port."""
        parsed = urlsplit(self.url)
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        user = f"{parsed.username}:***@" if parsed.username else ""
        netloc = f"{user}{host}:{self.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    @property
    def connect_kwargs(self) -> dict[str, object]:
        return {
            "connect_timeout": self.connect_timeout,
            "sslmode": self.sslmode,
        }


def quota_decision(
    *,
    current_bytes: int,
    requested_bytes: int,
    quota_bytes: int,
) -> dict[str, int | bool]:
    """Evaluate one quota reservation without performing I/O.

    ``current_bytes`` includes already retained bytes and reservations held by
    other tasks.  ``remaining_bytes`` deliberately reports the space that was
    available before this request, which is useful to render a denial without
    exposing a negative value.
    """
    current = max(0, int(current_bytes))
    requested = max(0, int(requested_bytes))
    quota = max(0, int(quota_bytes))
    projected = current + requested
    return {
        "allowed": projected <= quota,
        "projected_bytes": projected,
        "remaining_bytes": max(0, quota - current),
    }


def git_source_version(
    *,
    source_id: str,
    principal: str,
    profile_id: str = "",
    source_kind: str,
    repository_ref: str = "",
    relative_path: str = "",
    branch_ref: str = "",
    commit_sha: str,
    tree_hash: str = "",
    blob_hash: str = "",
    content_hash: str,
    snapshot_ref: str = "",
    storage_server_id: str = "",
    size_bytes: int = 0,
    dirty: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an immutable source identity for a factor or strategy input.

    A branch/ref is descriptive and may move.  The full commit SHA plus the
    content hash are the version key.  Dirty workspaces must provide a
    snapshot reference so a task can be reproduced after the local checkout
    changes.
    """
    source_key = str(source_id or "").strip()
    owner = str(principal or "").strip()
    kind = str(source_kind or "").strip()
    commit = str(commit_sha or "").strip().lower()
    content = str(content_hash or "").strip().lower()
    if not source_key:
        raise ValueError("source_id is required")
    if not owner:
        raise ValueError("principal is required")
    if not kind:
        raise ValueError("source_kind is required")
    if not _GIT_SHA_RE.fullmatch(commit):
        raise ValueError("commit_sha must be a full Git commit SHA")
    if not _CONTENT_HASH_RE.fullmatch(content):
        raise ValueError("content_hash must be a SHA-256 hash")
    for field, value in (("tree_hash", tree_hash), ("blob_hash", blob_hash)):
        normalized = str(value or "").strip().lower()
        if normalized and not _GIT_SHA_RE.fullmatch(normalized):
            raise ValueError(f"{field} must be a Git object SHA")
    snapshot = str(snapshot_ref or "").strip()
    if dirty and not snapshot:
        raise ValueError("dirty source requires snapshot_ref")
    version_id = f"{commit}:{content}"
    return {
        "source_id": source_key,
        "version_id": version_id,
        "principal": owner,
        "profile_id": str(profile_id or "").strip(),
        "source_kind": kind,
        "repository_ref": str(repository_ref or "").strip(),
        "relative_path": str(relative_path or "").strip(),
        "branch_ref": str(branch_ref or "").strip(),
        "commit_sha": commit,
        "tree_hash": str(tree_hash or "").strip().lower(),
        "blob_hash": str(blob_hash or "").strip().lower(),
        "content_hash": content,
        "snapshot_ref": snapshot,
        "storage_server_id": str(storage_server_id or "").strip(),
        "size_bytes": max(0, int(size_bytes)),
        "dirty": bool(dirty),
        "metadata": dict(metadata or {}),
    }


CONTROL_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS control_schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_organizations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_levels (
        id TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        parent_level_id TEXT NOT NULL DEFAULT '',
        manager_username TEXT NOT NULL DEFAULT '',
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (organization_id) REFERENCES control_organizations(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS control_levels_organization ON control_levels(organization_id, id)",
    "CREATE INDEX IF NOT EXISTS control_levels_parent ON control_levels(organization_id, parent_level_id)",
    """
    CREATE TABLE IF NOT EXISTS control_users (
        username TEXT PRIMARY KEY,
        alias TEXT NOT NULL DEFAULT '',
        salt TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT 'user',
        is_admin BOOLEAN NOT NULL DEFAULT FALSE,
        is_developer BOOLEAN NOT NULL DEFAULT FALSE,
        organization_id TEXT NOT NULL DEFAULT 'default',
        organization_name TEXT NOT NULL DEFAULT '',
        level_id TEXT NOT NULL DEFAULT '',
        parent_username TEXT NOT NULL DEFAULT '',
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_devices (
        device_id TEXT PRIMARY KEY,
        public_key JSONB NOT NULL,
        username TEXT NOT NULL,
        device_name TEXT NOT NULL DEFAULT '',
        client_type TEXT NOT NULL DEFAULT 'unknown',
        client_name TEXT NOT NULL DEFAULT '',
        enrollment_ip TEXT NOT NULL DEFAULT '',
        last_seen_ip TEXT NOT NULL DEFAULT '',
        public_access BOOLEAN NOT NULL DEFAULT FALSE,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        source_server_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TIMESTAMPTZ
    )
    """,
    "ALTER TABLE control_devices ADD COLUMN IF NOT EXISTS public_access BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE control_devices ADD COLUMN IF NOT EXISTS client_type TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE control_devices ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control_devices ADD COLUMN IF NOT EXISTS enrollment_ip TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control_devices ADD COLUMN IF NOT EXISTS last_seen_ip TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS control_devices_username ON control_devices(username, enabled)",
    "CREATE INDEX IF NOT EXISTS control_devices_public_username ON control_devices(username, public_access, enabled)",
    "CREATE INDEX IF NOT EXISTS control_devices_source ON control_devices(source_server_id, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS control_device_authorizations (
        token_hash TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        target_server_id TEXT NOT NULL,
        target_endpoint TEXT NOT NULL,
        device_name TEXT NOT NULL DEFAULT '',
        source_server_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS control_device_authorizations_target ON control_device_authorizations(target_server_id, expires_at)",
    "CREATE INDEX IF NOT EXISTS control_device_authorizations_user ON control_device_authorizations(username, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS control_profiles (
        principal TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (principal, profile_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_versions (
        source_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        principal TEXT NOT NULL,
        profile_id TEXT NOT NULL DEFAULT '',
        source_kind TEXT NOT NULL,
        repository_ref TEXT NOT NULL DEFAULT '',
        relative_path TEXT NOT NULL DEFAULT '',
        branch_ref TEXT NOT NULL DEFAULT '',
        commit_sha TEXT NOT NULL,
        tree_hash TEXT NOT NULL DEFAULT '',
        blob_hash TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL,
        snapshot_ref TEXT NOT NULL DEFAULT '',
        storage_server_id TEXT NOT NULL DEFAULT '',
        size_bytes BIGINT NOT NULL DEFAULT 0,
        dirty BOOLEAN NOT NULL DEFAULT FALSE,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (source_id, version_id),
        CHECK (size_bytes >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS source_versions_principal ON source_versions(principal, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS source_versions_commit ON source_versions(commit_sha)",
    """
    CREATE TABLE IF NOT EXISTS quota_policies (
        principal TEXT PRIMARY KEY,
        storage_quota_bytes BIGINT NOT NULL DEFAULT 0,
        max_concurrent_tasks INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK (storage_quota_bytes >= 0),
        CHECK (max_concurrent_tasks >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quota_server_usage (
        server_id TEXT NOT NULL,
        principal TEXT NOT NULL,
        artifact_bytes BIGINT NOT NULL DEFAULT 0,
        input_bytes BIGINT NOT NULL DEFAULT 0,
        output_bytes BIGINT NOT NULL DEFAULT 0,
        artifact_count BIGINT NOT NULL DEFAULT 0,
        input_count BIGINT NOT NULL DEFAULT 0,
        output_count BIGINT NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (server_id, principal),
        CHECK (artifact_bytes >= 0),
        CHECK (input_bytes >= 0),
        CHECK (output_bytes >= 0),
        CHECK (artifact_count >= 0),
        CHECK (input_count >= 0),
        CHECK (output_count >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quota_reservations (
        task_id TEXT PRIMARY KEY,
        principal TEXT NOT NULL,
        requested_bytes BIGINT NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'reserved',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        settled_at TIMESTAMPTZ,
        CHECK (requested_bytes >= 0),
        CHECK (status IN ('reserved', 'settled', 'released'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS quota_server_usage_principal ON quota_server_usage(principal)",
    "CREATE INDEX IF NOT EXISTS quota_reservations_principal_status ON quota_reservations(principal, status)",
    "ALTER TABLE quota_server_usage ADD COLUMN IF NOT EXISTS artifact_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE quota_server_usage ADD COLUMN IF NOT EXISTS input_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE quota_server_usage ADD COLUMN IF NOT EXISTS output_count BIGINT NOT NULL DEFAULT 0",
)


def _row_value(row: object, key: str, index: int = 0, default: object = None) -> object:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[index]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return default


ConnectFactory = Callable[[ControlDatabaseConfig], Any]


class PostgresControlStore:
    """Small PostgreSQL repository with lazy connections and idempotent writes."""

    def __init__(
        self,
        config: ControlDatabaseConfig,
        *,
        connect_factory: ConnectFactory | None = None,
    ) -> None:
        self.config = config
        self._connect_factory = connect_factory
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _connect(self) -> Any:
        if self._connect_factory is not None:
            try:
                return self._connect_factory(self.config)
            except ControlDatabaseError:
                raise
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise ControlDatabaseUnavailable(
                    f"control database {self.config.redacted_url} is unavailable"
                ) from exc
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise ControlDatabaseUnavailable(
                "psycopg is not installed; install deploy/requirements-linux.txt"
            ) from exc
        try:
            return psycopg.connect(
                self.config.url,
                row_factory=dict_row,
                **self.config.connect_kwargs,
            )
        except Exception as exc:  # pragma: no cover - requires a live database
            raise ControlDatabaseUnavailable(
                f"control database {self.config.redacted_url} is unavailable"
            ) from exc

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        except ControlDatabaseError:
            raise
        except Exception as exc:
            raise ControlDatabaseUnavailable(
                f"control database {self.config.redacted_url} request failed"
            ) from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connection() as connection:
                for statement in CONTROL_SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO control_schema_migrations(version)
                    VALUES (%s)
                    ON CONFLICT(version) DO NOTHING
                    """,
                    (CONTROL_DATABASE_SCHEMA_VERSION,),
                )
            self._schema_ready = True

    def load_accounts(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT username, alias, salt, password_hash AS hash, role,
                       is_admin, is_developer, organization_id,
                       organization_name, level_id, parent_username,
                       updated_at
                FROM control_users
                WHERE active=TRUE
                ORDER BY username
                """
            ).fetchall()
        return [dict(row) if isinstance(row, Mapping) else {
            "username": _row_value(row, "username", 0, ""),
            "alias": _row_value(row, "alias", 1, ""),
            "salt": _row_value(row, "salt", 2, ""),
            "hash": _row_value(row, "hash", 3, ""),
            "role": _row_value(row, "role", 4, "user"),
            "is_admin": _row_value(row, "is_admin", 5, False),
            "is_developer": _row_value(row, "is_developer", 6, False),
            "organization_id": _row_value(row, "organization_id", 7, "default"),
            "organization_name": _row_value(row, "organization_name", 8, ""),
            "level_id": _row_value(row, "level_id", 9, ""),
            "parent_username": _row_value(row, "parent_username", 10, ""),
            "updated_at": _row_value(row, "updated_at", 11, None),
        } for row in rows]

    def replace_accounts(self, accounts: list[Mapping[str, Any]]) -> None:
        self.ensure_schema()
        with self._connection() as connection:
            connection.execute("UPDATE control_users SET active=FALSE, updated_at=CURRENT_TIMESTAMP")
            for account in accounts:
                username = str(account.get("username") or "").strip()
                if not username:
                    continue
                connection.execute(
                    """
                    INSERT INTO control_users(
                        username, alias, salt, password_hash, role,
                        is_admin, is_developer, organization_id,
                        organization_name, level_id, parent_username, active,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                    ON CONFLICT(username) DO UPDATE SET
                        alias=EXCLUDED.alias, salt=EXCLUDED.salt,
                        password_hash=EXCLUDED.password_hash,
                        role=EXCLUDED.role, is_admin=EXCLUDED.is_admin,
                        is_developer=EXCLUDED.is_developer,
                        organization_id=EXCLUDED.organization_id,
                        organization_name=EXCLUDED.organization_name,
                        level_id=EXCLUDED.level_id,
                        parent_username=EXCLUDED.parent_username,
                        active=TRUE, updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        username,
                        str(account.get("alias") or ""),
                        str(account.get("salt") or ""),
                        str(account.get("hash") or ""),
                        str(account.get("role") or "user"),
                        bool(account.get("is_admin")),
                        bool(account.get("is_developer")),
                        str(account.get("organization_id") or "default"),
                        str(account.get("organization_name") or ""),
                        str(account.get("level_id") or ""),
                        str(account.get("parent_username") or ""),
                    ),
                )

    @staticmethod
    def _device_value(row: object, *, fallback_username: str = "") -> dict[str, Any]:
        value = dict(row) if isinstance(row, Mapping) else {
            "device_id": _row_value(row, "device_id", 0, ""),
            "public_key": _row_value(row, "public_key", 1, {}),
            "username": _row_value(row, "username", 2, fallback_username),
            "device_name": _row_value(row, "device_name", 3, ""),
            "client_type": _row_value(row, "client_type", 4, "unknown"),
            "client_name": _row_value(row, "client_name", 5, ""),
            "enrollment_ip": _row_value(row, "enrollment_ip", 6, ""),
            "last_seen_ip": _row_value(row, "last_seen_ip", 7, ""),
            "public_access": _row_value(row, "public_access", 8, False),
            "enabled": _row_value(row, "enabled", 9, False),
            "source_server_id": _row_value(row, "source_server_id", 10, ""),
            "created_at": _row_value(row, "created_at", 11, None),
            "updated_at": _row_value(row, "updated_at", 12, None),
            "last_seen_at": _row_value(row, "last_seen_at", 13, None),
        }
        public_key = value.get("public_key")
        if isinstance(public_key, str):
            try:
                public_key = json.loads(public_key)
            except (TypeError, ValueError, json.JSONDecodeError):
                public_key = {}
        value["public_key"] = public_key if isinstance(public_key, dict) else {}
        for key in ("created_at", "updated_at", "last_seen_at"):
            timestamp = value.get(key)
            if hasattr(timestamp, "isoformat"):
                value[key] = timestamp.isoformat()
        return value

    def enroll_device(
        self,
        *,
        device_id: str,
        public_key: Mapping[str, Any],
        username: str,
        device_name: str = "",
        source_server_id: str,
        public_access: bool = False,
        client_type: str = "unknown",
        client_name: str = "",
        enrollment_ip: str = "",
    ) -> dict[str, Any]:
        """Register one browser public key in the central control database."""
        self.ensure_schema()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT 1 FROM control_devices WHERE device_id=%s",
                (str(device_id),),
            ).fetchone()
            if existing is not None:
                raise ValueError("device_id is already registered")
            if public_access:
                # All public-device enrollments for an account serialize on
                # the same transaction-level advisory lock.  The count and
                # insert therefore remain atomic across every Manager using
                # this PostgreSQL control plane.
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"factortester:public-device:{username}",),
                )
                count_row = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM control_devices
                    WHERE username=%s AND public_access=TRUE AND enabled=TRUE
                    """,
                    (str(username),),
                ).fetchone()
                count = int(_row_value(count_row, "count", 0, 0))
                if count >= PUBLIC_DEVICE_LIMIT:
                    raise ValueError("public device limit reached")
            row = connection.execute(
                """
                INSERT INTO control_devices(
                    device_id, public_key, username, device_name,
                    client_type, client_name, enrollment_ip, last_seen_ip,
                    public_access, enabled, source_server_id, updated_at
                ) VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s,
                          %s, TRUE, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(device_id) DO NOTHING
                RETURNING device_id, public_key, username, device_name,
                          client_type, client_name, enrollment_ip, last_seen_ip,
                          public_access, enabled, source_server_id,
                          created_at, updated_at, last_seen_at
                """,
                (
                    str(device_id), json.dumps(dict(public_key), ensure_ascii=False),
                    str(username), str(device_name or "")[:128],
                    str(client_type or "unknown")[:32],
                    str(client_name or "")[:128],
                    str(enrollment_ip or "")[:45],
                    str(enrollment_ip or "")[:45],
                    bool(public_access), str(source_server_id),
                ),
            ).fetchone()
        if row is None:
            raise ValueError("device_id is already registered")
        return self._device_value(row, fallback_username=str(username))

    def device(self, device_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT device_id, public_key, username, device_name,
                       client_type, client_name, enrollment_ip, last_seen_ip,
                       public_access, enabled, source_server_id,
                       created_at, updated_at, last_seen_at
                FROM control_devices WHERE device_id=%s
                """,
                (str(device_id),),
            ).fetchone()
        return None if row is None else self._device_value(row)

    def list_devices(
        self,
        *,
        username: str = "",
        include_disabled: bool = True,
    ) -> list[dict[str, Any]]:
        self.ensure_schema()
        predicates = []
        parameters: list[Any] = []
        owner = str(username or "").strip()
        if owner:
            predicates.append("username=%s")
            parameters.append(owner)
        if not include_disabled:
            predicates.append("enabled=TRUE")
        where = " WHERE " + " AND ".join(predicates) if predicates else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT device_id, public_key, username, device_name,
                       client_type, client_name, enrollment_ip, last_seen_ip,
                       public_access, enabled, source_server_id,
                       created_at, updated_at, last_seen_at
                FROM control_devices{where}
                ORDER BY username, device_name, device_id
                """,
                tuple(parameters),
            ).fetchall()
        return [self._device_value(row) for row in rows]

    def revoke_device(self, device_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE control_devices
                SET enabled=FALSE, updated_at=CURRENT_TIMESTAMP
                WHERE device_id=%s
                RETURNING device_id, public_key, username, device_name,
                          client_type, client_name, enrollment_ip, last_seen_ip,
                          public_access, enabled, source_server_id,
                          created_at, updated_at, last_seen_at
                """,
                (str(device_id),),
            ).fetchone()
        return None if row is None else self._device_value(row)

    def touch_device(self, device_id: str, *, last_seen_ip: str = "") -> None:
        self.ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE control_devices
                SET last_seen_at=CURRENT_TIMESTAMP,
                    last_seen_ip=CASE WHEN %s='' THEN last_seen_ip ELSE %s END,
                    updated_at=CURRENT_TIMESTAMP
                WHERE device_id=%s AND enabled=TRUE
                """,
                (
                    str(last_seen_ip or "")[:45],
                    str(last_seen_ip or "")[:45],
                    str(device_id),
                ),
            )

    def public_device_count(self, *, username: str = "") -> int:
        self.ensure_schema()
        predicates = ["public_access=TRUE", "enabled=TRUE"]
        parameters: list[Any] = []
        owner = str(username or "").strip()
        if owner:
            predicates.append("username=%s")
            parameters.append(owner)
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM control_devices WHERE {' AND '.join(predicates)}",
                tuple(parameters),
            ).fetchone()
        return int(_row_value(row, "count", 0, 0))

    def public_device_user_count(self) -> int:
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(DISTINCT username) AS count
                FROM control_devices
                WHERE public_access=TRUE AND enabled=TRUE
                """
            ).fetchone()
        return int(_row_value(row, "count", 0, 0))

    @staticmethod
    def _device_authorization_value(row: object) -> dict[str, Any]:
        value = dict(row) if isinstance(row, Mapping) else {
            "username": _row_value(row, "username", 0, ""),
            "target_server_id": _row_value(row, "target_server_id", 1, ""),
            "target_endpoint": _row_value(row, "target_endpoint", 2, ""),
            "device_name": _row_value(row, "device_name", 3, ""),
            "source_server_id": _row_value(row, "source_server_id", 4, ""),
            "created_at": _row_value(row, "created_at", 5, None),
            "expires_at": _row_value(row, "expires_at", 6, None),
            "used_at": _row_value(row, "used_at", 7, None),
        }
        for key in ("created_at", "expires_at", "used_at"):
            timestamp = value.get(key)
            if hasattr(timestamp, "isoformat"):
                value[key] = timestamp.isoformat()
        return value

    def create_device_authorization(
        self,
        *,
        token_hash: str,
        username: str,
        target_server_id: str,
        target_endpoint: str,
        device_name: str = "",
        expires_at: float,
        source_server_id: str,
    ) -> None:
        """Persist only a hash for a short-lived public-device grant."""
        self.ensure_schema()
        expiration = datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO control_device_authorizations(
                    token_hash, username, target_server_id, target_endpoint,
                    device_name, source_server_id, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(token_hash), str(username), str(target_server_id),
                    str(target_endpoint), str(device_name or "")[:128],
                    str(source_server_id), expiration,
                ),
            )

    def consume_device_authorization(
        self,
        *,
        token_hash: str,
        target_server_id: str,
    ) -> dict[str, Any] | None:
        """Atomically validate and consume a grant on its target Manager."""
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT username, target_server_id, target_endpoint, device_name,
                       source_server_id, created_at, expires_at, used_at
                FROM control_device_authorizations
                WHERE token_hash=%s
                FOR UPDATE
                """,
                (str(token_hash),),
            ).fetchone()
            if row is None:
                return None
            value = self._device_authorization_value(row)
            if (
                value.get("used_at") is not None
                or str(value.get("target_server_id") or "") != str(target_server_id)
            ):
                return None
            # Keep the expiry check in PostgreSQL so all Managers agree on
            # the same clock and a slow client cannot redeem an old grant.
            updated = connection.execute(
                """
                UPDATE control_device_authorizations
                SET used_at=CURRENT_TIMESTAMP
                WHERE token_hash=%s AND used_at IS NULL
                  AND target_server_id=%s AND expires_at>CURRENT_TIMESTAMP
                RETURNING username, target_server_id, target_endpoint,
                          device_name, source_server_id, created_at,
                          expires_at, used_at
                """,
                (str(token_hash), str(target_server_id)),
            ).fetchone()
            if updated is None:
                return None
        return self._device_authorization_value(updated)

    def load_organizations(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, name, description, updated_at
                FROM control_organizations WHERE active=TRUE ORDER BY id
                """
            ).fetchall()
        return [dict(row) if isinstance(row, Mapping) else {
            "id": _row_value(row, "id", 0, ""),
            "name": _row_value(row, "name", 1, ""),
            "description": _row_value(row, "description", 2, ""),
            "updated_at": _row_value(row, "updated_at", 3, None),
        } for row in rows]

    def replace_organizations(
        self,
        organizations: list[Mapping[str, Any]],
    ) -> None:
        self.ensure_schema()
        with self._connection() as connection:
            connection.execute(
                "UPDATE control_organizations SET active=FALSE, updated_at=CURRENT_TIMESTAMP"
            )
            for organization in organizations:
                organization_id = str(
                    organization.get("id") or organization.get("organization_id") or ""
                ).strip()
                if not organization_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO control_organizations(id, name, description, active, updated_at)
                    VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                        name=EXCLUDED.name,
                        description=EXCLUDED.description,
                        active=TRUE,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        organization_id,
                        str(organization.get("name") or organization.get("organization_name") or ""),
                        str(organization.get("description") or ""),
                    ),
                )

    def load_levels(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, organization_id, name, parent_level_id,
                       manager_username, updated_at
                FROM control_levels WHERE active=TRUE
                ORDER BY organization_id, id
                """
            ).fetchall()
        return [dict(row) if isinstance(row, Mapping) else {
            "id": _row_value(row, "id", 0, ""),
            "organization_id": _row_value(row, "organization_id", 1, "default"),
            "name": _row_value(row, "name", 2, ""),
            "parent_level_id": _row_value(row, "parent_level_id", 3, ""),
            "manager_username": _row_value(row, "manager_username", 4, ""),
            "updated_at": _row_value(row, "updated_at", 5, None),
        } for row in rows]

    def replace_levels(self, levels: list[Mapping[str, Any]]) -> None:
        self.ensure_schema()
        with self._connection() as connection:
            connection.execute(
                "UPDATE control_levels SET active=FALSE, updated_at=CURRENT_TIMESTAMP"
            )
            for level in levels:
                level_id = str(level.get("id") or "").strip()
                if not level_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO control_levels(
                        id, organization_id, name, parent_level_id,
                        manager_username, active, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                        organization_id=EXCLUDED.organization_id,
                        name=EXCLUDED.name,
                        parent_level_id=EXCLUDED.parent_level_id,
                        manager_username=EXCLUDED.manager_username,
                        active=TRUE,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        level_id,
                        str(level.get("organization_id") or "default"),
                        str(level.get("name") or ""),
                        str(level.get("parent_level_id") or ""),
                        str(level.get("manager_username") or ""),
                    ),
                )

    def upsert_source_version(self, value: Mapping[str, Any]) -> dict[str, Any]:
        normalized = git_source_version(**dict(value))
        self.ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO source_versions(
                    source_id, version_id, principal, profile_id, source_kind,
                    repository_ref, relative_path, branch_ref, commit_sha,
                    tree_hash, blob_hash, content_hash, snapshot_ref,
                    storage_server_id, size_bytes, dirty, metadata, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP
                )
                ON CONFLICT(source_id, version_id) DO UPDATE SET
                    profile_id=EXCLUDED.profile_id,
                    source_kind=EXCLUDED.source_kind,
                    repository_ref=EXCLUDED.repository_ref,
                    relative_path=EXCLUDED.relative_path,
                    branch_ref=EXCLUDED.branch_ref,
                    commit_sha=EXCLUDED.commit_sha,
                    tree_hash=EXCLUDED.tree_hash,
                    blob_hash=EXCLUDED.blob_hash,
                    content_hash=EXCLUDED.content_hash,
                    snapshot_ref=EXCLUDED.snapshot_ref,
                    storage_server_id=EXCLUDED.storage_server_id,
                    size_bytes=EXCLUDED.size_bytes,
                    dirty=EXCLUDED.dirty,
                    metadata=EXCLUDED.metadata,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    normalized["source_id"], normalized["version_id"],
                    normalized["principal"], normalized["profile_id"],
                    normalized["source_kind"], normalized["repository_ref"],
                    normalized["relative_path"], normalized["branch_ref"],
                    normalized["commit_sha"], normalized["tree_hash"],
                    normalized["blob_hash"], normalized["content_hash"],
                    normalized["snapshot_ref"], normalized["storage_server_id"],
                    normalized["size_bytes"], normalized["dirty"],
                    json.dumps(normalized["metadata"], ensure_ascii=False),
                ),
            )
        return normalized

    def source_version(
        self,
        *,
        source_id: str,
        version_id: str,
    ) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM source_versions
                WHERE source_id=%s AND version_id=%s
                """,
                (str(source_id), str(version_id)),
            ).fetchone()
        if row is None:
            return None
        value = dict(row) if isinstance(row, Mapping) else {}
        if isinstance(value.get("metadata"), str):
            try:
                value["metadata"] = json.loads(value["metadata"])
            except (TypeError, ValueError, json.JSONDecodeError):
                value["metadata"] = {}
        return value

    def list_profiles(self, principal: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT principal, profile_id, display_name, payload, updated_at
                FROM control_profiles WHERE principal=%s ORDER BY profile_id
                """,
                (str(principal),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row) if isinstance(row, Mapping) else {
                "principal": _row_value(row, "principal", 0, principal),
                "profile_id": _row_value(row, "profile_id", 1, ""),
                "display_name": _row_value(row, "display_name", 2, ""),
                "payload": _row_value(row, "payload", 3, {}),
                "updated_at": _row_value(row, "updated_at", 4, None),
            }
            payload = value.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError, json.JSONDecodeError):
                    payload = {}
            value["payload"] = payload if isinstance(payload, dict) else {}
            result.append(value)
        return result

    def upsert_profile(
        self,
        principal: str,
        profile_id: str,
        display_name: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO control_profiles(principal, profile_id, display_name, payload, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT(principal, profile_id) DO UPDATE SET
                    display_name=EXCLUDED.display_name,
                    payload=EXCLUDED.payload,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    str(principal), str(profile_id), str(display_name or ""),
                    json.dumps(dict(payload or {}), ensure_ascii=False),
                ),
            )

    def quota_bytes(self, principal: str, *, default_bytes: int) -> int:
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT storage_quota_bytes FROM quota_policies WHERE principal=%s",
                (str(principal),),
            ).fetchone()
        if row is None:
            return max(0, int(default_bytes))
        return max(0, int(_row_value(row, "storage_quota_bytes", 0, default_bytes) or 0))

    def set_quota(self, principal: str, quota_bytes: int) -> None:
        self.ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO quota_policies(principal, storage_quota_bytes, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(principal) DO UPDATE SET
                    storage_quota_bytes=EXCLUDED.storage_quota_bytes,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (str(principal), max(0, int(quota_bytes))),
            )

    def reconcile_server_usage(
        self,
        *,
        server_id: str,
        principal: str,
        artifact_bytes: int,
        input_bytes: int,
        output_bytes: int,
        artifact_count: int = 0,
        input_count: int = 0,
        output_count: int = 0,
    ) -> dict[str, int]:
        """Upsert one host snapshot; totals are summed across all servers."""
        self.ensure_schema()
        values = {
            "artifact_bytes": max(0, int(artifact_bytes)),
            "input_bytes": max(0, int(input_bytes)),
            "output_bytes": max(0, int(output_bytes)),
            "artifact_count": max(0, int(artifact_count)),
            "input_count": max(0, int(input_count)),
            "output_count": max(0, int(output_count)),
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO quota_server_usage(
                    server_id, principal, artifact_bytes, input_bytes,
                    output_bytes, artifact_count, input_count, output_count,
                    updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(server_id, principal) DO UPDATE SET
                    artifact_bytes=EXCLUDED.artifact_bytes,
                    input_bytes=EXCLUDED.input_bytes,
                    output_bytes=EXCLUDED.output_bytes,
                    artifact_count=EXCLUDED.artifact_count,
                    input_count=EXCLUDED.input_count,
                    output_count=EXCLUDED.output_count,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    str(server_id), str(principal), values["artifact_bytes"],
                    values["input_bytes"], values["output_bytes"],
                    values["artifact_count"], values["input_count"],
                    values["output_count"],
                ),
            )
            row = connection.execute(
                """
                SELECT COALESCE(SUM(artifact_bytes), 0) AS artifact_bytes,
                       COALESCE(SUM(input_bytes), 0) AS input_bytes,
                       COALESCE(SUM(output_bytes), 0) AS output_bytes,
                       COALESCE(SUM(artifact_count), 0) AS artifact_count,
                       COALESCE(SUM(input_count), 0) AS input_count,
                       COALESCE(SUM(output_count), 0) AS output_count
                FROM quota_server_usage WHERE principal=%s
                """,
                (str(principal),),
            ).fetchone()
        return self._usage_dict(row)

    def usage(self, principal: str) -> dict[str, int]:
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(artifact_bytes), 0) AS artifact_bytes,
                       COALESCE(SUM(input_bytes), 0) AS input_bytes,
                       COALESCE(SUM(output_bytes), 0) AS output_bytes,
                       COALESCE(SUM(artifact_count), 0) AS artifact_count,
                       COALESCE(SUM(input_count), 0) AS input_count,
                       COALESCE(SUM(output_count), 0) AS output_count
                FROM quota_server_usage WHERE principal=%s
                """,
                (str(principal),),
            ).fetchone()
        return self._usage_dict(row)

    @staticmethod
    def _usage_dict(row: object) -> dict[str, int]:
        return {
            "artifact_bytes": max(0, int(_row_value(row, "artifact_bytes", 0, 0) or 0)),
            "input_bytes": max(0, int(_row_value(row, "input_bytes", 1, 0) or 0)),
            "output_bytes": max(0, int(_row_value(row, "output_bytes", 2, 0) or 0)),
            "artifact_count": max(0, int(_row_value(row, "artifact_count", 3, 0) or 0)),
            "input_count": max(0, int(_row_value(row, "input_count", 4, 0) or 0)),
            "output_count": max(0, int(_row_value(row, "output_count", 5, 0) or 0)),
        }

    def reserve_task(
        self,
        *,
        task_id: str,
        principal: str,
        requested_bytes: int,
        default_quota_bytes: int,
    ) -> dict[str, Any]:
        """Atomically reserve cross-server quota for one task id."""
        self.ensure_schema()
        task = str(task_id or "").strip()
        owner = str(principal or "").strip()
        requested = max(0, int(requested_bytes))
        if not task or not owner:
            raise ValueError("task_id and principal are required")
        with self._connection() as connection:
            # The advisory lock serializes a quota decision for one principal
            # without introducing a second public service or a global lock.
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (owner,),
            )
            existing = connection.execute(
                "SELECT status, requested_bytes FROM quota_reservations WHERE task_id=%s",
                (task,),
            ).fetchone()
            if existing is not None:
                status = str(_row_value(existing, "status", 0, ""))
                if status == "reserved":
                    return {
                        "allowed": True,
                        "idempotent": True,
                        "task_id": task,
                        "requested_bytes": int(_row_value(existing, "requested_bytes", 1, requested) or requested),
                    }
                return {
                    "allowed": False,
                    "idempotent": True,
                    "task_id": task,
                    "status": status,
                    "error": "quota reservation is no longer active",
                }
            usage = connection.execute(
                """
                SELECT COALESCE(SUM(artifact_bytes), 0) AS artifact_bytes
                FROM quota_server_usage WHERE principal=%s
                """,
                (owner,),
            ).fetchone()
            reserved = connection.execute(
                """
                SELECT COALESCE(SUM(requested_bytes), 0) AS reserved_bytes
                FROM quota_reservations
                WHERE principal=%s AND status='reserved'
                """,
                (owner,),
            ).fetchone()
            quota = self.quota_bytes(owner, default_bytes=default_quota_bytes)
            current = int(_row_value(usage, "artifact_bytes", 0, 0) or 0)
            current += int(_row_value(reserved, "reserved_bytes", 0, 0) or 0)
            decision = quota_decision(
                current_bytes=current,
                requested_bytes=requested,
                quota_bytes=quota,
            )
            if not decision["allowed"]:
                return {
                    **decision,
                    "task_id": task,
                    "quota_bytes": quota,
                    "error": "global storage quota exceeded",
                }
            connection.execute(
                """
                INSERT INTO quota_reservations(task_id, principal, requested_bytes, status)
                VALUES (%s, %s, %s, 'reserved')
                """,
                (task, owner, requested),
            )
        return {
            **decision,
            "allowed": True,
            "task_id": task,
            "quota_bytes": quota,
            "requested_bytes": requested,
        }

    def settle_task(self, *, task_id: str, status: str = "settled") -> bool:
        self.ensure_schema()
        normalized = str(status or "settled").strip().lower()
        if normalized not in {"settled", "released"}:
            raise ValueError("reservation status must be settled or released")
        with self._connection() as connection:
            result = connection.execute(
                """
                UPDATE quota_reservations SET status=%s, settled_at=CURRENT_TIMESTAMP
                WHERE task_id=%s AND status='reserved'
                RETURNING task_id
                """,
                (normalized, str(task_id)),
            ).fetchone()
        return result is not None


def control_database_configured() -> bool:
    return ControlDatabaseConfig.from_env() is not None


def control_store_from_env(
    environ: Mapping[str, str] | None = None,
) -> PostgresControlStore | None:
    config = ControlDatabaseConfig.from_env(environ)
    return PostgresControlStore(config) if config is not None else None


def control_database_status(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a safe status object for the Manager settings page."""
    try:
        config = ControlDatabaseConfig.from_env(environ)
    except ControlDatabaseConfigurationError as exc:
        return {
            "configured": True,
            "healthy": False,
            "port": DEFAULT_CONTROL_DATABASE_PORT,
            "error": str(exc),
        }
    if config is None:
        return {
            "configured": False,
            "healthy": False,
            "port": DEFAULT_CONTROL_DATABASE_PORT,
            "mode": "local-fallback",
        }
    try:
        import psycopg  # noqa: F401
        driver = True
    except ImportError:
        driver = False
    return {
        "configured": True,
        "healthy": None,
        "driver_available": driver,
        "host": config.host,
        "port": config.port,
        "database": config.database,
        "sslmode": config.sslmode,
        "endpoint": config.redacted_url,
        "mode": "postgresql",
    }
