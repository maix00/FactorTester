from __future__ import annotations

import base64
import json
from urllib.error import HTTPError

import pytest

from server.jobs.storage.couchdb_research_publication import (
    ResearchPublicationConflict, commit_shared_report, prepare_projection,
)
from server.jobs.storage.couchdb_research_reports import get_research_report, projection
from tools.cli.release.research_reporting.public_research.object_uploads import projection_hash


class Couch:
    def __init__(self):
        self.docs = {}
        self.next_conflict = False
        self.writes = 0

    def _request(self, method, path, body=None):
        current = self.docs.get(path)
        if method == 'GET':
            if current is None:
                raise HTTPError(path, 404, 'missing', {}, None)
            return 200, json.dumps(current).encode()
        if self.next_conflict:
            raise HTTPError(path, 409, 'conflict', {}, None)
        value = json.loads(body)
        if current is not None and value.get('_rev') != current['_rev']:
            raise HTTPError(path, 409, 'conflict', {}, None)
        self.writes += 1
        value['_rev'] = f'{self.writes}-revision'
        self.docs[path] = value
        return 201, json.dumps({'ok': True, 'rev': value['_rev']}).encode()

    def get_attachment(self, ref, name):
        return base64.b64decode(self.docs[ref]['_attachments'][name]['data'])


def report(*, generation=1, title='selected', body=b'picture'):
    value = {'schema_version': 2, 'report_id': 'report-1', 'title': title, 'generation': generation,
             'content_lazy': False, 'components': [{'component_id': 'c1', 'body': 'selected content'}],
             'assets': [{'asset_id': 'image-1', 'available': True, 'media_type': 'image/png',
                         'content_base64': base64.b64encode(body).decode()}],
             'attachments': [], 'local_resources': []}
    value['projection_hash'] = projection_hash(value)
    return value


def publish(store, value, *, expected=None, authorize=lambda: None):
    return commit_shared_report(store, manager_id='source', owner_id='stable-owner', owner_ref='alice',
        research_id='research-1', report_id='report-1', branch_ref='main', keycloak_resource_id='kc-resource',
        projection=value, expected_revision=expected, authorize_now=authorize)


def test_single_report_and_only_its_attachments_are_published_atomically():
    store, value = Couch(), report()
    receipt = publish(store, value)
    doc = get_research_report(store, receipt['publication_id'])
    assert doc['keycloak_resource_id'] == 'kc-resource' and doc['owner_identity_id'] == 'stable-owner'
    assert doc['publication']['authorized_users'] == [] and doc['publication']['visibility'] == 'private'
    assert set(doc['attachments']) == {'projection.json', 'research_asset/image-1'}
    assert store.get_attachment(doc['_id'], doc['attachments']['research_asset/image-1']['name']) == b'picture'
    restored = projection(store, doc)
    assert restored['report_id'] == 'report-1' and restored['assets'][0].get('content_base64') is None
    assert restored['projection_hash'] == receipt['projection_hash']
    assert 'private sibling report' not in json.dumps(doc)
    assert store.writes == 1


def test_rechecks_authorization_before_commit_and_preserves_existing_document():
    store = Couch()
    first = publish(store, report())
    def revoked():
        raise PermissionError('current Keycloak grant revoked')
    with pytest.raises(PermissionError):
        publish(store, report(generation=2), expected=first['revision'], authorize=revoked)
    assert store.writes == 1
    assert get_research_report(store, first['publication_id'])['generation'] == 1


def test_compare_and_set_and_generation_conflicts_do_not_overwrite():
    store = Couch()
    first = publish(store, report(generation=1))
    with pytest.raises(ResearchPublicationConflict):
        publish(store, report(generation=2), expected=None)
    with pytest.raises(ResearchPublicationConflict):
        publish(store, report(generation=1, title='changed'), expected=first['revision'])
    store.next_conflict = True
    with pytest.raises(ResearchPublicationConflict):
        publish(store, report(generation=2), expected=first['revision'])
    assert store.writes == 1
    store.next_conflict = False
    second = publish(store, report(generation=2), expected=first['revision'])
    assert second['revision'] != first['revision'] and store.writes == 2


def test_lost_response_can_retry_only_identical_complete_authorized_content():
    store = Couch()
    first = publish(store, report())
    retry = publish(store, report())
    assert retry['idempotent'] is True and retry['revision'] == first['revision'] and store.writes == 1
    def revoked(): raise PermissionError('revoked')
    with pytest.raises(PermissionError): publish(store, report(), authorize=revoked)
    ref = 'research-report:' + first['publication_id']
    store.docs[ref]['_attachments'].pop(next(iter(store.docs[ref]['_attachments'])))
    with pytest.raises(ResearchPublicationConflict): publish(store, report())
    assert store.writes == 1


def test_wrong_resource_or_owner_cannot_replace_an_existing_publication():
    store = Couch()
    receipt = publish(store, report())
    ref = 'research-report:' + receipt['publication_id']
    store.docs[ref]['keycloak_resource_id'] = 'replaced-resource'
    with pytest.raises(PermissionError):
        publish(store, report(generation=2), expected=receipt['revision'])
    assert store.writes == 1


@pytest.mark.parametrize('mutation', [
    lambda value: value.update(report_id='other-report'),
    lambda value: value.update(research={'title': 'private sibling report'}),
    lambda value: value.update(content_lazy=True),
    lambda value: value.update(authoring_bundle={'content': 'private source'}),
    lambda value: value['assets'][0].pop('content_base64'),
    lambda value: value['assets'][0].update(content_hash='a' * 64),
])
def test_rejects_unrelated_incomplete_or_tampered_projection(mutation):
    value = report()
    mutation(value)
    value['projection_hash'] = projection_hash(value)
    with pytest.raises(ValueError):
        prepare_projection(value, report_id='report-1')


def test_untrusted_svg_is_not_served_as_active_content():
    value = report(body=b'<svg><script>alert(1)</script></svg>')
    value['assets'][0]['media_type'] = 'image/svg+xml'
    value['projection_hash'] = projection_hash(value)
    _clean, attachments, _inline = prepare_projection(value, report_id='report-1')
    assert attachments['research_asset/image-1']['content_type'] == 'application/octet-stream'


def test_projection_hash_is_verified_before_publication():
    value = report()
    value['title'] = 'changed after hashing'
    with pytest.raises(ValueError, match='hash'):
        prepare_projection(value, report_id='report-1')
