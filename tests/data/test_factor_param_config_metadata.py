from __future__ import annotations

import settings as Settings
import pytest
from tools.data.account_manage import (
    delete_factor_family_configs,
    list_factor_family_dependency_configs,
    load_factor_param_config,
    save_factor_param_config,
)


def test_materialized_configuration_and_outbox_rollback_together(monkeypatch, tmp_path):
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    from tools.data.sqlite.db import connect_sqlite
    database = tmp_path/'atomic.sqlite'
    monkeypatch.setattr(Settings, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', database)
    original = LocalAccountDomainStore.upsert_local
    def fail_after_outbox(self, **kwargs):
        original(self, **kwargs)
        raise RuntimeError('simulated failure before commit')
    monkeypatch.setattr(LocalAccountDomainStore, 'upsert_local', fail_after_outbox)
    with pytest.raises(RuntimeError, match='before commit'):
        save_factor_param_config('alice', 'Family', [], resolved_factors=[])
    assert load_factor_param_config('alice', 'Family') is None
    with connect_sqlite(database, readonly=True) as db:
        assert db.execute('SELECT count(*) FROM account_domain_outbox').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM account_domain_entities').fetchone()[0] == 0
    monkeypatch.setattr(LocalAccountDomainStore, 'upsert_local', original)
    value = save_factor_param_config('alice', 'Family', [], resolved_factors=[])
    assert load_factor_param_config('alice', 'Family') == value
    assert LocalAccountDomainStore(database).get_entity('alice', 'factor_param_config', 'default:Family')['payload']['resolved_factors'] == []


def test_received_factor_configuration_can_be_deleted_without_authored_row(monkeypatch, tmp_path):
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    from server.modules.custom_factors import factor_library_store
    database = tmp_path/'receiver.sqlite'
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', database)
    mirror = LocalAccountDomainStore(database)
    mirror.upsert_local(principal='alice', entity_type='factor_param_config',
                        entity_id='default:Family', payload={'resolved_factors': []}, manager_id='origin')
    assert factor_library_store.delete_factor_param_config('alice', 'Family')
    assert mirror.get_entity('alice', 'factor_param_config', 'default:Family')['deleted']
    assert factor_library_store.load_factor_param_config('alice', 'Family') is None
    assert not factor_library_store.delete_factor_param_config('alice', 'Family')


def test_factor_param_config_preserves_research_metadata(monkeypatch, tmp_path):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)

    saved = save_factor_param_config(
        "alice",
        "MmRet",
        [{"N": "10d", "$F": "1d"}],
        "research-core8",
        metadata={
            "note": "sample-in good, oos weak",
            "research_report": "/tmp/report.md",
            "product_group_paths": ["Product/Futures/CNFutures/日夜盘/日盘/_products/AP.CZC"],
        },
    )

    assert saved["metadata"]["note"] == "sample-in good, oos weak"
    loaded = load_factor_param_config("alice", "MmRet", "research-core8")
    assert loaded is not None
    assert loaded["metadata"] == saved["metadata"]


def test_delete_factor_family_configs_cascades_rows_across_scopes(monkeypatch, tmp_path):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)
    save_factor_param_config("alice", "MmRet", [{"N": "10d"}], "default")
    save_factor_param_config("alice", "MmRet", [{"N": "20d"}, {"N": "30d"}], "night")
    save_factor_param_config("alice", "MmOther", [{"N": "5d"}], "default")
    save_factor_param_config("bob", "MmRet", [{"N": "60d"}], "default")

    deleted = delete_factor_family_configs("MmRet", username="alice")

    assert deleted == {"config_count": 2, "factor_count": 3}
    assert load_factor_param_config("alice", "MmRet", "default") is None
    assert load_factor_param_config("alice", "MmRet", "night") is None
    assert load_factor_param_config("alice", "MmOther", "default") is not None
    assert load_factor_param_config("bob", "MmRet", "default") is not None


def test_factor_family_dependency_scan_finds_nested_frozen_factors(
    monkeypatch, tmp_path,
):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)
    nested = {
        "schema_version": 2,
        "ref": "factor:v2:nested",
        "alias": "Inner|N:5d",
        "owner_ref": "principal:alice",
        "identity": {"family_alias": "Inner"},
    }
    save_factor_param_config(
        "alice", "Outer", [{"P": nested["ref"]}], "default",
        metadata={"factor_dependencies": [nested]},
    )

    assert list_factor_family_dependency_configs(
        "Inner", owner_ref="alice",
    ) == [{
        "username": "alice",
        "scope_key": "default",
        "outer_family_alias": "Outer",
        "factor_refs": ["factor:v2:nested"],
    }]


def test_family_delete_cascades_received_configs_and_syncs_back(monkeypatch, tmp_path):
    from server.manager.storage.account_domain import AccountDomainSyncService
    from tests.scripts.test_worktree_manager_account_domain_sync import MemoryControlStore
    from tools.factors.formula_identity import freeze_factor_identity
    from tools.data.sqlite.db import connect_sqlite

    control = MemoryControlStore()
    left = AccountDomainSyncService(sqlite_path=tmp_path/'left.sqlite', control_store=control, manager_id='left')
    right = AccountDomainSyncService(sqlite_path=tmp_path/'right.sqlite', control_store=control, manager_id='right')
    monkeypatch.setattr(Settings, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', left.local.path)
    monkeypatch.setenv('FACTORTESTER_SERVER_ID', 'left')
    expected = {}
    for owner, family, scope in [('alice', 'CA', 'default'), ('alice', 'CA', 'research:night'),
                                  ('alice', 'Other', 'default'), ('bob', 'CA', 'default')]:
        factor = freeze_factor_identity(owner_ref=owner, family_alias=family, factor_alias=family+scope,
            family_formula_fingerprint='a'*64, self_formula_fingerprint='b'*64, params={'scope': scope})
        expected[(owner, family, scope)] = factor['ref']
        save_factor_param_config(owner, family, [{'scope': scope}], scope, resolved_factors=[factor])
    for owner in ['alice', 'bob']:
        left.flush(principal=owner)
        right.pull(principal=owner)
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', right.local.path)
    monkeypatch.setenv('FACTORTESTER_SERVER_ID', 'right')
    assert len(right.local.factor_catalog('alice')) == 3
    assert delete_factor_family_configs('CA', username='alice') == {'config_count': 2, 'factor_count': 2}
    assert delete_factor_family_configs('CA', username='alice') == {'config_count': 0, 'factor_count': 0}
    right.flush(principal='alice')
    left.pull(principal='alice')
    for store in [left.local, right.local]:
        assert {r['factor_ref'] for r in store.factor_catalog('alice')} == {expected[('alice', 'Other', 'default')]}
        assert {r['factor_ref'] for r in store.factor_catalog('bob')} == {expected[('bob', 'CA', 'default')]}
        assert store.get_entity('alice', 'factor_param_config', 'research:night:CA')['deleted']
    # Replaying synchronization must preserve the same ref sets.
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', left.local.path)
    monkeypatch.setenv('FACTORTESTER_SERVER_ID', 'left')
    left.reconcile_factor_catalog('alice', force=True)
    left.flush(principal='alice'); right.pull(principal='alice')
    assert {r['factor_ref'] for r in right.local.factor_catalog('alice')} == {expected[('alice', 'Other', 'default')]}
    with connect_sqlite(right.local.path, readonly=True) as db:
        assert db.execute('SELECT count(*) FROM account_factor_param_configs').fetchone()[0] == 0


def test_family_delete_rolls_back_when_tombstone_fails(monkeypatch, tmp_path):
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    monkeypatch.setattr(Settings, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', tmp_path/'rollback.sqlite')
    saved = save_factor_param_config('alice', 'CA', [{'N': 1}])
    original = LocalAccountDomainStore.upsert_local
    def fail(self, **kwargs):
        original(self, **kwargs)
        raise RuntimeError('tombstone failure')
    monkeypatch.setattr(LocalAccountDomainStore, 'upsert_local', fail)
    with pytest.raises(RuntimeError, match='tombstone failure'):
        delete_factor_family_configs('CA', username='alice')
    assert load_factor_param_config('alice', 'CA') == saved


@pytest.mark.parametrize('public', [False, True])
def test_deleted_family_retry_cleans_residual_registrations(monkeypatch, public):
    from flask import Flask
    from server.modules.custom_factors import crud_routes as routes
    app = Flask(__name__)
    calls = []
    monkeypatch.setattr(routes, '_username', lambda: 'alice')
    monkeypatch.setattr(routes, '_current_user_is_super_admin', lambda: True)
    monkeypatch.setattr(routes, 'load_factor_source', lambda *a: None)
    monkeypatch.setattr(routes, 'load_public_factor_source', lambda *a: None)
    monkeypatch.setattr(routes, 'family_head', lambda *a: {'deleted': True})
    monkeypatch.setattr(routes, 'list_factor_family_dependency_configs', lambda *a, **k: [])
    monkeypatch.setattr(routes, 'delete_factor_family_configs',
                        lambda *a, **k: calls.append((a, k)) or {'config_count': 1, 'factor_count': 1})
    monkeypatch.setattr(routes, 'invalidate_custom_factor_cache', lambda *a: None)
    monkeypatch.setattr(routes, 'invalidate_factor_family_cache', lambda *a: None)
    method = routes.api_delete_public_factor if public else routes.api_delete_factor
    with app.test_request_context():
        response = method.__wrapped__('CA')
        assert response.get_json()['cascade_deleted']['factor_count'] == 1
        assert calls == [(('CA',), {} if public else {'username': 'alice'})]
        monkeypatch.setattr(routes, 'family_head', lambda *a: None)
        assert method.__wrapped__('CA')[1] == 404
    assert len(calls) == 1
