import json
from urllib.parse import parse_qs, urlsplit

import pytest

from server.jobs.storage.couchdb_local_report_directory import owned_registration_page
from tests.server.test_couchdb_research_publication import Couch


class ViewCouch(Couch):
    def _request(self, method, path, body=None):
        if method == 'GET' and '/_view/owned?' in path:
            query = parse_qs(urlsplit(path).query)
            start, end = json.loads(query['startkey'][0]), json.loads(query['endkey'][0])
            rows = []
            for doc in self.docs.values():
                if doc.get('kind') != 'research_report_registration' or doc.get('state') != 'registered':
                    continue
                key = [doc['manager_id'], doc['owner_identity_id'], doc['report_id']]
                if start <= key <= end:
                    rows.append({'key': key, 'doc': doc})
            rows.sort(key=lambda item: item['key'])
            return 200, json.dumps({'rows': rows[:int(query['limit'][0])]}).encode()
        return super()._request(method, path, body)


def test_directory_is_owner_scoped_and_survives_deleted_cursor():
    store = ViewCouch()
    for owner, report in [('alice', 'report:a'), ('alice', 'report:b'), ('alice', 'report:c'), ('bob', 'report:z')]:
        store.docs[owner + report] = {'kind': 'research_report_registration', 'state': 'registered',
            'manager_id': 'manager', 'owner_identity_id': owner, 'report_id': report}
    first, cursor = owned_registration_page(store, manager_id='manager', owner_id='alice', after='', limit=1)
    assert [item['report_id'] for item in first] == ['report:a'] and cursor == 'report:a'
    del store.docs['alicereport:a']
    second, cursor = owned_registration_page(store, manager_id='manager', owner_id='alice', after=cursor, limit=1)
    assert [item['report_id'] for item in second] == ['report:b'] and cursor == 'report:b'
    third, cursor = owned_registration_page(store, manager_id='manager', owner_id='alice', after=cursor, limit=1)
    assert [item['report_id'] for item in third] == ['report:c'] and cursor is None


def test_directory_refuses_to_replace_an_unexpected_design():
    store = ViewCouch()
    store.docs['_design/tr-local-report-directory-v1'] = {'_id': '_design/tr-local-report-directory-v1',
        'language': 'javascript', 'views': {'owned': {'map': 'unexpected'}}}
    with pytest.raises(RuntimeError, match='inconsistent'):
        owned_registration_page(store, manager_id='manager', owner_id='alice', after='', limit=1)
