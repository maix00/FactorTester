"""Real isolated Manager HTTP -> Keycloak -> CouchDB publication check.

Only disposable containers and a temporary Manager state are used. Existing
users, server data, credentials and client installations are never touched.
"""
from __future__ import annotations

import json
import copy
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
            inconsistent = build_upload_projection(snapshot)
            inconsistent['title'] = 'Different display title'
            inconsistent['projection_hash'] = projection_hash(inconsistent)
            status, _ = publish({'branch_ref': 'main', 'projection': inconsistent,
                'expected_revision': receipt['revision'], 'authoring': {'sha256': digest,
                    'root_ref': snapshot['head']['root_ref'], 'content_base64': base64.b64encode(source).decode('ascii')}})
            assert status == 400 and get_research_report(store, receipt['publication_id'])['_rev'] == receipt['revision']
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

            # A genuinely fresh native store discovers an explicitly shared
            # client-local report without any server Research/Profile row.
            native_manager = {'endpoint': endpoint, 'subject': verified['keycloak_subject'], 'token': token,
                              'certificate_pem': '', 'cookies': []}
            def native_client(name):
                return LocalResearchRPC(root / name, issuer=verified['keycloak_issuer'], identity_id=verified['tr_identity_id'],
                    profiles=[{'profile_id': 'self', 'display_name': 'Owner'}], manager=native_manager)
            source, fresh = native_client('local-source'), native_client('local-fresh')
            research = source.request({'action':'create', 'profile_id':'self', 'title':'Local shared research',
                                       'description':'private local notes', 'operation_id':'local-research'})['research']
            create_local = {'action':'create_report', 'profile_id':'self', 'research_id':research['research_id']}
            shared = source.request({**create_local, 'title':'Selected local report', 'operation_id':'local-shared'})['report']
            private = source.request({**create_local, 'title':'Unshared sibling', 'operation_id':'local-private'})['report']
            local_ids = {'profile_id':'self', 'research_id':research['research_id'], 'report_id':shared['report_id']}
            # Exercise the content baseline through the real authorization and
            # persistence path, including an external edit committed to Git.
            from tools.cli.release.research_reporting.authoring.tree_model import add_asset
            from tools.cli.release.research_reporting.git import commit_report_workspace
            _, source_root = source.store._report_root('self', research['research_id'], shared['report_id'])
            figure = source_root / 'branches' / 'main' / 'assets' / 'figure.png'
            figure.parent.mkdir(exist_ok=True)
            original_figure = b'real-manager-linked-asset'
            figure.write_bytes(original_figure)
            figure_hash = hashlib.sha256(original_figure).hexdigest()
            add_asset(package_root=source_root, branch_id='main', asset={
                'asset_ref': 'report-asset:sha256:' + figure_hash, 'media_type': 'image/png',
                'filename': 'figure.png', 'caption': 'Figure', 'alt_text': '',
                'content_hash': figure_hash, 'local_ref': 'branches/main/assets/figure.png'})
            commit_report_workspace(source_root, message='Add report figure')
            local_publication = source.request({'action':'publish_report', **local_ids})['publication']
            figure.write_bytes(b'committed external modification')
            commit_report_workspace(source_root, message='Modify report figure externally')
            edited_pull = source.request({'action': 'pull_report', **local_ids})
            assert edited_pull['status'] == 'up_to_date' and edited_pull['local_modified'] is True, edited_pull
            assert figure.read_bytes() == b'committed external modification'
            figure.write_bytes(original_figure)
            commit_report_workspace(source_root, message='Restore report figure')
            local_sync = {'action':'sync_reports', 'profile_id':'self', 'after_report_id':'', 'limit':4}
            restored = fresh.request(local_sync)
            assert any(item['report_id'] == shared['report_id'] and item['status'] == 'imported'
                       for item in restored['report_imports']), restored
            restored_research = fresh.request({'action':'get', 'profile_id':'self', 'research_id':research['research_id']})['research']
            assert restored_research['title'] == 'Local shared research' and restored_research['description'] == ''
            restored_reports = fresh.request({'action':'list_reports', 'profile_id':'self',
                'research_id':research['research_id'], 'limit':10, 'offset':0})['reports']
            assert [row['report_id'] for row in restored_reports] == [shared['report_id']]
            version = fresh.request({'action':'get_report', **local_ids})['version']
            fresh.request({'action':'add_report_component', **local_ids, 'component_id':'fresh-section', 'kind':'chapter',
                           'parent_id':'', 'title':'Fresh device edit', 'body':'', **version})
            assert fresh.request(local_sync)['reports'][0]['status'] == 'published'
            assert source.request(local_sync)['reports'][0]['status'] == 'updated'
            assert source.request({'action':'get_report', **local_ids})['index']['chapters'][0]['title'] == 'Fresh device edit'
            # Simulate a crash after identical report content was committed but
            # before its local receipt advanced. The recovery must compare the
            # full authoring bundle under real Manager and Keycloak sessions.
            with source.store._connect() as db:
                updated = db.execute('''UPDATE report_publications SET revision=?,generation=?,local_root_ref=?
                    WHERE report_id=?''', ('fixture-old-revision', 999, 'fixture-old-root', shared['report_id']))
                assert updated.rowcount == 1
            recovered = source.request(local_sync)
            assert any(item['report_id'] == shared['report_id'] and item['status'] == 'unchanged'
                       for item in recovered['reports']), recovered
            # Model an old report resource without the Research binding. Real
            # Keycloak decisions for every fixture user and scope must remain
            # unchanged when the binding is recovered from its real receipt.
            from scripts.migrations.keycloak_local_report_binding import BindingBackend, _SCOPES
            from scripts.migrations import keycloak_local_report_binding_cli
            from server.identity.keycloak_policy_evaluation import KeycloakPolicyEvaluator
            from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
            origin_resource = manager._resource(settings, pat, 'research_report', shared['report_id'])
            origin_id = str(origin_resource.get('_id') or origin_resource.get('id'))
            origin_policy = next(row for row in manager._resource_policies(settings, pat, origin_id)
                                 if str(row.get('name') or '').endswith(':owner'))
            restored_policy = {'name': origin_policy['name'], 'description': origin_policy['description'],
                'users': [users['owner']['id']], 'scopes': origin_policy['scopes'], 'logic': 'POSITIVE'}
            manager.request(settings, pat, 'PUT', 'uma-policy/' + origin_policy['id'],
                {**restored_policy, 'scopes': [scope for scope in restored_policy['scopes'] if scope != 'share']})
            legacy_resource = copy.deepcopy(origin_resource)
            legacy_resource['attributes'].pop('traderesearch_research_binding')
            manager.request(settings, pat, 'PUT', 'resource_set/' + origin_id, legacy_resource)
            identities = {'stable-' + name: user['id'] for name, user in users.items()}
            evaluator = KeycloakPolicyEvaluator(allowed_kinds=('research_report',),
                allowed_scopes=_SCOPES, adapter=manager_keycloak_admin_adapter(),
                settings=settings, request=lambda _adapter, client_uuid, body: sandbox.api('POST', realm,
                    f'clients/{client_uuid}/authz/resource-server/policy/evaluate', body))
            # This fixture knows its three human users; production enumerates
            # and validates the complete Keycloak group directory instead.
            with patch('server.identity.keycloak_migration_directory.active_human_subjects', lambda _adapter: identities), \
                 patch.object(manager, 'settings_provider', lambda: kc_settings):
                backend = BindingBackend(state=state, store=store, manager=manager,
                    adapter=manager_keycloak_admin_adapter(), research_id=research['research_id'],
                    report_id=shared['report_id'], owner_id=verified['tr_identity_id'], evaluator=evaluator)
                before = backend.read_evidence()
                decision_snapshot = backend.read_decisions(identities, shared['report_id'])
                assert decision_snapshot[(verified['tr_identity_id'], 'share')] is False
                # Restore the two origin documents with original CouchDB
                # revisions in a separate test database. Keycloak backup is a
                # checksum fixture only, not a realm restore rehearsal.
                import base64
                import hashlib
                import io
                from contextlib import redirect_stdout
                restored_name = 'binding_restore'
                header = 'Basic ' + base64.b64encode((couch['username'] + ':' + couch['password']).encode()).decode()
                with urllib.request.urlopen(urllib.request.Request(couch['url'] + '/' + restored_name,
                        method='PUT', headers={'Authorization': header}), timeout=10): pass
                restored_store = CouchDBObjectStore(couch['url'], restored_name,
                    username=couch['username'], password=couch['password'])
                documents = []
                for key in ('receipt', 'publication'):
                    status, raw = store._request('GET', before[key]['_id'] + '?attachments=true&revs=true')
                    assert status == 200
                    documents.append(json.loads(raw))
                backup_file, kc_fixture = root / 'couch-fixture.json', root / 'kc-fixture'
                backup_file.write_text(json.dumps({'docs': documents, 'new_edits': False}), encoding='utf-8')
                backup_file.chmod(0o600)
                status, response = restored_store._request('POST', '_bulk_docs', backup_file.read_bytes())
                assert status in (201, 202) and all(not item.get('error') for item in json.loads(response))
                kc_fixture.write_bytes(b'disposable checksum fixture, not a realm backup'); kc_fixture.chmod(0o600)
                plan_file, journal_file = root / 'binding-plan.json', root / 'binding-journal.jsonl'
                common = ['binding', '--manager-id', 'publication-smoke', '--owner-id', verified['tr_identity_id'],
                    '--research-id', research['research_id'], '--report-id', shared['report_id'], '--plan', str(plan_file)]
                restored_env = {'TR_REPORT_RESTORED_COUCHDB_URL': couch['url'], 'TR_REPORT_RESTORED_COUCHDB_DB': restored_name,
                    'TR_REPORT_RESTORED_COUCHDB_USER': couch['username'], 'TR_REPORT_RESTORED_COUCHDB_PASSWORD': couch['password']}
                with patch.dict(os.environ, restored_env), \
                     patch('server.identity.keycloak_research.KeycloakResearchGrantManager', lambda: manager), \
                     patch('server.identity.keycloak_policy_evaluation.KeycloakPolicyEvaluator', lambda **_kwargs: evaluator), \
                     redirect_stdout(io.StringIO()):
                    with patch.object(sys, 'argv', [common[0], 'review', *common[1:]]):
                        keycloak_local_report_binding_cli.main()
                    with patch.object(sys, 'argv', [common[0], 'stage', *common[1:], '--journal', str(journal_file),
                        '--keycloak-backup', str(kc_fixture), '--keycloak-backup-sha256', hashlib.sha256(kc_fixture.read_bytes()).hexdigest(),
                        '--couch-backup', str(backup_file), '--couch-backup-sha256', hashlib.sha256(backup_file.read_bytes()).hexdigest(),
                        '--authorization-writes-quiesced', '--keycloak-restore-verified']):
                        keycloak_local_report_binding_cli.main()
                assert [json.loads(row)['event'] for row in journal_file.read_text().splitlines()] == ['binding_intent', 'binding_verified']
                assert backend.read_decisions(identities, shared['report_id']) == decision_snapshot
            manager.request(settings, pat, 'PUT', 'uma-policy/' + origin_policy['id'], restored_policy)
            # A second Manager in this shared realm can adopt only the same
            # research-bound resource with the owner's current authorization.
            # Both instances share the temporary object store in this fixture.
            peer_state = manager_runtime.ManagerState(Path(__file__).resolve().parents[2], sys.executable,
                server_role='main', server_id='publication-peer', state_root=root / 'peer-state', data_root=root / 'peer-data')
            peer_state.research_catalog = catalog
            class PeerHandler(manager_runtime.Handler):
                def log_message(self, *_args): pass
            PeerHandler.state = peer_state
            peer_http = manager_runtime.ThreadingHTTPServer(('127.0.0.1', 0), PeerHandler)
            peer_thread = threading.Thread(target=peer_http.serve_forever, daemon=True)
            peer_thread.start()
            try:
                peer_endpoint = 'http://127.0.0.1:' + str(peer_http.server_address[1])
                source_on_peer = LocalResearchRPC(root / 'local-source', issuer=verified['keycloak_issuer'],
                    identity_id=verified['tr_identity_id'], profiles=[{'profile_id':'self', 'display_name':'Owner'}],
                    manager={**native_manager, 'endpoint': peer_endpoint})
                peer_client = LocalResearchRPC(root / 'local-fresh', issuer=verified['keycloak_issuer'],
                    identity_id=verified['tr_identity_id'], profiles=[{'profile_id':'self', 'display_name':'Owner'}],
                    manager={**native_manager, 'endpoint': peer_endpoint})
                # Both in-process states otherwise share one process-wide
                # deployment environment, which deliberately rejects two
                # distinct server IDs. Isolate just that deployment lookup;
                # token, role, object policy and CouchDB remain real.
                with patch.object(server_admission, '_context',
                                  lambda state=None: (True, state.server_id, ())):
                    shared_resource = manager._resource(settings, pat, 'research_report', shared['report_id'])
                    shared_id = str(shared_resource.get('_id') or shared_resource.get('id'))
                    shared_policy = next(row for row in manager._resource_policies(settings, pat, shared_id)
                                         if str(row.get('name') or '').endswith(':owner'))
                    original_policy = {'name': shared_policy['name'], 'description': shared_policy['description'],
                        'users': [users['owner']['id']], 'scopes': shared_policy['scopes'], 'logic': 'POSITIVE'}
                    manager.request(settings, pat, 'PUT', 'uma-policy/' + shared_policy['id'],
                        {**original_policy, 'scopes': [scope for scope in original_policy['scopes'] if scope != 'share']})
                    denied = source_on_peer.request({'action':'publish_report', **local_ids})
                    assert denied['success'] is False and denied['code'] == 'local_report_publication_denied'
                    live_policy = next(row for row in manager._resource_policies(settings, pat, shared_id)
                                       if row['id'] == shared_policy['id'])
                    assert 'share' not in live_policy['scopes']
                    manager.request(settings, pat, 'PUT', 'uma-policy/' + shared_policy['id'], original_policy)
                    published_peer = source_on_peer.request({'action':'publish_report', **local_ids})
                    assert published_peer['success'] is True
                    peer_result = peer_client.request(local_sync)
                    if not any(item['report_id'] == shared['report_id'] and item['status'] == 'attached'
                               for item in peer_result['report_imports']):
                        from tools.cli.release.research_reporting.local_catalog_import import import_shared_local_report
                        import_shared_local_report(peer_client.store, binding=peer_client.binding, manager=peer_client.manager,
                            profile_id='self', research_id=research['research_id'], report_id=shared['report_id'])
                    assert any(item['report_id'] == shared['report_id'] and item['status'] == 'attached'
                               for item in peer_result['report_imports']), peer_result
                    version = peer_client.request({'action':'get_report', **local_ids})['version']
                    peer_client.request({'action':'add_report_component', **local_ids, 'component_id':'peer-section',
                        'kind':'chapter', 'parent_id':'', 'title':'Peer edit', 'body':'', **version})
                    assert peer_client.request(local_sync)['reports'][0]['status'] == 'published'
                    assert source_on_peer.request(local_sync)['reports'][0]['status'] == 'updated'
                    assert source.request(local_sync)['reports'][0]['status'] == 'published'
                    assert source.request({'action':'get_report', **local_ids})['index']['chapters'][-1]['title'] == 'Peer edit'
            finally:
                peer_http.shutdown(); peer_http.server_close(); peer_thread.join(timeout=5)
            with sqlite3.connect('file:' + str(catalog.db_path) + '?mode=ro', uri=True) as conn:
                assert conn.execute('SELECT count(*) FROM research_catalog_researches WHERE research_id=?', (research['research_id'],)).fetchone()[0] == 0
            local_published = get_research_report(store, local_publication['publication_id'])
            assert private['report_id'] not in json.dumps(local_published) and 'private local notes' not in json.dumps(local_published)
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
        'catalog_editable_source_roundtrip': True, 'mismatched_authoring_rejected': True, 'catalog_desktop_import': True, 'catalog_two_client_sync': True, 'catalog_automatic_discovery': True,
        'same_token_share_and_read_revocation': True, 'local_first_publication': True,
        'committed_asset_edit_preserved': True,
        'local_fresh_device_discovery_and_bidirectional_sync': True,
        'real_authoring_convergence_recovery': True,
        'local_retry_does_not_restore_revoked_share': True, 'local_grant_and_revoke': True,
        'shared_realm_two_manager_client_mediated_sync': True, 'legacy_binding_permissions_preserved': True,
        'independent_realms_tested': False}, sort_keys=True))


if __name__ == '__main__':
    main()
