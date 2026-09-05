import copy
import json
import sqlite3

import pytest
from tools.factors.formula_identity import freeze_factor_identity
from tools.migrations.repair_factor_catalog_sync import build_plan, build_acceptance_plan, apply_local
from server.manager.storage.account_domain.local import LocalAccountDomainStore


def factor(alias='F'):
    return freeze_factor_identity(owner_ref='alice', family_alias='F', factor_alias=alias,
        family_formula_fingerprint='a'*64, self_formula_fingerprint='b'*64, params={})


def row(payload, *, deleted=False, revision=4):
    return dict(principal='alice', entity_type='factor_param_config', entity_id='default:F',
        payload=payload, deleted=deleted, revision=revision, remote_revision=revision)


def test_explicit_deletion_is_preserved_and_migration_tombstone_restored():
    local = row({'resolved_factors': [factor()]})
    explicit = row({'reason': 'user delete'}, deleted=True)
    assert build_plan('alice', [local], [explicit], [], 'local')['rows'] == []
    migration = row({'discarded_reason': 'incompatible formula identity'}, deleted=True)
    plan = build_plan('alice', [local], [migration], [], 'local')
    assert plan['factor_count'] == 1
    assert not plan['rows'][0]['new_deleted']


def test_additional_authority_identities_are_never_overwritten():
    local = row({'resolved_factors': [factor()]})
    remote = row({'resolved_factors': [factor(), factor('F2')]})
    assert build_plan('alice', [local], [remote], [], 'local')['rows'] == []
    with pytest.raises(ValueError, match='discard local frozen'):
        build_acceptance_plan('alice', [remote], [local], 'public')


def test_empty_authoring_draft_accepts_only_migration_tombstone():
    local = row({'params_list': [{'x': 1}], 'resolved_factors': []})
    before = copy.deepcopy(local)
    remote = row({'discarded_reason': 'incompatible formula identity'}, deleted=True)
    plan = build_plan('alice', [local], [remote], [], 'local')
    assert plan['rows'][0]['new_deleted']
    assert local == before
    assert plan['factor_count'] == 0


def test_stale_local_snapshot_rolls_back_without_losing_outbox(tmp_path):
    db = tmp_path / 'mirror.sqlite'
    store = LocalAccountDomainStore(db)
    payload = {'resolved_factors': [factor()]}
    store.upsert_local(principal='alice', entity_type='factor_param_config', entity_id='default:F', manager_id='local', payload=payload)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE account_domain_entities SET remote_revision=4')
    local = row(payload)
    plan = build_plan('alice', [local], [], [], 'local')
    store.upsert_local(principal='alice', entity_type='factor_param_config', entity_id='default:F', manager_id='local', payload={**payload, 'user_edit': True})
    with pytest.raises(ValueError, match='precondition changed'):
        apply_local(db, plan, {'rows': [dict(entity_type='factor_param_config', entity_id='default:F', revision=10)]})
    with sqlite3.connect(db) as conn:
        assert json.loads(conn.execute("SELECT payload_json FROM account_domain_entities WHERE entity_type='factor_param_config'").fetchone()[0])['user_edit']
        assert conn.execute('SELECT count(*) FROM account_domain_outbox').fetchone()[0] == 1
