import json
import io
import hashlib
import pytest
from types import SimpleNamespace

from server.manager.objects.adapters.strategy_revision import StrategyRevisionOriginAdapter
from server.manager.storage.account_domain import AccountDomainSyncService
from server.manager.storage.account_domain.strategy_sync import publish_strategy
from server.services.strategy_library import StrategyLibraryService
from tests.scripts.test_worktree_manager_account_domain_sync import MemoryControlStore
from tests.server.test_strategy_library import SOURCE, SOURCE_V2
from tools.data.sqlite.db import connect_sqlite


def test_strategy_create_edit_delete_converges_without_source_in_metadata(tmp_path):
    control = MemoryControlStore()
    left = AccountDomainSyncService(sqlite_path=tmp_path/'left.sqlite', control_store=control, manager_id='left')
    right = AccountDomainSyncService(sqlite_path=tmp_path/'right.sqlite', control_store=control, manager_id='right')
    author = StrategyLibraryService(left.local.path, account_provider=lambda: [])
    reader = StrategyLibraryService(right.local.path, account_provider=lambda: [])
    entry = author.create({'name': 'Probe', 'entrypoint': 'Demo', 'source_code': SOURCE}, principal='alice')['strategy']
    ref = entry['strategy_ref']
    publish_strategy(left, ref, 'alice')
    assert left.flush(principal='alice')['pending'] == 0
    right.pull(principal='alice')
    assert reader.list(principal='alice')['total'] == 1
    received = reader.get(ref, principal='alice')['strategy']
    assert received['current_revision']['revision_ref'] == entry['current_revision_ref']
    assert 'source_code' not in json.dumps(list(control.rows.values()))
    assert reader.store.get_revision(entry['current_revision_ref'])['source_code'] == ''
    metadata = right.local.get_entity('alice', 'strategy_revision', entry['current_revision_ref'])['payload']
    origin = StrategyRevisionOriginAdapter(database=left.local.path, cache_root=tmp_path/'bytes')
    path = origin(SimpleNamespace(object_id=entry['current_revision_ref'],
                                 expected_sha256=metadata['object_sha256'], expected_size=metadata['object_bytes']))
    assert json.loads(path.read_text())['source_code'] == SOURCE
    reader.source_loader = lambda revision_ref, *, principal: author.get_revision(
        ref, revision_ref, principal=principal, include_source=True)['revision']
    reader.update(ref, {'source_code': SOURCE_V2}, principal='alice')
    publish_strategy(right, ref, 'alice')
    right.flush(principal='alice')
    left.pull(principal='alice')
    assert len(author.get(ref, principal='alice')['strategy']['revisions']) == 2
    assert len(reader.get(ref, principal='alice')['strategy']['revisions']) == 2
    author.delete(ref, principal='alice')
    publish_strategy(left, ref, 'alice')
    left.flush(principal='alice')
    right.pull(principal='alice')
    assert reader.list(principal='alice')['total'] == 0


def test_disconnected_revision_numbers_do_not_block_other_objects(tmp_path):
    control = MemoryControlStore()
    left = AccountDomainSyncService(sqlite_path=tmp_path/'left.sqlite', control_store=control, manager_id='left')
    right = AccountDomainSyncService(sqlite_path=tmp_path/'right.sqlite', control_store=control, manager_id='right')
    author = StrategyLibraryService(left.local.path, account_provider=lambda: [])
    reader = StrategyLibraryService(right.local.path, account_provider=lambda: [])
    ref = author.create({'name': 'Concurrent', 'entrypoint': 'Demo', 'source_code': SOURCE}, principal='alice')['strategy']['strategy_ref']
    publish_strategy(left, ref, 'alice')
    left.flush(principal='alice')
    right.pull(principal='alice')
    reader.source_loader = lambda revision_ref, *, principal: author.get_revision(
        ref, revision_ref, principal=principal, include_source=True)['revision']
    reader.update(ref, {'source_code': SOURCE_V2}, principal='alice')
    author.update(ref, {'source_code': SOURCE_V2 + '\n# independent edit\n'}, principal='alice')
    publish_strategy(left, ref, 'alice')
    publish_strategy(right, ref, 'alice')
    left.flush(principal='alice')
    right.flush(principal='alice')
    left.pull(principal='alice')
    right.pull(principal='alice')
    assert len(author.store.list_revisions(ref)) == 3
    assert len(reader.store.list_revisions(ref)) == 3
    assert sorted(row['revision_number'] for row in author.store.list_revisions(ref)) == [1, 2, 2]


def test_legacy_revision_counter_migration_preserves_rows(tmp_path):
    from server.services.strategy_library.schema import REVISION_COLUMNS, migrate_revision_identity
    database = tmp_path/'legacy.sqlite'
    with connect_sqlite(database) as db:
        db.execute(f'CREATE TABLE strategy_library_revisions ({REVISION_COLUMNS}, UNIQUE(strategy_ref, revision_number))')
        row = ('revision:a', 'strategy:a', 1, 'digest', SOURCE, 'Demo', '[]', '{}', 'alice', 123)
        db.execute('INSERT INTO strategy_library_revisions VALUES (?,?,?,?,?,?,?,?,?,?)', row)
    with connect_sqlite(database) as db:
        migrate_revision_identity(db)
        assert tuple(db.execute('SELECT * FROM strategy_library_revisions').fetchone()) == row
        db.execute('INSERT INTO strategy_library_revisions VALUES (?,?,?,?,?,?,?,?,?,?)', ('revision:b', *row[1:]))
    with connect_sqlite(database) as db:
        migrate_revision_identity(db)
        assert db.execute('SELECT count(*) FROM strategy_library_revisions').fetchone()[0] == 2


def test_revision_hydration_checks_access_and_bytes_before_persisting(tmp_path, monkeypatch):
    from server.manager.services import strategy_revision_hydration as hydration
    from server.manager.storage.account_domain.strategy_sync import revision_bytes
    control = MemoryControlStore()
    left = AccountDomainSyncService(sqlite_path=tmp_path/'left.sqlite', control_store=control, manager_id='left')
    right = AccountDomainSyncService(sqlite_path=tmp_path/'right.sqlite', control_store=control, manager_id='right')
    author = StrategyLibraryService(left.local.path, account_provider=lambda: [])
    reader = StrategyLibraryService(right.local.path, account_provider=lambda: [])
    entry = author.create({'name': 'Hydrate', 'entrypoint': 'Demo', 'source_code': SOURCE}, principal='alice')['strategy']
    revision_ref = entry['current_revision_ref']
    publish_strategy(left, entry['strategy_ref'], 'alice')
    left.flush(principal='alice')
    right.pull(principal='alice')
    raw = revision_bytes(author.store.get_revision(revision_ref))
    requests = []
    def prepare(**kwargs):
        requests.append(kwargs)
        return {'url': 'https://origin/object', 'bearer': 'test-ticket'}
    state = SimpleNamespace(strategy_library=reader, account_domain_sync=right,
                            prepare_object_download=prepare, server_id='right')
    load = hydration.StrategyRevisionHydrator(state)
    with pytest.raises(PermissionError):
        load(revision_ref, principal='bob')
    assert not requests
    monkeypatch.setattr(hydration, 'loopback_client_access', lambda url: (url, None))
    monkeypatch.setattr(hydration, 'urlopen', lambda *args, **kwargs: io.BytesIO(b'bad'))
    with pytest.raises(ValueError, match='hash mismatch'):
        load(revision_ref, principal='alice')
    assert reader.store.get_revision(revision_ref)['source_code'] == ''
    monkeypatch.setattr(hydration, 'urlopen', lambda *args, **kwargs: io.BytesIO(raw))
    assert load(revision_ref, principal='alice')['source_code'] == SOURCE
    assert requests[-1]['expected_sha256'] == hashlib.sha256(raw).hexdigest()
    assert requests[-1]['object_kind'] == 'strategy_revision'
