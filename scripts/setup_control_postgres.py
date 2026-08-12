#!/usr/bin/env python3
"""One-time, idempotent PostgreSQL control-database bootstrap.

Run this on the remote host that owns PostgreSQL, for example:

    sudo -u postgres python scripts/setup_control_postgres.py \
      --admin-url 'postgresql:///postgres?user=postgres' \
      --app-host 203.0.113.10 \
      --env-file /etc/factortester/control-db.env

The script creates only the dedicated database role/database and the
FactorTester control schema.  It does not start a Manager or open a network
socket.  Both the local and remote Managers later use the URL written to the
environment file and connect to the remote PostgreSQL TCP port (5432 by
default).
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

# Make ``python scripts/setup_control_postgres.py`` work when launched from a
# release checkout.  The installed service uses the same repository layout,
# while tests import this module as ``scripts.*``.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.worktree_manager_control_db import (
    ControlDatabaseConfig,
    ControlDatabaseConfigurationError,
    ControlDatabaseUnavailable,
    PostgresControlStore,
)


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
DEFAULT_DATABASE = "factortester_control"
DEFAULT_APP_USER = "factortester_control"
DEFAULT_SSLMODE = "require"


def _identifier(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(
            f"{field} must contain only ASCII letters, digits, and underscores"
        )
    return normalized


def _require_psycopg():
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required; install deploy/requirements-linux.txt first"
        ) from exc
    return psycopg, sql


def build_app_url(
    *,
    admin_url: str,
    database: str,
    app_user: str,
    app_password: str,
    app_host: str = "",
    sslmode: str = DEFAULT_SSLMODE,
    connect_timeout: int = 5,
) -> str:
    """Build the application URL without leaking the password.

    ``admin_url`` may use the remote host's local Unix socket.  In that case
    ``app_host`` is required because the Managers connect to PostgreSQL over
    TCP.  Keeping these two addresses separate also prevents accidentally
    writing ``127.0.0.1`` into an env file that is later copied to another
    server.
    """
    parsed = urlsplit(str(admin_url or "").strip())
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ValueError("admin URL must be a PostgreSQL URL")
    if not str(app_password):
        raise ValueError("app password is required")
    if not 1 <= int(connect_timeout) <= 120:
        raise ValueError("connect_timeout must be between 1 and 120")
    host = str(app_host or parsed.hostname or "").strip()
    if not host:
        raise ValueError("app_host is required when admin URL has no host")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{quote(app_user, safe='')}:{quote(app_password, safe='')}@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    query = f"sslmode={quote(str(sslmode), safe='')}&connect_timeout={int(connect_timeout)}"
    return urlunsplit(("postgresql", netloc, f"/{database}", query, ""))


def _admin_connection_url(admin_url: str) -> str:
    parsed = urlsplit(str(admin_url or "").strip())
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ValueError("admin URL must be a PostgreSQL URL")
    if parsed.netloc:
        return urlunsplit((parsed.scheme, parsed.netloc, "/postgres", parsed.query, ""))
    # ``postgresql:///postgres?user=postgres`` selects the local Unix socket.
    # urlunsplit() would collapse the empty netloc to one slash, which libpq
    # interprets as the invalid option ``postgresql:/postgres``.
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}:///postgres{query}"


def _role_exists(connection, role: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
    ).fetchone() is not None


def _database_exists(connection, database: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
    ).fetchone() is not None


def bootstrap(
    *,
    admin_url: str,
    database: str,
    app_user: str,
    app_password: str,
    app_host: str,
    sslmode: str,
    connect_timeout: int,
    rotate_password: bool = False,
) -> dict[str, object]:
    """Create the role/database and apply the control schema."""
    database = _identifier(database, "database")
    app_user = _identifier(app_user, "app_user")
    app_url = build_app_url(
        admin_url=admin_url,
        database=database,
        app_user=app_user,
        app_password=app_password,
        app_host=app_host,
        sslmode=sslmode,
        connect_timeout=connect_timeout,
    )
    psycopg, sql = _require_psycopg()
    created_role = False
    created_database = False
    with psycopg.connect(
        _admin_connection_url(admin_url),
        autocommit=True,
        connect_timeout=int(connect_timeout),
        sslmode=sslmode,
    ) as admin:
        if not _role_exists(admin, app_user):
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(app_user),
                    sql.Literal(app_password),
                ),
            )
            created_role = True
        elif rotate_password:
            admin.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(app_user),
                    sql.Literal(app_password),
                ),
            )
        if not _database_exists(admin, database):
            admin.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database), sql.Identifier(app_user),
                )
            )
            created_database = True
        admin.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(app_user),
            )
        )

    config = ControlDatabaseConfig.from_url(app_url)
    store = PostgresControlStore(config)
    store.ensure_schema()
    return {
        "database": database,
        "app_user": app_user,
        "created_role": created_role,
        "created_database": created_database,
        "app_url": app_url,
        "redacted_url": config.redacted_url,
        "port": config.port,
    }


def write_env_file(path: str | Path, app_url: str) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        f"FACTORTESTER_CONTROL_DATABASE_URL={app_url}\n",
        encoding="utf-8",
    )
    os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-url",
        default=os.environ.get("FACTORTESTER_POSTGRES_ADMIN_URL", ""),
        help="administrator URL, normally the remote host's local postgres DB",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("FACTORTESTER_CONTROL_DATABASE_NAME", DEFAULT_DATABASE),
    )
    parser.add_argument(
        "--app-user",
        default=os.environ.get("FACTORTESTER_CONTROL_DATABASE_USER", DEFAULT_APP_USER),
    )
    parser.add_argument(
        "--app-password",
        default=os.environ.get("FACTORTESTER_CONTROL_DATABASE_PASSWORD", ""),
        help="prefer an environment/secret manager; prompt if omitted",
    )
    parser.add_argument(
        "--app-host",
        default=os.environ.get("FACTORTESTER_CONTROL_DATABASE_HOST", ""),
        help="TCP hostname/IP used by Managers; required for a Unix-socket admin URL",
    )
    parser.add_argument("--sslmode", choices=("require", "verify-ca", "verify-full"), default=DEFAULT_SSLMODE)
    parser.add_argument("--connect-timeout", type=int, default=5)
    parser.add_argument("--rotate-password", action="store_true")
    parser.add_argument(
        "--env-file",
        default="",
        help="optional 600-mode file containing FACTORTESTER_CONTROL_DATABASE_URL",
    )
    args = parser.parse_args(argv)
    try:
        if not args.admin_url:
            raise ValueError("--admin-url or FACTORTESTER_POSTGRES_ADMIN_URL is required")
        password = str(args.app_password or "")
        if not password:
            if not sys.stdin.isatty():
                raise ValueError("--app-password or FACTORTESTER_CONTROL_DATABASE_PASSWORD is required")
            password = getpass.getpass("PostgreSQL control user password: ")
        result = bootstrap(
            admin_url=args.admin_url,
            database=args.database,
            app_user=args.app_user,
            app_password=password,
            app_host=args.app_host,
            sslmode=args.sslmode,
            connect_timeout=args.connect_timeout,
            rotate_password=bool(args.rotate_password),
        )
        if args.env_file:
            target = write_env_file(args.env_file, str(result["app_url"]))
            result["env_file"] = str(target)
        print(
            "control database ready: "
            f"{result['database']} on PostgreSQL port {result['port']} "
            f"({result['redacted_url']})"
        )
        if result.get("env_file"):
            print(f"wrote owner-only environment file: {result['env_file']}")
        else:
            print("set FACTORTESTER_CONTROL_DATABASE_URL from the secret manager")
        return 0
    except (ControlDatabaseConfigurationError, ControlDatabaseUnavailable, RuntimeError, ValueError) as exc:
        print(f"control database bootstrap failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
