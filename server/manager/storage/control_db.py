"""PostgreSQL control-plane storage for Manager-owned operational metadata.

Keycloak is the sole authority for users, organizations, groups, roles, and
permissions. This database retains non-identity projections such as profiles,
quotas, devices, and account-domain objects.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import parse_qs, urlsplit, urlunsplit

from server.manager.storage.account_domain.remote import AccountDomainControlMixin


CONTROL_DATABASE_ENV = "FACTORTESTER_CONTROL_DATABASE_URL"
DEFAULT_CONTROL_DATABASE_PORT = 5432
DEFAULT_CONTROL_DATABASE_SSLMODE = "require"
DEFAULT_CONTROL_DATABASE_TIMEOUT = 5
CONTROL_DATABASE_SCHEMA_VERSION = 11
CONTROL_DATABASE_ENCODING = "UTF8"
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
    CREATE TABLE IF NOT EXISTS control_devices (
        device_id TEXT PRIMARY KEY,
        public_key JSONB NOT NULL,
        username TEXT NOT NULL,
        device_name TEXT NOT NULL DEFAULT '',
        client_type TEXT NOT NULL DEFAULT 'unknown',
        client_name TEXT NOT NULL DEFAULT '',
        enrollment_ip TEXT NOT NULL DEFAULT '',
        last_seen_ip TEXT NOT NULL DEFAULT '',
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        source_server_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TIMESTAMPTZ
    )
    """,
    "ALTER TABLE control_devices ADD COLUMN IF NOT EXISTS client_type TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE control_devices ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control_devices ADD COLUMN IF NOT EXISTS enrollment_ip TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control_devices ADD COLUMN IF NOT EXISTS last_seen_ip TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS control_devices_username ON control_devices(username, enabled)",
    "DROP INDEX IF EXISTS control_devices_public_username",
    "ALTER TABLE control_devices DROP COLUMN IF EXISTS public_access",
    "ALTER TABLE control_devices DROP COLUMN IF EXISTS quota_exempt",
    "CREATE INDEX IF NOT EXISTS control_devices_source ON control_devices(source_server_id, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS control_user_preferences (
        principal TEXT PRIMARY KEY,
        preferred_language TEXT NOT NULL DEFAULT 'system',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK (preferred_language IN ('system', 'zh-Hans', 'en'))
    )
    """,
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
    CREATE SEQUENCE IF NOT EXISTS control_account_domain_revision_seq
    """,
    """
    CREATE TABLE IF NOT EXISTS control_account_domain_entities (
        principal TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        deleted BOOLEAN NOT NULL DEFAULT FALSE,
        visibility TEXT NOT NULL DEFAULT 'private',
        authorized_users JSONB NOT NULL DEFAULT '[]'::jsonb,
        storage_server_id TEXT NOT NULL DEFAULT '',
        origin_manager_id TEXT NOT NULL DEFAULT '',
        revision BIGINT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (principal, entity_type, entity_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS control_account_domain_revision ON control_account_domain_entities(revision)",
    "CREATE INDEX IF NOT EXISTS control_account_domain_principal ON control_account_domain_entities(principal, entity_type, updated_at DESC)",
    "ALTER TABLE control_account_domain_entities ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'",
    "ALTER TABLE control_account_domain_entities ADD COLUMN IF NOT EXISTS authorized_users JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE control_account_domain_entities ADD COLUMN IF NOT EXISTS storage_server_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control_account_domain_entities ADD COLUMN IF NOT EXISTS origin_manager_id TEXT NOT NULL DEFAULT ''",
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
    """
    CREATE TABLE IF NOT EXISTS quota_deferred_output_cleanups (
        request_id TEXT PRIMARY KEY,
        principal TEXT NOT NULL,
        server_id TEXT NOT NULL,
        snapshot_output_bytes BIGINT NOT NULL,
        snapshot_output_count BIGINT NOT NULL,
        snapshot_observed_at TIMESTAMPTZ NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        claimed_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        deleted_artifacts BIGINT NOT NULL DEFAULT 0,
        freed_bytes BIGINT NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        CHECK (snapshot_output_bytes > 0),
        CHECK (snapshot_output_count >= 0),
        CHECK (status IN ('pending', 'executing', 'completed',
                         'cancelled', 'needs_review'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS quota_deferred_output_cleanups_principal "
    "ON quota_deferred_output_cleanups(principal, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS quota_deferred_output_cleanups_server "
    "ON quota_deferred_output_cleanups(server_id, status, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS quota_deferred_output_cleanup_active "
    "ON quota_deferred_output_cleanups(principal, server_id) "
    "WHERE status IN ('pending', 'executing')",
    """
    CREATE TABLE IF NOT EXISTS quota_profile_usage (
        server_id TEXT NOT NULL,
        principal TEXT NOT NULL,
        research_reports_bytes BIGINT NOT NULL,
        profile_uploads_bytes BIGINT NOT NULL,
        profile_workspaces_bytes BIGINT NOT NULL,
        research_reports_count BIGINT NOT NULL,
        profile_uploads_count BIGINT NOT NULL,
        profile_workspaces_count BIGINT NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (server_id, principal),
        CHECK (research_reports_bytes >= 0),
        CHECK (profile_uploads_bytes >= 0),
        CHECK (profile_workspaces_bytes >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS quota_profile_usage_principal ON quota_profile_usage(principal)",
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


class PostgresControlStore(AccountDomainControlMixin):
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
            connection = psycopg.connect(
                self.config.url,
                row_factory=dict_row,
                **self.config.connect_kwargs,
            )
            reported_encoding = str(connection.info.encoding or "")
            encoding = reported_encoding.replace("-", "").upper()
            if encoding != CONTROL_DATABASE_ENCODING:
                connection.close()
                raise ControlDatabaseConfigurationError(
                    "control database must use UTF8 encoding; "
                    f"found {reported_encoding or 'unknown'}"
                )
            return connection
        except ControlDatabaseError:
            raise
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
            "enabled": _row_value(row, "enabled", 8, False),
            "source_server_id": _row_value(row, "source_server_id", 9, ""),
            "created_at": _row_value(row, "created_at", 10, None),
            "updated_at": _row_value(row, "updated_at", 11, None),
            "last_seen_at": _row_value(row, "last_seen_at", 12, None),
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
            row = connection.execute(
                """
                INSERT INTO control_devices(
                    device_id, public_key, username, device_name,
                    client_type, client_name, enrollment_ip, last_seen_ip,
                    enabled, source_server_id, updated_at
                ) VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s,
                          TRUE, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(device_id) DO NOTHING
                RETURNING device_id, public_key, username, device_name,
                          client_type, client_name, enrollment_ip, last_seen_ip,
                          enabled, source_server_id,
                          created_at, updated_at, last_seen_at
                """,
                (
                    str(device_id), json.dumps(dict(public_key), ensure_ascii=False),
                    str(username), str(device_name or "")[:128],
                    str(client_type or "unknown")[:32],
                    str(client_name or "")[:128],
                    str(enrollment_ip or "")[:45],
                    str(enrollment_ip or "")[:45],
                    str(source_server_id),
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
                       enabled, source_server_id,
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
                       enabled, source_server_id,
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
                          enabled, source_server_id,
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
        predicates = ["enabled=TRUE"]
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
                WHERE enabled=TRUE
                """
            ).fetchone()
        return int(_row_value(row, "count", 0, 0))

    def public_device_total_count(self, *, username: str = "") -> int:
        """Count all enabled public allowlist devices."""
        self.ensure_schema()
        predicates = ["enabled=TRUE"]
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

    def load_user_preference(self, principal: str) -> dict[str, Any] | None:
        """Load one small global preference row for Manager cache refresh."""
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT preferred_language AS language, updated_at
                FROM control_user_preferences
                WHERE principal=%s
                """,
                (str(principal),),
            ).fetchone()
        if row is None:
            return None
        value = dict(row) if isinstance(row, Mapping) else {
            "language": _row_value(row, "language", 0, "system"),
            "updated_at": _row_value(row, "updated_at", 1, None),
        }
        if hasattr(value.get("updated_at"), "isoformat"):
            value["updated_at"] = value["updated_at"].isoformat()
        return value

    def upsert_user_preference(
        self,
        principal: str,
        *,
        language: str,
    ) -> dict[str, Any]:
        """Write through one user preference and return its canonical row."""
        if str(language) not in {"system", "zh-Hans", "en"}:
            raise ValueError("language preference is invalid")
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                """
                INSERT INTO control_user_preferences(
                    principal, preferred_language, updated_at
                ) VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(principal) DO UPDATE SET
                    preferred_language=excluded.preferred_language,
                    updated_at=CURRENT_TIMESTAMP
                RETURNING preferred_language AS language, updated_at
                """,
                (str(principal), str(language)),
            ).fetchone()
        value = dict(row) if isinstance(row, Mapping) else {
            "language": _row_value(row, "language", 0, "system"),
            "updated_at": _row_value(row, "updated_at", 1, None),
        }
        if hasattr(value.get("updated_at"), "isoformat"):
            value["updated_at"] = value["updated_at"].isoformat()
        return value





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
    def _unified_usage_sql() -> str:
        return """
            SELECT GREATEST(0,
              COALESCE((SELECT SUM(artifact_bytes) FROM quota_server_usage
                        WHERE principal=%s), 0)
              + COALESCE((SELECT SUM(research_reports_bytes + profile_uploads_bytes
                                     + profile_workspaces_bytes)
                          FROM quota_profile_usage WHERE principal=%s), 0)
              + COALESCE((SELECT SUM(OCTET_LENGTH(payload::text))
                          FROM control_account_domain_entities
                          WHERE principal=%s AND NOT deleted), 0)
              - COALESCE((SELECT SUM(LEAST(
                    requests.snapshot_output_bytes, usage.output_bytes))
                  FROM quota_deferred_output_cleanups AS requests
                  JOIN quota_server_usage AS usage
                    ON usage.server_id=requests.server_id
                   AND usage.principal=requests.principal
                  WHERE requests.principal=%s
                    AND requests.status IN ('pending', 'executing')), 0)
            ) AS used_bytes
        """

    def unified_usage_bytes(self, principal: str) -> int:
        """Meter all currently known server and account-domain storage."""
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute(
                self._unified_usage_sql(), (str(principal),) * 4,
            ).fetchone()
        return max(0, int(_row_value(row, "used_bytes", 0, 0) or 0))

    def usage_by_server(self, principal: str) -> list[dict[str, Any]]:
        """Read existing Job quota snapshots with their observation times."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT server_id, artifact_bytes, input_bytes, output_bytes,
                       artifact_count, input_count, output_count, updated_at
                FROM quota_server_usage WHERE principal=%s
                ORDER BY server_id
                """, (str(principal),),
            ).fetchall()
        result = []
        for row in rows:
            observed = _row_value(row, "updated_at", 7)
            result.append({
                "storage_server_id": str(_row_value(row, "server_id", 0, "") or ""),
                **{
                    key: max(0, int(_row_value(row, key, index, 0) or 0))
                    for index, key in enumerate((
                        "artifact_bytes", "input_bytes", "output_bytes",
                        "artifact_count", "input_count", "output_count",
                    ), start=1)
                },
                "observed_at": observed.isoformat() if hasattr(observed, "isoformat")
                else str(observed or ""),
            })
        return result

    @staticmethod
    def _deferred_cleanup_value(row: object) -> dict[str, Any]:
        names = (
            "request_id", "principal", "server_id", "snapshot_output_bytes",
            "snapshot_output_count", "snapshot_observed_at", "status",
            "created_at", "claimed_at", "finished_at", "deleted_artifacts",
            "freed_bytes", "error", "credit_bytes",
        )
        value = {name: _row_value(row, name, index) for index, name in enumerate(names)}
        for name in ("snapshot_observed_at", "created_at", "claimed_at", "finished_at"):
            raw = value[name]
            value[name] = raw.isoformat() if hasattr(raw, "isoformat") else str(raw or "")
        for name in ("snapshot_output_bytes", "snapshot_output_count",
                     "deleted_artifacts", "freed_bytes", "credit_bytes"):
            value[name] = max(0, int(value[name] or 0))
        value["error"] = str(value["error"] or "")
        return value

    def deferred_output_cleanups(self, principal: str) -> list[dict[str, Any]]:
        """Read only this user's bounded command history and current quota credit."""
        self.ensure_schema()
        with self._connection() as connection:
            rows = connection.execute("""
                SELECT requests.*, CASE WHEN requests.status IN ('pending', 'executing')
                    THEN LEAST(requests.snapshot_output_bytes,
                               COALESCE(usage.output_bytes, 0))
                    ELSE 0 END AS credit_bytes
                FROM quota_deferred_output_cleanups AS requests
                LEFT JOIN quota_server_usage AS usage
                  ON usage.server_id=requests.server_id
                 AND usage.principal=requests.principal
                WHERE requests.principal=%s
                ORDER BY requests.created_at DESC LIMIT 100
            """, (str(principal),)).fetchall()
        return [self._deferred_cleanup_value(row) for row in rows]

    def queue_deferred_output_cleanup(
        self, *, principal: str, server_id: str, expected_bytes: int,
        expected_count: int, observed_at: str,
    ) -> dict[str, Any]:
        """Atomically anchor one reversible request to a measured server row."""
        owner, server = str(principal or "").strip(), str(server_id or "").strip()
        if (not owner or not server or len(server) > 128 or not observed_at
                or expected_bytes <= 0
                or expected_count < 0):
            raise ValueError("valid owner, server and measured output are required")
        try:
            if datetime.fromisoformat(str(observed_at).replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("snapshot observation needs a timezone")
        except ValueError as exc:
            raise ValueError("invalid snapshot observation time") from exc
        self.ensure_schema()
        with self._connection() as connection:
            usage = connection.execute("""
                SELECT output_bytes, output_count, updated_at
                FROM quota_server_usage
                WHERE principal=%s AND server_id=%s
                  AND updated_at=%s::timestamptz FOR UPDATE
            """, (owner, server, observed_at)).fetchone()
            if (usage is None or int(_row_value(usage, "output_bytes", 0, 0)) != expected_bytes
                    or int(_row_value(usage, "output_count", 1, 0)) != expected_count):
                # The client must refresh rather than scheduling against a
                # different server generation or stale usage measurement.
                raise ValueError("storage snapshot changed; refresh before scheduling")
            existing = connection.execute("""
                SELECT requests.*, LEAST(requests.snapshot_output_bytes,
                    %s) AS credit_bytes
                FROM quota_deferred_output_cleanups AS requests
                WHERE principal=%s AND server_id=%s
                  AND status IN ('pending', 'executing') FOR UPDATE
            """, (expected_bytes, owner, server)).fetchone()
            if existing is not None:
                if (int(_row_value(existing, "snapshot_output_bytes", 3, 0)) == expected_bytes
                        and str(_row_value(existing, "status", 6, "")) == "pending"):
                    return self._deferred_cleanup_value(existing)
                raise ValueError("an output cleanup is already in progress for this server")
            request_id = uuid.uuid4().hex
            row = connection.execute("""
                INSERT INTO quota_deferred_output_cleanups(
                    request_id, principal, server_id, snapshot_output_bytes,
                    snapshot_output_count, snapshot_observed_at
                ) VALUES (%s, %s, %s, %s, %s, %s::timestamptz)
                RETURNING *, snapshot_output_bytes AS credit_bytes
            """, (request_id, owner, server, expected_bytes, expected_count,
                  observed_at)).fetchone()
        return self._deferred_cleanup_value(row)

    def cancel_deferred_output_cleanup(
        self, *, principal: str, request_id: str,
    ) -> dict[str, Any]:
        """Refund quota only while the target has not claimed the request."""
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute("""
                UPDATE quota_deferred_output_cleanups
                SET status='cancelled', finished_at=CURRENT_TIMESTAMP
                WHERE principal=%s AND request_id=%s AND status='pending'
                RETURNING *, 0 AS credit_bytes
            """, (str(principal), str(request_id))).fetchone()
        if row is None:
            raise ValueError("cleanup is unavailable or already executing")
        return self._deferred_cleanup_value(row)

    def claim_deferred_output_cleanup(self, *, server_id: str) -> dict[str, Any] | None:
        """Claim one local command; an expired execution is retryable after crash."""
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute("""
                WITH selected AS (
                    SELECT request_id FROM quota_deferred_output_cleanups
                    WHERE server_id=%s AND (
                        status='pending' OR
                        (status='executing' AND claimed_at <
                         CURRENT_TIMESTAMP - INTERVAL '60 seconds'))
                    ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE quota_deferred_output_cleanups AS requests
                SET status='executing', claimed_at=CURRENT_TIMESTAMP
                FROM selected WHERE requests.request_id=selected.request_id
                RETURNING requests.*, requests.snapshot_output_bytes AS credit_bytes
            """, (str(server_id),)).fetchone()
        return self._deferred_cleanup_value(row) if row is not None else None

    def finish_deferred_output_cleanup(
        self, *, server_id: str, request_id: str, status: str,
        deleted_artifacts: int = 0, freed_bytes: int = 0, error: str = "",
    ) -> dict[str, Any]:
        if status not in {"completed", "needs_review"}:
            raise ValueError("invalid cleanup result")
        self.ensure_schema()
        with self._connection() as connection:
            row = connection.execute("""
                UPDATE quota_deferred_output_cleanups
                SET status=%s, finished_at=CURRENT_TIMESTAMP,
                    deleted_artifacts=%s, freed_bytes=%s, error=%s
                WHERE server_id=%s AND request_id=%s AND status='executing'
                RETURNING *, 0 AS credit_bytes
            """, (status, max(0, int(deleted_artifacts)),
                  max(0, int(freed_bytes)), str(error)[:500],
                  str(server_id), str(request_id))).fetchone()
        if row is None:
            raise ValueError("cleanup is not claimed by this server")
        return self._deferred_cleanup_value(row)

    def release_deferred_output_cleanup(
        self, *, server_id: str, request_id: str, error: str,
    ) -> None:
        """Return a transient failure to the cancellable pending state."""
        self.ensure_schema()
        with self._connection() as connection:
            connection.execute("""
                UPDATE quota_deferred_output_cleanups
                SET status='pending', claimed_at=NULL, error=%s
                WHERE server_id=%s AND request_id=%s AND status='executing'
            """, (str(error)[:500], str(server_id), str(request_id)))

    def record_profile_usage(
        self, *, server_id: str, principal: str, inventory: Mapping[str, Any],
    ) -> None:
        """Keep the last complete local scan for use while its server is offline."""
        categories = inventory.get("categories")
        names = ("research_reports", "profile_uploads", "profile_workspaces")
        if not server_id or not principal or not isinstance(categories, Mapping) or set(categories) != set(names):
            raise ValueError("invalid Profile storage identity or categories")
        sizes = []
        counts = []
        for name in names:
            value = categories[name]
            if not isinstance(value, Mapping):
                raise ValueError("invalid Profile storage category")
            size, count = value.get("bytes"), value.get("file_count")
            if type(size) is not int or size < 0 or type(count) is not int or count < 0:
                raise ValueError("invalid Profile storage category")
            sizes.append(size)
            counts.append(count)
        observed = inventory.get("observed_at")
        if (type(observed) not in (int, float) or not math.isfinite(observed)
                or observed <= 0
                or type(inventory.get("bytes")) is not int
                or sum(sizes) != inventory["bytes"]):
            raise ValueError("incomplete Profile storage inventory")
        self.ensure_schema()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO quota_profile_usage (
                    server_id, principal, research_reports_bytes,
                    profile_uploads_bytes, profile_workspaces_bytes,
                    research_reports_count, profile_uploads_count,
                    profile_workspaces_count, observed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, to_timestamp(%s))
                ON CONFLICT(server_id, principal) DO UPDATE SET
                    research_reports_bytes=EXCLUDED.research_reports_bytes,
                    profile_uploads_bytes=EXCLUDED.profile_uploads_bytes,
                    profile_workspaces_bytes=EXCLUDED.profile_workspaces_bytes,
                    research_reports_count=EXCLUDED.research_reports_count,
                    profile_uploads_count=EXCLUDED.profile_uploads_count,
                    profile_workspaces_count=EXCLUDED.profile_workspaces_count,
                    observed_at=EXCLUDED.observed_at
                WHERE quota_profile_usage.observed_at <= EXCLUDED.observed_at
                """,
                (str(server_id), str(principal), *sizes, *counts, float(observed)),
            )

    def profile_usage_by_server(self, principal: str) -> list[dict[str, Any]]:
        """Return only servers for which a complete Profile scan was saved."""
        self.ensure_schema()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT server_id, research_reports_bytes, profile_uploads_bytes,
                       profile_workspaces_bytes, research_reports_count,
                       profile_uploads_count, profile_workspaces_count,
                       observed_at
                FROM quota_profile_usage WHERE principal=%s ORDER BY server_id
                """, (str(principal),),
            ).fetchall()
        result = []
        for row in rows:
            categories = {}
            for index, name in enumerate(("research_reports", "profile_uploads", "profile_workspaces")):
                categories[name] = {
                    "bytes": max(0, int(_row_value(row, f"{name}_bytes", index + 1, 0) or 0)),
                    "file_count": max(0, int(_row_value(row, f"{name}_count", index + 4, 0) or 0)),
                }
            observed = _row_value(row, "observed_at", 7)
            result.append({
                "storage_server_id": str(_row_value(row, "server_id", 0, "") or ""),
                "status": "last_observed",
                "inventory": {
                    "categories": categories,
                    "bytes": sum(item["bytes"] for item in categories.values()),
                    "observed_at": observed.isoformat() if hasattr(observed, "isoformat") else str(observed or ""),
                },
            })
        return result

    def protected_entity_metadata_usage(self, principal: str) -> dict[str, dict[str, int]]:
        """Measure authoritative active account-domain JSON metadata.

        Source bodies and Profile files are separate storage authorities; this
        read-only query cannot be presented as their physical disk usage.
        """
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT entity_type, COUNT(*) AS item_count,
                       COALESCE(SUM(OCTET_LENGTH(payload::text)), 0) AS bytes
                FROM control_account_domain_entities
                WHERE principal=%s AND NOT deleted
                GROUP BY entity_type
                """, (str(principal),),
            ).fetchall()
        result = {
            "factors": {"bytes": 0, "item_count": 0},
            "product_groups": {"bytes": 0, "item_count": 0},
            "strategies": {"bytes": 0, "item_count": 0},
            "other": {"bytes": 0, "item_count": 0},
        }
        for row in rows:
            entity_type = str(_row_value(row, "entity_type", 0, ""))
            category = ("product_groups" if entity_type in
                        {"product_group", "product_category"} else
                        "factors" if entity_type.startswith("factor_") else
                        "strategies" if entity_type.startswith("strategy_") else
                        "other")
            result[category]["bytes"] += max(
                0, int(_row_value(row, "bytes", 2, 0) or 0)
            )
            result[category]["item_count"] += max(
                0, int(_row_value(row, "item_count", 1, 0) or 0)
            )
        return result

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
                self._unified_usage_sql(), (owner,) * 4,
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
            current = int(_row_value(usage, "used_bytes", 0, 0) or 0)
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
