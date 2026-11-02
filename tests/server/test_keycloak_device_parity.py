from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.migrations.keycloak_device_parity import verify_device_policy_parity
from scripts.migrations.keycloak_device_stage import review
from server.identity.keycloak_authorization import AuthorizationUnavailable

ISSUER = 'https://id.example/realms/test'
KEY = {'kty': 'EC', 'crv': 'P-256', 'x': 'A' * 43, 'y': 'A' * 43}


class Adapter:
    def __init__(self):
        self.users = [{'id': name+'-subject', 'username': name, 'enabled': True,
                       'attributes': {'tr_identity_id': [name+'-id'],
                                      'legacy_username': ['org@'+name+'@123']}}
                      for name in ('alice', 'bob', 'carol')]

    def _page(self, path, **_kwargs):
        assert path == 'users'
        return deepcopy(self.users)

    def group_tree_members(self, path, **_kwargs):
        assert path == '/traderesearch/organizations'
        return [SimpleNamespace(subject=user['id'], enabled=user['enabled']) for user in self.users]

    def user_by_identity_id(self, identity):
        return next(user for user in self.users if user['attributes']['tr_identity_id'] == [identity])


def fixture():
    snapshot = {'server_id': 'lan', 'devices': [
        {'device_id': f'device-1234567890{n:02}', 'username': 'org@alice@123',
         'public_key': KEY, 'enabled': n != 2, 'source_server_id': 'other' if n == 3 else 'lan'}
        for n in range(4)]}
    directory = {'accounts': [{'username': 'org@alice@123', 'tr_identity_id': 'alice-id',
                               'keycloak_subject': 'alice-subject', 'active': True}]}
    from scripts.migrations.keycloak_device_inventory import plan
    entries = plan(snapshot, directory, manager_id='lan')['entries']
    refs = [row['resource_ref'] for row in entries if row['status'] != 'outside_manager']
    class Evaluator:
        adapter = Adapter()
        calls = []
        def evaluate(self, identity, *, candidates):
            self.calls.append((identity, candidates))
            return {(kind, ref, 'use'): identity == 'alice-id' and ref in refs[:2]
                    for kind, ref, _scopes in candidates}
    evaluator = Evaluator()
    return dict(reviewed=review(snapshot, directory, manager_id='lan', issuer=ISSUER),
                live_snapshot=lambda: deepcopy(snapshot), live_directory=lambda: deepcopy(directory),
                manager_id='lan', issuer=ISSUER, evaluator=evaluator,
                resource_absent=lambda ref: ref == refs[2]), refs, snapshot, directory


def test_parity_covers_non_owners_denied_missing_resources_and_scoped_mirrors():
    args, refs, _, _ = fixture()
    receipt = verify_device_policy_parity(**args)
    assert receipt == dict(schema='tr-device-parity-v1', plan_sha256=args['reviewed']['sha256'],
                          manager_id='lan', users=3, devices=3, outside_manager=1,
                          decisions=9, allowed=2, denied=7, missing_denied_resources=1, cutover_ready=False)
    assert {identity for identity, _ in args['evaluator'].calls} == {'alice-id', 'bob-id', 'carol-id'}
    assert all(len(candidates) == 2 for _, candidates in args['evaluator'].calls)


@pytest.mark.parametrize('bad', ['other-user', 'disabled-device', 'missing-decision', 'revoked-owner'])
def test_parity_rejects_overgrants_omissions_and_revocations_without_repair(bad):
    args, refs, _, _ = fixture()
    original = args['evaluator'].evaluate
    if bad == 'disabled-device': args['resource_absent'] = lambda _ref: False
    def evaluate(identity, *, candidates):
        rows = original(identity, candidates=candidates)
        if bad == 'other-user': rows[('device', refs[0], 'use')] = True
        elif bad == 'disabled-device': rows[('device', refs[2], 'use')] = identity == 'alice-id'
        elif bad == 'missing-decision': rows.pop(next(iter(rows)))
        elif bad == 'revoked-owner': rows[('device', refs[0], 'use')] = False
        return rows
    args['evaluator'].evaluate = evaluate
    with pytest.raises(AuthorizationUnavailable, match='decisions differ|coverage differs'):
        verify_device_policy_parity(**args)


def test_grant_resource_must_exist_and_mismatched_subject_is_rejected():
    args, _, _, directory = fixture()
    args['resource_absent'] = lambda _ref: True
    with pytest.raises(AuthorizationUnavailable, match='grant is missing'):
        verify_device_policy_parity(**args)
    args, _, _, directory = fixture()
    directory['accounts'][0]['keycloak_subject'] = 'new-subject'
    args['reviewed'] = review(args['live_snapshot'](), directory, manager_id='lan', issuer=ISSUER)
    with pytest.raises(AuthorizationUnavailable, match='owner subject differs'):
        verify_device_policy_parity(**args)


@pytest.mark.parametrize('change', ['same-count-other-device', 'new-user', 'resource-created'])
def test_changes_during_check_invalidate_receipt(change):
    args, refs, snapshot, _ = fixture()
    original = args['evaluator'].evaluate
    def evaluate(identity, *, candidates):
        rows = original(identity, candidates=candidates)
        if change == 'same-count-other-device': snapshot['devices'][0]['device_id'] = 'device-different-123456'
        elif change == 'new-user' and identity == 'alice-id':
            args['evaluator'].adapter.users.append({'id':'new-subject','username':'new','enabled':True,
                'attributes':{'tr_identity_id':['new-id']}})
        return rows
    args['evaluator'].evaluate = evaluate
    if change != 'resource-created': args['resource_absent'] = lambda ref: ref == refs[2]
    else: args['resource_absent'] = lambda ref: ref == refs[2] and not args['evaluator'].calls
    with pytest.raises(AuthorizationUnavailable, match='changed'):
        verify_device_policy_parity(**args)
