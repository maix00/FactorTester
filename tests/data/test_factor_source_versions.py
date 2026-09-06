from __future__ import annotations

import pytest

import settings as Settings
from tools.data.sqlite import factor_source_versions


def _fingerprint(character: str) -> str:
    return character * 64


def test_history_manifest_and_bytes_survive_current_source_change(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from server.manager.objects.adapters.factor_source import FactorSourceOriginAdapter
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    from server.manager.storage.account_domain.factor_version_sync import backfill_factor_versions
    from tools.data.sqlite.db import connect_sqlite

    database = tmp_path / 'history.sqlite'
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', database)
    monkeypatch.setenv('FACTORTESTER_SERVER_ID', 'origin')
    old = factor_source_versions.record_factor_formula_version(
        'custom', 'alice', 'History', 'class History:\n    pass\n',
        family_formula_fingerprint='a' * 64,
    )
    mirror = LocalAccountDomainStore(database)
    rows = mirror.list_entities(principal='alice', entity_type='factor_source_version')
    assert len(rows) == 1
    assert rows[0]['payload']['source_sha256'] == old['source_sha256']
    assert 'source_code' not in rows[0]['payload']
    adapter = FactorSourceOriginAdapter(database=database, cache_root=tmp_path / 'cache')
    transfer = SimpleNamespace(object_id='alice:History', expected_sha256=old['source_sha256'],
                               expected_size=len(old['source_code'].encode()))
    assert adapter(transfer).read_text() == old['source_code']
    transfer.object_id = 'bob:History'
    with pytest.raises(FileNotFoundError):
        adapter(transfer)
    # Simulate a pre-migration version row with no version manifest.
    with connect_sqlite(database) as connection:
        connection.execute("DELETE FROM account_domain_entities WHERE entity_type='factor_source_version'")
        connection.execute("DELETE FROM account_domain_outbox WHERE entity_type='factor_source_version'")
    sync = SimpleNamespace(local=mirror, manager_id='origin')
    backfill_factor_versions(sync, 'bob')
    assert mirror.list_entities(principal='alice', entity_type='factor_source_version') == []
    backfill_factor_versions(sync, 'alice')
    assert len(mirror.list_entities(principal='alice', entity_type='factor_source_version')) == 1


def test_history_and_outbox_roll_back_together(monkeypatch, tmp_path):
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', tmp_path / 'rollback.sqlite')
    def fail(*args, **kwargs):
        raise RuntimeError('outbox unavailable')
    monkeypatch.setattr(LocalAccountDomainStore, 'upsert_local', fail)
    with pytest.raises(RuntimeError, match='outbox unavailable'):
        factor_source_versions.record_factor_formula_version(
            'custom', 'alice', 'History', 'class History:\n    pass\n',
            family_formula_fingerprint='a' * 64,
        )
    assert factor_source_versions.load_factor_formula_version('custom', 'alice', 'History', 'a'*64) is None


def test_version_list_uses_remote_metadata_without_source_bodies(monkeypatch, tmp_path):
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', tmp_path / 'metadata.sqlite')
    mirror = LocalAccountDomainStore(Settings.CACHE_DB_PATH)
    mirror.apply_remote({'principal':'alice','entity_type':'factor_source_version',
                         'entity_id':'custom:History:'+'a'*64+'@origin', 'revision':1,
                         'payload':{'source_kind':'custom','factor_id':'History',
                                    'family_formula_fingerprint':'a'*64,'source_sha256':'b'*64,
                                    'source_bytes':123,'created_at':1}})
    versions = factor_source_versions.list_factor_formula_versions('custom','alice','History')
    assert [v['family_formula_fingerprint'] for v in versions] == ['a'*64]
    assert all('source_code' not in v for v in versions)
    assert factor_source_versions.load_factor_formula_version('custom','alice','History','a'*64) is None

def test_formula_versions_roundtrip_without_git_identity(monkeypatch, tmp_path):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    source = "class Momentum(FactorFamily):\n    pass\n"

    saved = factor_source_versions.record_factor_formula_version(
        "public",
        "ignored-owner",
        "Momentum",
        source,
        family_formula_fingerprint=_fingerprint("a"),
        subject="create",
    )

    listed = factor_source_versions.list_factor_formula_versions(
        "public", "", "Momentum"
    )
    assert [item["family_formula_fingerprint"] for item in listed] == [
        _fingerprint("a")
    ]
    assert not ({"commit", "revision", "git_commit_sha"} & set(listed[0]))

    loaded = factor_source_versions.load_factor_formula_version(
        "public", "another-owner", "Momentum", _fingerprint("a")
    )
    assert loaded is not None
    assert loaded["source_code"] == source
    assert loaded["source_sha256"] == saved["source_sha256"]


def test_formula_version_deduplicates_source_changes_with_same_formula(
    monkeypatch, tmp_path
):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    first = "class Momentum(FactorFamily):\n    pass\n"
    later = "# prose-only change\nclass Momentum(FactorFamily):\n    pass\n"
    fingerprint = _fingerprint("b")

    factor_source_versions.record_factor_formula_version(
        "public",
        "",
        "Momentum",
        first,
        family_formula_fingerprint=fingerprint,
    )
    factor_source_versions.record_factor_formula_version(
        "public",
        "",
        "Momentum",
        later,
        family_formula_fingerprint=fingerprint,
    )

    loaded = factor_source_versions.load_factor_formula_version(
        "public", "", "Momentum", fingerprint
    )
    assert loaded is not None
    assert loaded["source_code"] == first


def test_custom_formula_version_keeps_owner_scope(monkeypatch, tmp_path):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    source = "class Momentum(FactorFamily):\n    pass\n"
    fingerprint = _fingerprint("c")

    factor_source_versions.record_factor_formula_version(
        "custom",
        "alice",
        "Momentum",
        source,
        family_formula_fingerprint=fingerprint,
    )

    assert (
        factor_source_versions.load_factor_formula_version(
            "custom", "bob", "Momentum", fingerprint
        )
        is None
    )
    assert factor_source_versions.load_factor_formula_version(
        "custom", "alice", "Momentum", fingerprint
    )["source_code"] == source


def test_formula_version_requires_full_semantic_fingerprint(monkeypatch, tmp_path):
    database = tmp_path / "factor-source-versions.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)

    with pytest.raises(ValueError, match="formula fingerprint"):
        factor_source_versions.record_factor_formula_version(
            "custom",
            "alice",
            "Momentum",
            "class Momentum(FactorFamily):\n    pass\n",
            family_formula_fingerprint="short",
        )


def test_upsert_factor_source_enqueues_fingerprint_into_outbox(monkeypatch, tmp_path):
    """Saving a factor source must put its family_formula_fingerprint into the
    factor_source outbox payload, so a receiving server can converge version
    history (source body is still pulled lazily on demand).

    This is the source-end half of the cross-server version-sync chain that
    keeps factor_family_formula_versions consistent across servers.
    """
    database = tmp_path / "factor-source.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    fingerprint = _fingerprint("c")

    import tools.data.sqlite.factor_source_store as store

    store.upsert_factor_source(
        "custom",
        "alice",
        "Momentum",
        "Momentum",
        "class Momentum(FactorFamily):\n    pass\n",
        family_formula_fingerprint=fingerprint,
    )

    # The enqueued factor_source row is held in the local outbox as an
    # account-domain entity.  Read it back and confirm the fingerprint travelled
    # with the payload.
    from server.manager.storage.account_domain.local import LocalAccountDomainStore

    local = LocalAccountDomainStore(str(database))
    pending = local.pending(principal="alice", limit=1000)
    rows = [item for item in pending if item["entity_type"] == "factor_source"]
    assert rows, "expected a pending factor_source outbox row after upsert"
    payload = rows[0]["payload"]
    assert payload["factor_id"] == "Momentum"
    assert payload["family_formula_fingerprint"] == fingerprint, (
        "factor_source outbox payload must carry family_formula_fingerprint so "
        "the receiving server can record version history"
    )
    # storage_server_id is set from FACTORTESTER_SERVER_ID and is empty in a
    # bare test run; the fingerprint (the cross-server convergence key) is what
    # matters here, not the origin label.
    assert "source_sha256" in payload
