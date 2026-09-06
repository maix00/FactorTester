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
