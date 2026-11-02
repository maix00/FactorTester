import pytest
import settings
from server.manager.storage.account_domain.local import LocalAccountDomainStore
from tools.data.sqlite.factor_family_heads import legacy_source_manifests


@pytest.mark.parametrize('kind,owner', [('public', ''), ('custom', 'alice')])
@pytest.mark.parametrize('deleted', [False, True])
def test_current_head_wins_over_later_provider(tmp_path, monkeypatch, kind, owner, deleted):
    monkeypatch.setattr(settings, 'CACHE_DB_PATH', tmp_path / 'db.sqlite')
    store = LocalAccountDomainStore(settings.CACHE_DB_PATH)
    principal = owner or '__public__'
    payload = {'source_kind': kind, 'owner_username': owner, 'factor_id': 'Mm'}
    store.upsert_local(principal=principal, entity_type='factor_family',
        entity_id=kind + ':Mm', payload=payload, manager_id='a', deleted=deleted)
    providers = [{'principal': principal, 'payload': payload, 'remote_revision': 999}]
    assert list(legacy_source_manifests(providers, kind, owner)) == []
    # No head for another alias: retain legacy metadata without requiring bytes.
    legacy = {**payload, 'factor_id': 'Legacy'}
    assert list(legacy_source_manifests([{'principal': principal, 'payload': legacy}], kind, owner)) == [legacy]
    assert list(legacy_source_manifests([{'principal': principal, 'payload': legacy, 'deleted': True}], kind, owner)) == []
    assert list(legacy_source_manifests([{'principal': principal, 'payload': {**legacy, 'owner_username': 'other'}}], kind, owner)) == []


def test_same_alias_tombstone_is_owner_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'CACHE_DB_PATH', tmp_path / 'db.sqlite')
    store = LocalAccountDomainStore(settings.CACHE_DB_PATH)
    store.upsert_local(principal='alice', entity_type='factor_family',
        entity_id='custom:Mm', payload={}, manager_id='a', deleted=True)
    payload = {'source_kind': 'custom', 'factor_id': 'Mm', 'owner_username': 'bob'}
    assert list(legacy_source_manifests([{'principal': 'bob', 'payload': payload}], 'custom', 'bob')) == [payload]


@pytest.mark.parametrize('deleted', [False, True])
def test_couchdb_catalog_applies_committed_owner_head(tmp_path, monkeypatch, deleted):
    from tools.data.sqlite.factor_metadata import list_factor_summaries
    from server.jobs.storage.couchdb_library_reader import CouchDBLibraryReader
    from server.jobs.storage import couchdb_reports

    monkeypatch.setattr(settings, 'CACHE_DB_PATH', tmp_path / 'db.sqlite')
    monkeypatch.setenv('TRADERESEARCH_COUCHDB_AUTHORITY', '1')
    monkeypatch.setenv('FACTORTESTER_COUCHDB_URL', 'http://unused.invalid')
    monkeypatch.setattr(couchdb_reports, 'CouchDBObjectStore', lambda *args: object())
    monkeypatch.setattr(CouchDBLibraryReader, 'factor_families', lambda *args: [
        {'owner_ref': 'alice', 'factor_id': 'F', 'catalog': {'description': 'stale'}},
    ])
    monkeypatch.setattr(CouchDBLibraryReader, 'factor_family_heads', lambda *args: [])
    store = LocalAccountDomainStore(settings.CACHE_DB_PATH)
    for owner in ('alice', 'bob'):
        store.upsert_local(principal=owner, entity_type='factor_family',
            entity_id='custom:F', payload={'factor_id': 'F', 'description': owner},
            manager_id='a', deleted=deleted if owner == 'alice' else False)
    values = list_factor_summaries('custom', 'alice')
    assert values == ([] if deleted else [
        {'factor_id': 'F', 'description': 'alice', 'owner_username': 'alice'},
    ])
    # Explicit snapshot reads retain the CouchDB snapshot without overlay.
    assert list_factor_summaries('custom', 'alice', include_heads=False)[0]['description'] == 'stale'
