"""Real isolated Manager HTTP -> Keycloak -> CouchDB publication check.

Only disposable containers and a temporary Manager state are used. Existing
users, server data, credentials and client installations are never touched.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from scripts.test.couchdb_sandbox import couchdb_sandbox
from scripts.test.keycloak_cross_realm_smoke import Sandbox
from scripts.test.keycloak_research_grant_smoke import run
from scripts.test.research_couchdb_publication_smoke import value
from server.identity.request_context import bind_verified_identity, identity_request
from server.identity.user_session import UserSessionVerifier
from server.jobs.storage.couchdb_reports import CouchDBObjectStore
from server.jobs.storage.couchdb_research_reports import get_research_report, projection


def exercise(*, couch, **case):
    from server.manager import runtime as manager_runtime
    from server.identity import server_admission

    sandbox, realm, cid = case['sandbox'], case['realm'], case['client_uuid']
    catalog, ref, users = case['catalog'], case['research_id'], case['users']
    kc_settings = {**case['settings'], 'issuer': case['issuer'], 'client_id': case['client_id'],
                   'roles_client_id': case['client_id'], 'audience': case['client_id'],
                   'backchannel_base_url': sandbox.base,
                   'client_secret': case['settings']['authz_client_secret'], 'secret_path': ''}
    token = case['sessions']['owner'][0]
    verified = UserSessionVerifier(case['client'], issuer=case['issuer'], audience=case['client_id']).session(
        token, use_cache=False)
    if not verified or 'public_server:login' not in verified['keycloak_roles']:
        raise AssertionError('real Keycloak token did not include the configured public login role')
    with identity_request():
        bind_verified_identity(token, verified)
        catalog.register_report(ref, actor='owner', report_id='report-1', title='selected')
        catalog.register_report(ref, actor='owner', report_id='private-sibling',
                                title='private sibling report sentinel')

    with tempfile.TemporaryDirectory(prefix='tr-publication-manager-') as dirname, ExitStack() as stack:
        root = Path(dirname)
        updates = {'TRADERESEARCH_PUBLIC_SERVER': '1', 'FACTORTESTER_PUBLIC_SERVER': '1',
                   'TRADERESEARCH_SERVER_ID': 'publication-smoke', 'FACTORTESTER_SERVER_ID': 'publication-smoke',
                   'TRADERESEARCH_COUCHDB_URL': couch['url'], 'TRADERESEARCH_COUCHDB_DB': couch['database'],
                   'TRADERESEARCH_COUCHDB_USER': couch['username'], 'TRADERESEARCH_COUCHDB_PASSWORD': couch['password']}
        stack.enter_context(patch.dict(os.environ, updates))
        stack.enter_context(patch('server.identity.user_session.oidc_settings', lambda: kc_settings))
        stack.enter_context(patch('server.identity.server_admission.oidc_settings', lambda: kc_settings))
        server_admission.clear_server_admission_cache()
        state = manager_runtime.ManagerState(Path(__file__).resolve().parents[2], sys.executable,
            server_role='main', server_id='publication-smoke', state_root=root / 'state', data_root=root / 'data')
        state.research_catalog = catalog
        class Handler(manager_runtime.Handler):
            def log_message(self, *_args): pass
        Handler.state = state
        http = manager_runtime.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        target = ('http://127.0.0.1:' + str(http.server_address[1]) + '/api/research/'
                  + quote(ref, safe='') + '/reports/report-1/couchdb-publication')
        def publish(payload):
            request = urllib.request.Request(target, data=json.dumps(payload).encode(), method='POST',
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as exc:
                return exc.code, json.load(exc)
        def read(path):
            request = urllib.request.Request(path, headers={'Authorization': 'Bearer ' + token})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()
        try:
            first_status, first = publish({'branch_ref': 'main', 'projection': value(1, 'selected'),
                                           'expected_revision': None})
            if first_status != 201:
                raise AssertionError('real Manager publication failed: ' + str(first_status) + ' ' + str(first))
            receipt = first['publication']
            store = CouchDBObjectStore(couch['url'], couch['database'],
                                       username=couch['username'], password=couch['password'])
            doc = get_research_report(store, receipt['publication_id'])
            assert projection(store, doc)['report_id'] == 'report-1'
            assert 'private sibling report sentinel' not in json.dumps(doc)
            assert store.get_attachment(doc['_id'], doc['attachments']['research_asset/one']['name']) == b'only-selected-object'
            read_target = target + '/' + receipt['publication_id']
            status, body = read(read_target)
            assert status == 200 and json.loads(body)['projection']['report_id'] == 'report-1'
            status, body = read(target + '?branch_ref=main')
            assert status == 200 and json.loads(body)['publication']['publication_id'] == receipt['publication_id']
            status, body = read(read_target + '/attachments/research_asset/one')
            assert status == 200 and body == b'only-selected-object'
            sibling_target = target.replace('/reports/report-1/', '/reports/private-sibling/') + '/' + receipt['publication_id']
            assert read(sibling_target)[0] == 403

            # The verified bearer is deliberately reused after live role removal.
            role_path = 'users/' + users['owner']['id'] + '/role-mappings/clients/' + cid
            sandbox.api('DELETE', realm, role_path, [case['public_role']])
            denied, _ = publish({'branch_ref': 'main', 'projection': value(2, 'denied'),
                                 'expected_revision': receipt['revision']})
            assert denied in {401, 403} and get_research_report(store, receipt['publication_id'])['_rev'] == receipt['revision']
            assert read(read_target)[0] in {401, 403}
            sandbox.api('POST', realm, role_path, [case['public_role']])

            manager, settings = case['manager'], case['settings']
            pat = manager.token_provider(settings)
            resource = manager._resource(settings, pat, 'research_report', 'report-1')
            resource_id = str(resource.get('_id') or resource.get('id'))
            policies = [row for row in manager._resource_policies(settings, pat, resource_id)
                        if str(row.get('name') or '').endswith(':owner')]
            assert len(policies) == 1 and 'share' in policies[0]['scopes']
            policy = policies[0]
            original = {'name': policy['name'], 'description': policy['description'],
                        'users': [users['owner']['id']], 'scopes': policy['scopes'], 'logic': 'POSITIVE'}
            without_share = {**original, 'scopes': [scope for scope in original['scopes'] if scope != 'share']}
            manager.request(settings, pat, 'PUT', 'uma-policy/' + policy['id'], without_share)
            denied, _ = publish({'branch_ref': 'main', 'projection': value(2, 'denied'),
                                 'expected_revision': receipt['revision']})
            assert denied in {401, 403} and get_research_report(store, receipt['publication_id'])['_rev'] == receipt['revision']
            without_read = {**original, 'scopes': [scope for scope in original['scopes'] if scope != 'read']}
            manager.request(settings, pat, 'PUT', 'uma-policy/' + policy['id'], without_read)
            assert read(read_target)[0] in {401, 403}
            manager.request(settings, pat, 'PUT', 'uma-policy/' + policy['id'], original)
        finally:
            http.shutdown(); http.server_close(); thread.join(timeout=5)
            server_admission.clear_server_admission_cache()


def main():
    with couchdb_sandbox() as couch, Sandbox() as sandbox:
        run(sandbox, on_ready=lambda **case: exercise(couch=couch, **case))
    print(json.dumps({'real_manager_http': True, 'real_keycloak': True, 'real_couchdb': True,
        'single_report_and_attachment': True, 'same_token_role_revocation': True,
        'same_token_share_and_read_revocation': True, 'cross_manager_tested': False}, sort_keys=True))


if __name__ == '__main__':
    main()
