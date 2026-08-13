from __future__ import annotations

import os
from pathlib import Path

import pytest

from server.manager.storage.control_db import (
    CONTROL_DATABASE_ENCODING,
    CONTROL_DATABASE_ENV,
    CONTROL_DATABASE_SCHEMA_VERSION,
    CONTROL_SCHEMA,
    ControlDatabaseConfig,
    ControlDatabaseConfigurationError,
    quota_decision,
)
from server.manager.storage.control_database_settings import (
    ControlDatabaseSettingsStore,
)


def test_control_schema_keeps_organization_and_level_relations_central() -> None:
    schema = "\n".join(CONTROL_SCHEMA)

    assert "control_organizations" in schema
    assert "control_levels" in schema
    assert "organization_id" in schema
    assert "parent_level_id" in schema
    assert "control_users" in schema
    assert "control_devices" in schema
    assert "control_device_authorizations" in schema
    assert "control_user_preferences" in schema
    assert "preferred_language" in schema
    assert "public_key" in schema
    assert "public_access" in schema
    assert "last_seen_at" in schema
    assert "source_versions" in schema
    assert "client_type" in schema
    assert "enrollment_ip" in schema
    assert "last_seen_ip" in schema
    assert CONTROL_DATABASE_SCHEMA_VERSION == 5


def test_git_source_version_requires_an_immutable_commit_and_content_identity() -> None:
    from server.manager.storage.control_db import git_source_version

    value = git_source_version(
        source_id="factor:alpha",
        principal="default$alice@1",
        profile_id="research",
        source_kind="factor",
        repository_ref="user-factor-library",
        relative_path="custom_factors/alpha.py",
        branch_ref="feat/alpha",
        commit_sha="a" * 40,
        content_hash="b" * 64,
        blob_hash="c" * 40,
        dirty=False,
    )

    assert value["commit_sha"] == "a" * 40
    assert value["content_hash"] == "b" * 64
    assert value["version_id"] == "a" * 40 + ":" + "b" * 64

    with pytest.raises(ValueError, match="commit_sha"):
        git_source_version(
            source_id="factor:alpha",
            principal="alice",
            profile_id="research",
            source_kind="factor",
            repository_ref="repo",
            relative_path="alpha.py",
            commit_sha="short",
            content_hash="b" * 64,
        )


def test_setup_script_derives_a_tls_app_url_without_exposing_password() -> None:
    from scripts.setup_control_postgres import build_app_url

    value = build_app_url(
        admin_url="postgresql://postgres@db.example:5432/postgres",
        database="factortester_control",
        app_user="factortester_control",
        app_password="secret/pw",
    )
    config = ControlDatabaseConfig.from_url(value)

    assert config.host == "db.example"
    assert config.port == 5432
    assert config.database == "factortester_control"
    assert config.sslmode == "require"
    assert config.redacted_url.endswith("/factortester_control?sslmode=require&connect_timeout=5")


def test_setup_script_separates_unix_socket_admin_from_manager_host() -> None:
    from scripts.setup_control_postgres import _admin_connection_url, build_app_url

    value = build_app_url(
        admin_url="postgresql:///postgres?user=postgres",
        app_host="db.internal.example",
        database="factortester_control",
        app_user="factortester_control",
        app_password="secret",
    )

    config = ControlDatabaseConfig.from_url(value)
    assert config.host == "db.internal.example"
    assert config.port == 5432
    assert _admin_connection_url("postgresql:///postgres?user=postgres") == (
        "postgresql:///postgres?user=postgres"
    )


def test_setup_script_normalizes_the_database_encoding() -> None:
    from scripts.setup_control_postgres import _database_encoding

    class Connection:
        def execute(self, statement, parameters):
            assert "pg_encoding_to_char" in statement
            assert parameters == ("factortester_control",)
            return self

        def fetchone(self):
            return (b"UTF8",)

    assert CONTROL_DATABASE_ENCODING == "UTF8"
    assert _database_encoding(Connection(), "factortester_control") == "UTF8"


def test_setup_script_creates_utf8_database_from_template_zero() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts" / "setup_control_postgres.py"
    ).read_text(encoding="utf-8")

    assert "ENCODING 'UTF8' TEMPLATE template0" in source


def test_control_database_uses_remote_postgres_default_port_and_tls() -> None:
    config = ControlDatabaseConfig.from_url(
        "postgresql://control:secret@control.example/factortester"
    )

    assert config.host == "control.example"
    assert config.port == 5432
    assert config.database == "factortester"
    assert config.sslmode == "require"
    assert "secret" not in config.redacted_url
    assert "control.example:5432" in config.redacted_url


def test_control_database_accepts_explicit_port_and_verify_full() -> None:
    config = ControlDatabaseConfig.from_url(
        "postgresql://control:secret@10.0.0.5:55432/factortester"
        "?sslmode=verify-full&connect_timeout=7"
    )

    assert config.port == 55432
    assert config.sslmode == "verify-full"
    assert config.connect_timeout == 7


def test_control_database_rejects_non_postgres_urls() -> None:
    with pytest.raises(ControlDatabaseConfigurationError, match="postgresql"):
        ControlDatabaseConfig.from_url("sqlite:///tmp/control.db")


def test_control_database_settings_persist_secret_without_projecting_it(
    tmp_path,
) -> None:
    path = tmp_path / "control-database.json"
    store = ControlDatabaseSettingsStore(path, environ={})
    config = store.candidate({
        "host": "101.133.144.27",
        "port": 5432,
        "database": "factortester_control",
        "user": "factortester_control",
        "password": "secret/pw",
        "sslmode": "require",
        "connect_timeout": 5,
    })

    store.save(config)
    status = store.status()

    assert path.stat().st_mode & 0o777 == 0o600
    assert status["managed_by"] == "settings"
    assert status["host"] == "101.133.144.27"
    assert status["user"] == "factortester_control"
    assert status["password_configured"] is True
    assert "secret" not in str(status)
    updated = store.candidate({
        "host": "control.example",
        "password": "",
    })
    assert "secret%2Fpw" in updated.url


def test_environment_managed_control_database_is_read_only(tmp_path) -> None:
    store = ControlDatabaseSettingsStore(
        tmp_path / "control-database.json",
        environ={
            CONTROL_DATABASE_ENV: (
                "postgresql://control:secret@127.0.0.1/control"
                "?sslmode=require&connect_timeout=5"
            ),
        },
    )

    assert store.status()["managed_by"] == "environment"
    with pytest.raises(PermissionError, match="server environment"):
        store.candidate({"host": "101.133.144.27"})


def test_manager_switches_control_database_only_after_connection_succeeds(
    tmp_path, monkeypatch,
) -> None:
    from server.manager import runtime as manager
    from server.manager.state import control_database as state_module

    monkeypatch.delenv(CONTROL_DATABASE_ENV, raising=False)
    connected = []

    class _Store:
        def __init__(self, config):
            self.config = config

        def load_accounts(self):
            connected.append(self.config.redacted_url)
            return []

    monkeypatch.setattr(state_module, "PostgresControlStore", _Store)
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        state_root=tmp_path / "state",
    )
    result = state.update_control_database({
        "host": "101.133.144.27",
        "port": 5432,
        "database": "factortester_control",
        "user": "factortester_control",
        "password": "secret",
        "sslmode": "require",
    })

    assert result["healthy"] is True
    assert result["host"] == "101.133.144.27"
    assert connected
    assert state.device_registry.control_store is state.control_store
    assert state.device_authorizations.control_store is state.control_store
    assert state.user_preferences.control_store is state.control_store
    assert CONTROL_DATABASE_ENV not in os.environ

    monkeypatch.setattr(
        "server.manager.state.processes.subprocess.check_output",
        lambda *args, **kwargs: "a" * 40 + "\n",
    )
    child_env, _, _ = state._service_env(tmp_path / "repo", 8000)
    assert child_env[CONTROL_DATABASE_ENV].startswith("postgresql://")


def test_quota_decision_is_atomic_at_the_policy_boundary() -> None:
    assert quota_decision(
        current_bytes=100,
        requested_bytes=200,
        quota_bytes=300,
    ) == {"allowed": True, "projected_bytes": 300, "remaining_bytes": 200}
    assert quota_decision(
        current_bytes=100,
        requested_bytes=201,
        quota_bytes=300,
    ) == {"allowed": False, "projected_bytes": 301, "remaining_bytes": 200}
