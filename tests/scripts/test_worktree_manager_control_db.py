from __future__ import annotations

import pytest

from scripts.worktree_manager_control_db import (
    CONTROL_DATABASE_SCHEMA_VERSION,
    CONTROL_SCHEMA,
    ControlDatabaseConfig,
    ControlDatabaseConfigurationError,
    quota_decision,
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
    assert "public_key" in schema
    assert "public_access" in schema
    assert "last_seen_at" in schema
    assert "source_versions" in schema
    assert "client_type" in schema
    assert "enrollment_ip" in schema
    assert "last_seen_ip" in schema
    assert CONTROL_DATABASE_SCHEMA_VERSION == 4


def test_git_source_version_requires_an_immutable_commit_and_content_identity() -> None:
    from scripts.worktree_manager_control_db import git_source_version

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
