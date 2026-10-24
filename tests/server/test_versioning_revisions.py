from __future__ import annotations

import hashlib

import pytest

from server.manager.storage.account_domain import AccountDomainSyncService
from server.services.versioning import (
    REVISION_ENTITY_TYPE,
    build_revision_manifest,
    list_revision_manifests,
    publish_revision,
)
from tests.scripts.test_worktree_manager_account_domain_sync import MemoryControlStore
from tools.data.sqlite.factor_source_versions import record_factor_formula_version


def manifest(**overrides):
    values = {
        "object_kind": "product_group",
        "object_ref": "product-group:pg_123",
        "revision_ref": "product-group-revision:abc",
        "content_sha256": hashlib.sha256(b"definition").hexdigest(),
        "owner_ref": "alice",
        "storage_server_id": "manager-a",
        "created_at": 1_800_000_000.0,
        "created_by": "alice",
        "visibility": "private",
        "source_entity_type": "product_group",
    }
    values.update(overrides)
    return build_revision_manifest(**values)


def test_revision_manifest_is_bounded_and_rejects_invalid_identity():
    value = manifest(revision_number=2, object_bytes=32)
    assert value["schema_version"] == 1
    assert value["revision_number"] == 2
    with pytest.raises(ValueError, match="SHA-256"):
        manifest(content_sha256="nope")
    with pytest.raises(ValueError, match="object kind"):
        manifest(object_kind="job")
    with pytest.raises(ValueError, match="revision_number"):
        manifest(revision_number=0)


def test_version_index_uses_existing_cross_server_outbox_and_preserves_scope(tmp_path):
    control = MemoryControlStore()
    writer = AccountDomainSyncService(
        sqlite_path=tmp_path / "writer.sqlite", control_store=control,
        manager_id="manager-a",
    )
    reader = AccountDomainSyncService(
        sqlite_path=tmp_path / "reader.sqlite", control_store=control,
        manager_id="manager-b",
    )
    publish_revision(
        writer,
        principal="alice",
        manifest=manifest(),
        object_definition={"id": "pg_123", "name": "Treasuries", "paths": ["CN/Futures/T"]},
    )
    assert writer.flush(principal="alice")["pending"] == 0
    reader.pull(principal="alice")
    rows = list_revision_manifests(
        reader.local,
        principal="alice",
        object_kind="product_group",
        object_ref="product-group:pg_123",
    )
    assert len(rows) == 1
    assert rows[0]["content_sha256"] == hashlib.sha256(b"definition").hexdigest()
    entity = reader.local.list_entities(
        principal="alice", entity_type=REVISION_ENTITY_TYPE,
    )[0]
    assert entity["payload"]["object_definition"]["paths"] == ["CN/Futures/T"]
    assert entity["payload"]["visibility"] == "private"


def test_public_revision_manifest_is_visible_to_other_principals(tmp_path):
    control = MemoryControlStore()
    writer = AccountDomainSyncService(
        sqlite_path=tmp_path / "writer.sqlite", control_store=control,
        manager_id="manager-a",
    )
    reader = AccountDomainSyncService(
        sqlite_path=tmp_path / "reader.sqlite", control_store=control,
        manager_id="manager-b",
    )
    public = manifest(
        object_kind="factor_family",
        object_ref="factor-family:public:public:Carry",
        revision_ref="factor-family-revision:" + "a" * 64,
        owner_ref="__public__",
        visibility="public",
        source_entity_type="factor_source_version",
    )
    publish_revision(writer, principal="__public__", manifest=public)
    writer.flush(principal="__public__")
    reader.pull(principal="bob")
    rows = list_revision_manifests(
        reader.local,
        principal="bob",
        object_kind="factor_family",
    )
    assert [row["object_ref"] for row in rows] == [public["object_ref"]]


def test_factor_source_revision_uses_the_shared_index_without_copying_source(
    tmp_path, monkeypatch,
):
    import settings as Settings

    database = tmp_path / "factor-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(database))
    source = "class Carry: pass\n"
    control = MemoryControlStore()
    writer = AccountDomainSyncService(
        sqlite_path=database, control_store=control, manager_id="factor-manager",
    )
    record_factor_formula_version(
        "public", "", "Carry", source,
        family_formula_fingerprint="c" * 64,
    )
    assert writer.flush(principal="__public__")["pending"] == 0
    reader = AccountDomainSyncService(
        sqlite_path=tmp_path / "factor-reader.sqlite", control_store=control,
        manager_id="reader-manager",
    )
    reader.pull(principal="bob")
    rows = list_revision_manifests(
        reader.local,
        principal="bob",
        object_kind="factor_family",
    )
    assert rows[0]["object_ref"] == "factor-family:public:public:Carry"
    assert rows[0]["content_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    stored = reader.local.list_entities(
        principal="bob", entity_type=REVISION_ENTITY_TYPE,
    )[0]["payload"]
    assert "source_code" not in stored
