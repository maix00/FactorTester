from __future__ import annotations

import settings as Settings
from tools.data.factor_workspace import versions
from tools.data.sqlite import factor_source_versions


def test_sqlite_factor_source_snapshots_roundtrip_and_resolve_abbreviated_commit(
    monkeypatch, tmp_path,
):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)

    source = "class Momentum(FactorFamily):\n    pass\n"
    saved = factor_source_versions.record_factor_source_version(
        "public", "ignored-owner", "Momentum", "abcdef1234567890",
        source, relative_path="public_factors/Momentum.py", subject="create",
    )
    factor_source_versions.record_factor_source_version(
        "public", "ignored-owner", "Momentum", "fedcba1234567890",
        source, relative_path="public_factors/Momentum.py", subject="metadata-only",
    )

    listed = factor_source_versions.list_factor_source_version_snapshots(
        "public", "", "Momentum",
    )
    assert [item["commit"] for item in listed] == ["fedcba1234567890"]
    assert listed[0]["workspace"] == "server-db"

    loaded = factor_source_versions.load_factor_source_version_snapshot(
        "public", "another-owner", "Momentum", "abcdef12",
    )
    assert loaded is not None
    assert loaded["source_code"] == source
    assert loaded["source_hash"] == saved["source_hash"]

    monkeypatch.setattr(versions, "factor_source_root", lambda _username: str(tmp_path / "missing"))
    monkeypatch.setattr(versions, "WORKSPACE_ROOTS_DIR", str(tmp_path / "missing-roots"))
    result = versions.list_factor_source_versions(
        source_kind="public",
        owner_username="",
        factor_id="Momentum",
        current_source=source,
    )
    assert result["available"] is True
    assert result["workspace"] == "server-db"
    assert result["versions"][0]["commit"] == "fedcba1234567890"

    historical = versions.load_factor_source_version(
        source_kind="public",
        owner_username="",
        factor_id="Momentum",
        current_source="class Momentum(FactorFamily):\n    expr = 'new'\n",
        commit="abcdef12",
    )
    assert historical["source_code"] == source
    assert historical["is_current"] is False


def test_custom_factor_source_snapshot_keeps_owner_scope(monkeypatch, tmp_path):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    source = "class Momentum(FactorFamily):\n    pass\n"

    factor_source_versions.record_factor_source_version(
        "custom", "alice", "Momentum", "a" * 40, source,
    )
    assert factor_source_versions.load_factor_source_version_snapshot(
        "custom", "bob", "Momentum", "a" * 40,
    ) is None
    assert factor_source_versions.load_factor_source_version_snapshot(
        "custom", "alice", "Momentum", "a" * 12,
    )["source_code"] == source
