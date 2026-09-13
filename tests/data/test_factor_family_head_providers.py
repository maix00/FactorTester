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
