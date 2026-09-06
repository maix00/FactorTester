import pytest
import settings

from server.manager.storage.account_domain.local import LocalAccountDomainStore
from tools.data.sqlite.account_manager import product_category, product_group


@pytest.mark.parametrize('kind,module,load,save', [
    ('product_category', product_category, 'load_product_categories', 'save_product_categories'),
    ('product_group', product_group, 'load_product_groups', 'save_product_groups'),
])
def test_authoring_reads_peer_updates_and_tombstones(tmp_path, monkeypatch, kind, module, load, save):
    database = tmp_path / 'catalog.sqlite'
    monkeypatch.setattr(settings, 'CACHE_DB_PATH', database)
    getattr(module, save)('alice', [{'id': 'one', 'name': 'Old'}])
    store = LocalAccountDomainStore(database)
    for identifier, name in [('one', 'Peer edit'), ('two', 'Peer create')]:
        store.upsert_local(principal='alice', entity_type=kind, entity_id=identifier,
                           payload={'id': identifier, 'name': name}, manager_id='peer')
    assert getattr(module, load)('alice') == [
        {'id': 'one', 'name': 'Peer edit'}, {'id': 'two', 'name': 'Peer create'},
    ]
    assert getattr(module, load)('bob') == []
    store.upsert_local(principal='alice', entity_type=kind, entity_id='one',
                       payload={}, manager_id='peer', deleted=True)
    assert getattr(module, load)('alice') == [{'id': 'two', 'name': 'Peer create'}]
