from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from server.identity.request_context import (
    bind_verified_identity, current_verified_identity, identity_request,
)
from server.identity.keycloak_authorization import (
    keycloak_request_identity, keycloak_resource_uri,
)
from server.services.strategy_library.permissions import access_for, access_many
from server.services.strategy_library import StrategyLibraryService


def session(name='alice'):
    return {'username': name, 'keycloak_subject': 'subject-' + name,
            'keycloak_issuer': 'https://identity.invalid/realms/trade'}


def test_manager_identity_lives_for_one_request_and_requires_verified_claims():
    with identity_request():
        bind_verified_identity('verified-token', session())
        assert keycloak_request_identity().username == 'alice'
        with identity_request():
            assert keycloak_request_identity() is None
            bind_verified_identity('agent-token', {'username': 'alice'})
            assert keycloak_request_identity() is None
        assert keycloak_request_identity().subject == 'subject-alice'
    assert keycloak_request_identity() is None


def test_request_identity_does_not_cross_threads():
    with identity_request():
        bind_verified_identity('verified-token', session())
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(current_verified_identity).result() is None


def test_local_owner_visibility_descendants_and_shares_never_grant_access(monkeypatch):
    monkeypatch.setattr('server.identity.keycloak_authorization.keycloak_authorized_many',
                        lambda *_args, **_kwargs: {})
    with identity_request():
        bind_verified_identity('verified-token', session())
        for owner in ['alice', 'child']:
            result = access_for({'strategy_ref': 's1', 'owner_ref': owner, 'visibility': 'public'},
                                principal='alice', shared_principals={'alice'},
                                subordinate_users={'child'})
            assert not any(result[key] for key in ['can_view', 'can_edit', 'can_delete', 'can_share'])


def test_granted_strategy_with_no_local_share_is_authorized_and_batches_are_bounded(monkeypatch):
    calls = []
    def authorize(token, *, permissions):
        assert token == 'verified-token'
        calls.append(len(permissions))
        return {(uri, scope): scope == 'read' for uri, name, scope in permissions}
    monkeypatch.setattr('server.identity.keycloak_authorization.keycloak_authorized_many', authorize)
    entries = [{'strategy_ref': f's{i}', 'owner_ref': 'other'} for i in range(100)]
    with identity_request():
        bind_verified_identity('verified-token', session())
        access = access_many(entries, principal='alice', subordinate_users=set())
    assert calls == [256, 144]
    assert all(value['can_view'] and not value['can_edit'] for value in access.values())


def test_visible_pagination_counts_authorized_rows_not_old_acl_candidates(tmp_path, monkeypatch):
    service = StrategyLibraryService(tmp_path / 'strategies.sqlite', account_provider=lambda: [])
    def candidates(**kwargs):
        rows = [{'entry': {'strategy_ref': f's{i}', 'owner_ref': 'other', 'current_revision_ref': 'r'},
                 'revision': {'revision_ref': 'r', 'source_sha256': 'hash'}} for i in range(205)]
        start = (kwargs['page'] - 1) * kwargs['limit']
        return rows[start:start + kwargs['limit']], len(rows)
    service.store.list_visible_entries = candidates
    allowed = {keycloak_resource_uri('strategy', f's{i}') for i in [5, 103, 204]}
    def authorize(token, *, permissions):
        return {(uri, scope): uri in allowed and scope == 'read' for uri, name, scope in permissions}
    monkeypatch.setattr('server.identity.keycloak_authorization.keycloak_authorized_many', authorize)
    with identity_request():
        bind_verified_identity('verified-token', session())
        result = service.list(principal='alice', scope='all', page=2, limit=2)
    assert result['total'] == 3
    assert [row['strategy_ref'] for row in result['items']] == ['s204']
    assert all('source_code' not in row['current_revision'] for row in result['items'])


def test_old_share_mutations_are_not_a_permission_authority(tmp_path):
    service = StrategyLibraryService(tmp_path / 'strategies.sqlite')
    with pytest.raises(PermissionError, match='Keycloak'):
        service.grant('s1', 'bob', principal='alice')
    with pytest.raises(PermissionError, match='Keycloak'):
        service.revoke('s1', 'bob', principal='alice')
    with pytest.raises(PermissionError, match='verified Keycloak'):
        service.create({}, principal='alice')


def test_metadata_store_does_not_create_or_depend_on_legacy_acl(tmp_path):
    import sqlite3
    from server.services.strategy_library.store import StrategyLibraryStore
    path = tmp_path / 'metadata.sqlite'
    store = StrategyLibraryStore(path)
    refs = store.create(owner_ref='alice', name='A', description='', visibility='private',
                        source_sha256='hash', source_code='class A: pass', entrypoint='A',
                        hooks=[], requirements={}, created_by='alice')
    rows, total = store.list_visible_entries(principal='bob', scope='all',
                                              subordinate_users=set())
    assert total == 1 and rows[0]['entry']['strategy_ref'] == refs['strategy_ref']
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='strategy_library_shares'").fetchall() == []
    assert not hasattr(store, 'grant') and not hasattr(store, 'shares')
