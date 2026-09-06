import io
from types import SimpleNamespace

import settings

from server.manager.services.factor_family_current import ensure_current_family
from server.manager.services import factor_source_hydration
from server.manager.storage.account_domain import AccountDomainSyncService
from server.services.factor_registry import get_custom_factor_instance, invalidate_custom_factor_cache
from tests.scripts.test_worktree_manager_account_domain_sync import MemoryControlStore
from tools.data.sqlite.factor_metadata import list_factor_summaries
from tools.data.sqlite.factor_source_store import upsert_factor_source, delete_factor_source, load_factor_source


def test_current_head_restores_exact_local_snapshot_without_network(tmp_path, monkeypatch):
    from tools.data.sqlite.factor_source_versions import record_factor_formula_version
    from tools.data.sqlite.factor_family_heads import family_head
    monkeypatch.setattr(settings, 'CACHE_DB_PATH', tmp_path / 'cache.sqlite')
    monkeypatch.setenv('FACTORTESTER_SERVER_ID', 'peer')
    source = ('from tools.factors import FactorFamily\nfrom tools.factors.FactorExpr import ConstExpr\n'
              'class SnapshotProbe(FactorFamily):\n    @staticmethod\n'
              '    def factor_expr():\n        return ConstExpr(1)\n')
    upsert_factor_source('custom', 'alice', 'SnapshotProbe', 'SnapshotProbe', source)
    head = family_head('custom', 'alice', 'SnapshotProbe')
    record_factor_formula_version('custom', 'alice', 'SnapshotProbe', source,
        family_formula_fingerprint=head['payload']['family_formula_fingerprint'])
    # A reconciled mutable copy differs while the exact authoritative bytes
    # are already present in this server's immutable version store.
    upsert_factor_source('custom', 'alice', 'SnapshotProbe', 'SnapshotProbe',
                         source + '\n', publish_family=False)
    monkeypatch.setattr(factor_source_hydration.FactorSourceHydrator, 'hydrate',
                        lambda *args, **kwargs: False)
    assert ensure_current_family(SimpleNamespace(server_id='peer'), 'custom',
                                 'SnapshotProbe', principal='alice')
    assert load_factor_source('custom', 'alice', 'SnapshotProbe') == source
    assert family_head('custom', 'alice', 'SnapshotProbe') == head


def test_family_head_controls_peer_detail_edit_delete_and_cache(tmp_path, monkeypatch):
    control = MemoryControlStore()
    left = AccountDomainSyncService(sqlite_path=tmp_path/'left.sqlite', control_store=control, manager_id='left')
    right = AccountDomainSyncService(sqlite_path=tmp_path/'right.sqlite', control_store=control, manager_id='right')
    monkeypatch.setattr(settings, 'CACHE_DIR', tmp_path)
    source = ('from tools.factors import FactorFamily\nfrom tools.parameters import DataColumnParam\n'
              'class Probe(FactorFamily):\n    @staticmethod\n    def factor_expr():\n'
              '        return DataColumnParam("P", default_value="CA") + 0\n')

    def select(sync):
        monkeypatch.setattr(settings, 'CACHE_DB_PATH', sync.local.path)
        monkeypatch.setenv('FACTORTESTER_SERVER_ID', sync.manager_id)

    def hydrate(sync, body):
        state = SimpleNamespace(server_id=sync.manager_id, account_domain_sync=sync,
                    prepare_object_download=lambda **kwargs: {'url': 'https://peer/source', 'bearer': 'test'})
        monkeypatch.setattr(factor_source_hydration, 'urlopen', lambda *a, **kw: io.BytesIO(body.encode()))
        return ensure_current_family(state, 'custom', 'Probe', principal='alice')

    select(left)
    upsert_factor_source('custom', 'alice', 'Probe', 'Probe', source)
    source = load_factor_source('custom', 'alice', 'Probe')
    first = get_custom_factor_instance('alice', 'Probe')
    left.flush(principal='alice'); right.pull(principal='alice')
    select(right)
    assert list_factor_summaries('custom', 'alice')[0]['factor_id'] == 'Probe'
    assert load_factor_source('custom', 'alice', 'Probe') is None
    assert hydrate(right, source)
    head = right.local.get_entity('alice', 'factor_family', 'custom:Probe')
    assert head['origin_manager_id'] == 'left'  # Receiving bytes is not an edit.
    updated_source = source.replace('+ 0', '+ 1')
    upsert_factor_source('custom', 'alice', 'Probe', 'Probe', updated_source)
    right.flush(principal='alice'); left.pull(principal='alice')
    select(left)
    assert hydrate(left, updated_source)
    second = get_custom_factor_instance('alice', 'Probe')
    assert first.expr.semantic_fingerprint() != second.expr.semantic_fingerprint()
    select(right)
    delete_factor_source('custom', 'alice', 'Probe')
    right.flush(principal='alice'); left.pull(principal='alice')
    select(left)
    assert list_factor_summaries('custom', 'alice') == []
    assert not hydrate(left, updated_source)
    left.reconcile_factor_sources('alice')
    assert list_factor_summaries('custom', 'alice') == []
    invalidate_custom_factor_cache('alice', 'Probe')


def test_factor_set_peer_delete_shadows_stale_authoring_row(tmp_path, monkeypatch):
    from server.modules.custom_factors.factor_set_registry import author_factor_set, unregister_factor_set
    from tests.server.test_factor_set_registry import _descriptor
    from tools.data.account_manage import get_factor_set, list_factor_sets
    monkeypatch.setattr(settings, 'CACHE_DIR', tmp_path)
    control = MemoryControlStore()
    left = AccountDomainSyncService(sqlite_path=tmp_path/'left.sqlite', control_store=control, manager_id='left')
    right = AccountDomainSyncService(sqlite_path=tmp_path/'right.sqlite', control_store=control, manager_id='right')
    monkeypatch.setattr(settings, 'CACHE_DB_PATH', left.local.path)
    value = author_factor_set('alice', {'set_id': 'probe', 'alias': 'Probe',
               'members': _descriptor()['manifest']['identity']['members']}, persist=True)
    ref = value['target_ref']
    assert any(row['entity_id'] == ref for row in left.local.pending(principal='alice'))
    left.flush(principal='alice'); right.pull(principal='alice')
    monkeypatch.setattr(settings, 'CACHE_DB_PATH', right.local.path)
    assert get_factor_set('alice', ref)['ref'] == ref
    assert unregister_factor_set('alice', ref)
    right.flush(principal='alice'); left.pull(principal='alice')
    monkeypatch.setattr(settings, 'CACHE_DB_PATH', left.local.path)
    assert get_factor_set('alice', ref) is None
    assert list_factor_sets('alice') == []
