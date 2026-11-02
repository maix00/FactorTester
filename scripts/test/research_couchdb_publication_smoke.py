"""Verify one-report publication against a temporary local CouchDB image.

No image is downloaded, existing server contacted, or credentials printed.
The authorization callback is synthetic; real Keycloak is checked separately.
"""
from __future__ import annotations

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from server.jobs.storage.couchdb_reports import CouchDBObjectStore
from server.jobs.storage.couchdb_research_publication import ResearchPublicationConflict, commit_shared_report
from server.jobs.storage.couchdb_research_reports import get_research_report, projection
from scripts.test.couchdb_sandbox import couchdb_sandbox
from tools.cli.release.research_reporting.public_research.object_uploads import projection_hash


def value(generation, title):
    result = {'schema_version': 2, 'report_id': 'report-1', 'title': title, 'generation': generation,
              'content_lazy': False, 'components': [{'component_id': 'one', 'body': 'shared report only'}],
              'assets': [{'asset_id': 'one', 'media_type': 'image/png', 'available': True,
                          'content_base64': base64.b64encode(b'only-selected-object').decode()}],
              'attachments': [], 'local_resources': []}
    result['projection_hash'] = projection_hash(result)
    return result


def main():
    with couchdb_sandbox() as info:
        store = CouchDBObjectStore(info['url'], info['database'], username=info['username'], password=info['password'])
        def publish(data, expected, *, selected_store=store, authorize=lambda: None):
            return commit_shared_report(selected_store, manager_id='local', owner_id='owner-id', owner_ref='alice',
                research_id='research-1', report_id='report-1', branch_ref='main', keycloak_resource_id='kc-1',
                projection=data, expected_revision=expected, authorize_now=authorize)
        first = publish(value(1, 'shared'), None)
        retry = publish(value(1, 'shared'), None)
        assert retry.get('idempotent') is True and retry['revision'] == first['revision']
        document = get_research_report(store, first['publication_id'])
        assert projection(store, document)['title'] == 'shared'
        assert store.get_attachment(document['_id'], document['attachments']['research_asset/one']['name']) == b'only-selected-object'
        assert 'private sibling report' not in json.dumps(document)

        def denied(): raise PermissionError('grant revoked')
        try:
            publish(value(2, 'denied'), first['revision'], authorize=denied)
            raise AssertionError('revoked publication must fail')
        except PermissionError:
            pass
        assert get_research_report(store, first['publication_id'])['_rev'] == first['revision']

        barrier = threading.Barrier(2)
        class BarrierStore:
            def _request(self, method, path, *args):
                result = store._request(method, path, *args)
                if method == 'GET': barrier.wait(timeout=5)
                return result
        def race(title):
            try:
                return publish(value(2, title), first['revision'], selected_store=BarrierStore())
            except ResearchPublicationConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(race, ['concurrent-a', 'concurrent-b']))
        assert sum(item is not None for item in results) == 1
        print(json.dumps({'real_couchdb': True, 'atomic_projection_and_object': True, 'lost_response_retry': True,
            'revocation_prevents_write': True, 'concurrent_cas_one_winner': True,
            'real_keycloak': False, 'cross_manager_tested': False}, sort_keys=True))
if __name__ == '__main__':
    main()
