"""Real isolated Manager HTTP -> Keycloak -> CouchDB publication check.

Only disposable containers and a temporary Manager state are used. Existing
users, server data, credentials and client installations are never touched.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode

from scripts.test.couchdb_sandbox import couchdb_sandbox
from scripts.test.keycloak_cross_realm_smoke import Sandbox
from scripts.test.keycloak_research_grant_smoke import run
from scripts.test.research_couchdb_publication_smoke import value
from server.identity.request_context import bind_verified_identity, identity_request
from server.identity.user_session import UserSessionVerifier
from server.jobs.storage.couchdb_reports import CouchDBObjectStore
from server.jobs.storage.couchdb_research_reports import get_research_report, projection
from tools.cli.release.research_reporting.public_research.object_uploads import projection_hash


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
        def publish(payload, path=target, bearer=token):
            request = urllib.request.Request(path, data=json.dumps(payload).encode(), method='POST',
                headers={'Authorization': 'Bearer ' + bearer, 'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as exc:
                return exc.code, json.load(exc)
        def read(path, bearer=token):
            request = urllib.request.Request(path, headers={'Authorization': 'Bearer ' + bearer})
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

            # A catalog-owned report can now publish its actual editable tree,
            # not just its read-only projection. Verify bytes through the real
            # HTTP, Keycloak and CouchDB path after the policy is restored.
            import base64
            import hashlib
            from tools.cli.release.research_reporting.workspace import initialize_report_workspace
            from tools.cli.release.research_reporting.authoring.tree_model import add_component
            from tools.cli.release.research_reporting.authoring.tree_projection import load_snapshot
            from tools.cli.release.research_reporting.authoring.tree_bundle import bundle_from_snapshot
            from tools.cli.release.research_reporting.public_research.projection import build_upload_projection
            workspace = initialize_report_workspace(workspace_root=root / 'authoring', report_workspace_id='smoke',
                branch_id='main', report_id='report-1', workspace_id=ref, title='Editable', branch_ref='report-branch:main')
            package = workspace['package_root']
            for number in (1, 2):
                add_component(package_root=package, branch_id='main', component_id=f'chapter-{number}',
                    kind='chapter', title=f'Chapter {number}', parent_id=None, body='', content=None, display_kind='')
            snapshot = load_snapshot(package_root=package, branch_id='main')
            source = bundle_from_snapshot(snapshot, package_root=package, branch_id='main')
            digest = hashlib.sha256(source).hexdigest()
            status, editable = publish({'branch_ref': 'main', 'projection': build_upload_projection(snapshot),
                'expected_revision': receipt['revision'], 'authoring': {'sha256': digest,
                    'root_ref': snapshot['head']['root_ref'], 'content_base64': base64.b64encode(source).decode('ascii')}})
            if status != 201:
                raise AssertionError('real editable publication failed: ' + str(status) + ' ' + str(editable))
            status, body = read(target + '?branch_ref=main&metadata_only=1&requires_edit=1')
            metadata = json.loads(body)
            assert status == 200 and metadata['edit_authorized'] is True and metadata['authoring']['sha256'] == digest
            status, body = read(read_target + '/attachments/report_authoring/' + digest)
            assert status == 200 and body == source, f'authoring download status={status}, bytes={len(body)}, expected={len(source)}'

            # Verify the desktop client can import a server-owned editable
            # report through the same actual Manager / Keycloak / Couch path.
            catalog_report = 'report:v1:' + 'C' * 24
            with identity_request():
                bind_verified_identity(token, verified)
                catalog.register_report(ref, actor='owner', report_id=catalog_report, title='desktop import')
            catalog_workspace = initialize_report_workspace(workspace_root=root / 'catalog-authoring', report_workspace_id='smoke',
                branch_id='main', report_id=catalog_report, workspace_id=ref, title='Desktop import', branch_ref='report-branch:main')
            catalog_root = catalog_workspace['package_root']
            catalog_snapshot = load_snapshot(package_root=catalog_root, branch_id='main')
            catalog_source = bundle_from_snapshot(catalog_snapshot, package_root=catalog_root, branch_id='main')
            catalog_target = target.replace('/reports/report-1/', '/reports/' + quote(catalog_report, safe='') + '/')
            status, catalog_receipt = publish({'branch_ref': 'main', 'projection': build_upload_projection(catalog_snapshot),
                'expected_revision': None, 'authoring': {'sha256': hashlib.sha256(catalog_source).hexdigest(),
                    'root_ref': catalog_snapshot['head']['root_ref'], 'content_base64': base64.b64encode(catalog_source).decode('ascii')}}, catalog_target)
            assert status == 201, (status, catalog_receipt)
            from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC
            endpoint = 'http://127.0.0.1:' + str(http.server_address[1])
            client = LocalResearchRPC(root / 'desktop', issuer=verified['keycloak_issuer'], identity_id=verified['tr_identity_id'],
                profiles=[{'profile_id': 'self', 'display_name': 'Owner'}], manager={'endpoint': endpoint,
                    'subject': verified['keycloak_subject'], 'token': token, 'certificate_pem': '', 'cookies': []})
            imported_research = client.request({'action': 'import_research', 'profile_id': 'self', 'research_id': ref})
            assert imported_research['status'] == 'imported'
            imported_report = client.request({'action': 'import_catalog_report', 'profile_id': 'self',
                'research_id': ref, 'report_id': catalog_report})
            assert imported_report['status'] == 'imported'
            imported_version = client.request({'action': 'get_report', 'profile_id': 'self', 'research_id': ref,
                'report_id': catalog_report})['version']
            assert imported_version['generation'] == catalog_snapshot['head']['generation']
            peer = LocalResearchRPC(root / 'desktop-peer', issuer=verified['keycloak_issuer'], identity_id=verified['tr_identity_id'],
                profiles=[{'profile_id': 'self', 'display_name': 'Owner'}], manager={'endpoint': endpoint,
                    'subject': verified['keycloak_subject'], 'token': token, 'certificate_pem': '', 'cookies': []})
            cursor = ''
            while True:
                discovered = peer.request({'action': 'discover_researches', 'profile_id': 'self', 'cursor': cursor, 'limit': 16})
                cursor = discovered['next_cursor']
                if cursor is None: break
            sync = {'action': 'sync_reports', 'profile_id': 'self', 'after_report_id': '', 'limit': 4}
            discovery = peer.request(sync)
            assert any(item['report_id'] == catalog_report and item['status'] == 'imported' for item in discovery['report_imports']), discovery
            client.request({'action': 'add_report_component', 'profile_id': 'self', 'research_id': ref,
                'report_id': catalog_report, 'component_id': 'chapter-client', 'kind': 'chapter',
                'parent_id': '', 'title': 'Desktop edit', 'body': '', **imported_version})
            sync = {'action': 'sync_reports', 'profile_id': 'self', 'after_report_id': '', 'limit': 4}
            assert client.request(sync)['reports'][0]['status'] == 'published'
            assert any(item['report_id'] == catalog_report and item['status'] == 'updated' for item in peer.request(sync)['reports'])
            peer_index = peer.request({'action': 'get_report', 'profile_id': 'self', 'research_id': ref, 'report_id': catalog_report})
            assert peer_index['index']['chapters'][0]['title'] == 'Desktop edit'

            # A client-local report has no server-side Research or Profile.
            # Its first explicit publication registers exactly one report
            # resource and atomically writes its selected CouchDB projection.
            research_id, report_id = 'research:v1:' + 'R' * 24, 'report:v1:' + 'P' * 24
            local_target = ('http://127.0.0.1:' + str(http.server_address[1])
                            + '/api/research/local-report-publication')
            local_value = value(1, 'local-selected')
            local_value['report_id'] = report_id
            local_value['projection_hash'] = projection_hash(local_value)
            local_payload = {'research_id': research_id, 'report_id': report_id,
                             'branch_ref': 'main', 'projection': local_value, 'expected_revision': None}
            status, result = publish(local_payload, local_target)
            if status != 201:
                raise AssertionError('real local report first publication failed: ' + str(status) + ' ' + str(result))
            local_receipt = result['publication']
            retry_status, retry = publish(local_payload, local_target)
            assert retry_status == 201 and retry['publication']['idempotent'] is True
            local_query = urlencode({'research_id': research_id, 'report_id': report_id, 'branch_ref': 'main'})
            local_read_status, local_read_body = read(local_target + '?' + local_query)
            assert local_read_status == 200 and json.loads(local_read_body)['projection']['report_id'] == report_id
            with sqlite3.connect('file:' + str(catalog.db_path) + '?mode=ro', uri=True) as conn:
                assert conn.execute('SELECT count(*) FROM research_catalog_researches WHERE research_id=?',
                                    (research_id,)).fetchone()[0] == 0
                assert conn.execute('SELECT count(*) FROM research_catalog_reports WHERE report_id=?',
                                    (report_id,)).fetchone()[0] == 0
            assert projection(store, get_research_report(store, local_receipt['publication_id']))['title'] == 'local-selected'

            # Grant to the exact stable ID in this realm, then demonstrate
            # same-token access and revocation through the actual HTTP route.
            member_password = secrets.token_urlsafe(24)
            sandbox.api('PUT', realm, 'users/' + users['member']['id'] + '/reset-password',
                        {'type': 'password', 'value': member_password, 'temporary': False})
            sandbox.api('POST', realm, 'users/' + users['member']['id'] + '/role-mappings/clients/' + cid,
                        [case['public_role']])
            member_token = case['client']._token({'grant_type': 'password', 'client_id': case['client_id'],
                'username': 'member', 'password': member_password})['access_token']
            grant_target = local_target + '/grants'
            grant_payload = {'research_id': research_id, 'report_id': report_id,
                             'identity_id': 'stable-member', 'scopes': ['read']}
            assert read(local_target + '?' + local_query, member_token)[0] == 403
            assert publish(grant_payload, grant_target)[0] == 200
            grant_status, grant_body = read(grant_target + '?' + local_query)
            assert grant_status == 200 and json.loads(grant_body)['grants'][0]['identity_id'] == 'stable-member'
            assert read(local_target + '?' + local_query, member_token)[0] == 200
            assert publish({**grant_payload, 'scopes': []}, grant_target)[0] == 200
            assert read(local_target + '?' + local_query, member_token)[0] == 403
            assert read(local_target + '?' + local_query)[0] == 200
            sandbox.api('DELETE', realm, role_path, [case['public_role']])
            assert publish(local_payload, local_target)[0] in {401, 403}
            sandbox.api('POST', realm, role_path, [case['public_role']])
            local_resource = manager._resource(settings, pat, 'research_report', report_id)
            local_resource_id = str(local_resource.get('_id') or local_resource.get('id'))
            local_policies = [row for row in manager._resource_policies(settings, pat, local_resource_id)
                              if str(row.get('name') or '').endswith(':owner')]
            assert len(local_policies) == 1 and 'share' in local_policies[0]['scopes']
            local_policy = local_policies[0]
            local_original = {'name': local_policy['name'], 'description': local_policy['description'],
                              'users': [users['owner']['id']], 'scopes': local_policy['scopes'], 'logic': 'POSITIVE'}
            manager.request(settings, pat, 'PUT', 'uma-policy/' + local_policy['id'],
                            {**local_original, 'scopes': [scope for scope in local_original['scopes'] if scope != 'share']})
            assert publish(local_payload, local_target)[0] in {401, 403}
            live_policy = next(row for row in manager._resource_policies(settings, pat, local_resource_id)
                               if row['id'] == local_policy['id'])
            assert 'share' not in live_policy['scopes']
        finally:
            http.shutdown(); http.server_close(); thread.join(timeout=5)
            server_admission.clear_server_admission_cache()


def main():
    with couchdb_sandbox() as couch, Sandbox() as sandbox:
        run(sandbox, on_ready=lambda **case: exercise(couch=couch, **case))
    print(json.dumps({'real_manager_http': True, 'real_keycloak': True, 'real_couchdb': True,
        'single_report_and_attachment': True, 'same_token_role_revocation': True,
        'catalog_editable_source_roundtrip': True, 'catalog_desktop_import': True, 'catalog_two_client_sync': True, 'catalog_automatic_discovery': True,
        'same_token_share_and_read_revocation': True, 'local_first_publication': True,
        'local_retry_does_not_restore_revoked_share': True, 'local_grant_and_revoke': True,
        'cross_manager_tested': False}, sort_keys=True))


if __name__ == '__main__':
    main()
