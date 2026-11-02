"""Signed peer report read against two disposable Keycloak realms and CouchDB.

No existing Manager, user or database is modified. Manager admission and
report UMA checks are real; peer trust bindings and certificates are isolated
test configuration. The browser-to-source gateway is covered separately.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
import threading
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from scripts.test.couchdb_sandbox import couchdb_sandbox
from scripts.test.keycloak_cross_realm_smoke import Sandbox, denied, run
from scripts.test.research_couchdb_publication_smoke import value
from server.identity.request_context import bind_verified_identity, identity_request
from server.jobs.storage.couchdb_reports import CouchDBObjectStore
from server.manager import runtime as manager
from server.manager.http.peer_handler import peer_control_handler
from server.manager.services.local_report_publication import LocalReportPublicationService
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey
from tools.cli.release.research_reporting.public_research.object_uploads import projection_hash


def exercise(*, couch, **case):
    from server.identity import federated_peer_delegation as delegation, server_admission
    sandbox, realm = case['sandbox'], case['target_realm']
    client_id, client_uuid = 'chain-b-client', case['target_client_uuid']
    recipient = case['alice_target']
    owner_password = secrets.token_urlsafe(24)
    client_config = sandbox.api('GET', realm, 'clients/' + client_uuid)
    sandbox.api('PUT', realm, 'clients/' + client_uuid, {**client_config, 'directAccessGrantsEnabled': True})
    sandbox.api('POST', realm, 'users', {'username': 'report-owner', 'enabled': True, 'emailVerified': True,
        'firstName': 'Temporary', 'lastName': 'Owner', 'email': 'report-owner@example.invalid',
        'attributes': {'tr_identity_id': ['stable-report-owner']},
        'credentials': [{'type': 'password', 'value': owner_password, 'temporary': False}]})
    owner = sandbox.find(realm, 'users?username=report-owner&exact=true', 'report-owner', field='username')
    sandbox.api('POST', realm, 'clients/' + client_uuid + '/roles', {'name': 'public_server:login'})
    public_role = sandbox.api('GET', realm, 'clients/' + client_uuid + '/roles/public_server%3Alogin')
    role_path = 'users/' + recipient['id'] + '/role-mappings/clients/' + client_uuid
    sandbox.api('POST', realm, role_path, [public_role])
    sandbox.api('POST', realm, 'users/' + owner['id'] + '/role-mappings/clients/' + client_uuid, [public_role])
    settings = {'issuer': case['target_issuer'], 'realm': realm, 'base_url': sandbox.base,
                'backchannel_base_url': sandbox.base, 'client_id': client_id, 'roles_client_id': client_id,
                'audience': client_id, 'client_secret': case['target_secret'], 'secret_path': '',
                'authz_client_id': client_id, 'authz_client_secret': case['target_secret']}
    binding = delegation.PeerBinding('source-manager', '', case['source_issuer'], 'chain-a-client',
        case['target_issuer'], 'chain-a-client', case['source_resource'], case['target_resource'], 'access-chain-b')
    def clients(_base, requested_realm, _client, **_kwargs):
        return case['source_introspection'] if requested_realm == case['source_realm'] else case['target_client']
    class Directory:
        def _get(self, path): return sandbox.api('GET', realm, path)
        def user_by_identity_id(self, stable):
            users = [sandbox.api('GET', realm, 'users/' + user['id']) for user in (owner, recipient)]
            matched = [user for user in users if (user.get('attributes') or {}).get('tr_identity_id') == [stable]]
            if len(matched) != 1:
                raise LookupError('stable identity does not match')
            return matched[0]
    target_verifier = case['target_session']
    with tempfile.TemporaryDirectory(prefix='tr-federated-report-') as directory, ExitStack() as stack:
        root = Path(directory)
        stack.enter_context(patch.dict(os.environ, {'TRADERESEARCH_PUBLIC_SERVER': '1',
            'FACTORTESTER_PUBLIC_SERVER': '1', 'TRADERESEARCH_SERVER_ID': 'target-manager',
            'FACTORTESTER_SERVER_ID': 'target-manager', 'TRADERESEARCH_COUCHDB_URL': couch['url'],
            'TRADERESEARCH_COUCHDB_DB': couch['database'], 'TRADERESEARCH_COUCHDB_USER': couch['username'],
            'TRADERESEARCH_COUCHDB_PASSWORD': couch['password']}))
        stack.enter_context(patch('server.identity.user_session.oidc_settings', lambda: settings))
        stack.enter_context(patch('server.identity.server_admission.oidc_settings', lambda: settings))
        stack.enter_context(patch('server.identity.keycloak_authorization.oidc_settings', lambda: settings))
        stack.enter_context(patch('server.identity.federation_identity_sync.manager_keycloak_admin_adapter', Directory))
        stack.enter_context(patch('server.identity.federated_peer_delegation.bound_peer', return_value=binding))
        stack.enter_context(patch.object(delegation, 'oidc_settings', return_value=settings))
        stack.enter_context(patch.object(delegation, '_peer_secret', return_value=case['peer_secret']))
        stack.enter_context(patch.object(delegation, '_local_client', return_value=case['target_client']))
        stack.enter_context(patch.object(delegation, 'ServiceOIDCClient', side_effect=clients))
        stack.enter_context(patch.object(delegation, 'keycloak_session', side_effect=target_verifier.session))
        server_admission.clear_server_admission_cache()
        state = manager.ManagerState(root / 'repo', 'python', server_role='main', server_id='target-manager',
                                     state_root=root / 'state')
        key = NodeKey.load_or_create(root / 'source.key', node_id='source-manager')
        state.node_identities.enroll(key.public_record())
        server = ThreadingHTTPServer(('127.0.0.1', 0), peer_control_handler(state))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        node = NodeControlClient(f'http://127.0.0.1:{server.server_address[1]}', key=key)
        research_id, report_id = 'research:v1:' + 'R' * 24, 'report:v1:' + 'P' * 24
        owner_token = case['target_client']._token({'grant_type': 'password', 'client_id': client_id,
            'username': 'report-owner', 'password': owner_password})['access_token']
        owner_session = target_verifier.session(owner_token, use_cache=False)
        assert owner_session and owner_session['tr_identity_id'] == 'stable-report-owner'
        # The same source session is exchanged repeatedly; a target grant
        # revocation must be effective without requiring the user to log out.
        source_token = case['original']('source-alice')
        def assertion():
            return case['source_client'].exchange_token(source_token, audience=case['target_issuer'],
                                                        scope='access-chain-b')['access_token']
        data = value(1, 'cross-manager-selected')
        # Exercise the report-specific peer budget, which is deliberately
        # larger than the ordinary 1 MiB control-message limit.
        large_attachment = b'R' * (2 * 1024 * 1024)
        data['assets'][0]['content_base64'] = base64.b64encode(large_attachment).decode('ascii')
        data['report_id'], data['projection_hash'] = report_id, ''
        data['projection_hash'] = projection_hash(data)
        store = CouchDBObjectStore(couch['url'], couch['database'], username=couch['username'], password=couch['password'])
        service = LocalReportPublicationService(state=state, store=store)
        try:
            with identity_request():
                bind_verified_identity(owner_token, owner_session)
                published = service.publish_local(session=owner_session, research_id=research_id,
                    report_id=report_id, branch_ref='main', projection=data, expected_revision=None)
            request = {'kind': 'shared-report', 'operation': 'read', 'requester_server_id': 'source-manager',
                'identity_id': 'stable-alice', 'payload': {'research_id': research_id, 'report_id': report_id,
                                                           'branch_ref': 'main'}}
            def read(token=None):
                return node.signed_json('/api/federation/public-data',
                    {**request, 'delegation_assertion': token or assertion()},
                    max_response_bytes=12 * 1024 * 1024)
            denied(lambda: read())
            with identity_request():
                bind_verified_identity(owner_token, owner_session)
                service.set_grant(session=owner_session, research_id=research_id, report_id=report_id,
                                  identity_id='stable-alice', scopes=['read'])
            assert read()['projection']['title'] == 'cross-manager-selected'
            request['payload']['attachment'] = 'research_asset/one'
            assert base64.b64decode(read()['content_base64']) == large_attachment
            del request['payload']['attachment']
            assert read()['publication']['publication_id'] == published['publication_id']

            # A read-only recipient may view the report but cannot recover an
            # editable local snapshot. Exercise the metadata preflight through
            # both real realms and the signed peer endpoint.
            request['payload'].update(metadata_only=True, requires_edit=True)
            denied(lambda: read())
            with identity_request():
                bind_verified_identity(owner_token, owner_session)
                service.set_grant(session=owner_session, research_id=research_id, report_id=report_id,
                                  identity_id='stable-alice', scopes=['read', 'write'])
            edit_check = read()
            assert edit_check['publication']['publication_id'] == published['publication_id']
            assert edit_check['edit_authorized'] is True
            with identity_request():
                bind_verified_identity(owner_token, owner_session)
                service.set_grant(session=owner_session, research_id=research_id, report_id=report_id,
                                  identity_id='stable-alice', scopes=['read'])
            denied(lambda: read())
            del request['payload']['metadata_only']; del request['payload']['requires_edit']

            with identity_request():
                bind_verified_identity(owner_token, owner_session)
                service.set_grant(session=owner_session, research_id=research_id, report_id=report_id,
                                  identity_id='stable-alice', scopes=[])
            denied(lambda: read())
            with identity_request():
                bind_verified_identity(owner_token, owner_session)
                service.set_grant(session=owner_session, research_id=research_id, report_id=report_id,
                                  identity_id='stable-alice', scopes=['read'])
            pending = assertion()
            case['role_change'](case['alice_source'], 'DELETE')
            try: denied(lambda: read(pending))
            finally: case['role_change'](case['alice_source'], 'POST')

            grant_manager = service._manager()
            pat = grant_manager.token_provider(settings)
            resource = grant_manager._resource(settings, pat, 'research_report', report_id)
            assert resource and grant_manager._resource_policies(settings, pat, resource['_id'])
            sandbox.api('DELETE', realm, role_path, [public_role])
            try: denied(lambda: read())
            finally: sandbox.api('POST', realm, role_path, [public_role])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
            server_admission.clear_server_admission_cache()


def main():
    with couchdb_sandbox() as couch, Sandbox() as sandbox:
        run(sandbox, on_ready=lambda **case: exercise(couch=couch, **case))
    print(json.dumps({'two_real_keycloak_realms': True, 'real_couchdb': True, 'signed_peer_http': True,
        'target_report_and_admission': 'live_keycloak', 'source_and_target_revocation': True,
        'edit_permission_preflight': True,
        'distinct_owner_and_shared_recipient': True, 'same_source_session_after_revoke': True,
        'bounded_attachment_bytes': 2 * 1024 * 1024,
        'browser_source_gateway': 'covered_by_focused_test'}, sort_keys=True))


if __name__ == '__main__':
    main()
