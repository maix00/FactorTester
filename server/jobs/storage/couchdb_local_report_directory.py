"""A derived, owner-scoped CouchDB view of explicitly shared local reports."""
from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.parse import urlencode


_DESIGN = '_design/tr-local-report-directory-v1'
_MAP = ('function(doc) { if (doc.kind === "research_report_registration" && '
        'doc.state === "registered" && typeof doc.manager_id === "string" && '
        'typeof doc.owner_identity_id === "string" && typeof doc.report_id === "string") '
        '{ emit([doc.manager_id, doc.owner_identity_id, doc.report_id], null); } }')
_VIEWS = {'owned': {'map': _MAP, 'options': {'collation': 'raw'}}}


def ensure_directory_view(store) -> None:
    """Create the versioned derived view once; never overwrite a different design."""
    try:
        status, body = store._request('GET', _DESIGN)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        try:
            status, body = store._request('PUT', _DESIGN, json.dumps(
                {'_id': _DESIGN, 'language': 'javascript', 'views': _VIEWS},
                separators=(',', ':')).encode())
        except HTTPError as race:
            if race.code != 409:
                raise
        else:
            if status not in {201, 202} or json.loads(body).get('ok') is not True:
                raise RuntimeError('local report directory view was not created')
        status, body = store._request('GET', _DESIGN)
    value = json.loads(body)
    if (status != 200 or not isinstance(value, dict) or value.get('_id') != _DESIGN
            or value.get('language') != 'javascript' or value.get('views') != _VIEWS):
        raise RuntimeError('local report directory view is inconsistent')


def owned_registration_page(store, *, manager_id: str, owner_id: str, after: str, limit: int) -> tuple[list[dict], str | None]:
    if type(limit) is not int or not 1 <= limit <= 100 or not isinstance(after, str) or len(after) > 160:
        raise ValueError('invalid local report directory page')
    ensure_directory_view(store)
    query = urlencode({'startkey': json.dumps([manager_id, owner_id, after], ensure_ascii=False, separators=(',', ':')),
                       'endkey': json.dumps([manager_id, owner_id, '\ufff0'], ensure_ascii=False, separators=(',', ':')),
                       'include_docs': 'true', 'limit': limit + 2})
    status, body = store._request('GET', _DESIGN + '/_view/owned?' + query)
    value = json.loads(body)
    rows = value.get('rows') if isinstance(value, dict) else None
    if status != 200 or not isinstance(rows, list) or len(rows) > limit + 2:
        raise RuntimeError('local report directory response is invalid')
    selected = []
    previous = after
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('doc'), dict) or not isinstance(row.get('key'), list):
            raise RuntimeError('local report directory row is invalid')
        key, doc = row['key'], row['doc']
        if (len(key) != 3 or key[:2] != [manager_id, owner_id] or not isinstance(key[2], str)
                or key[2] < previous or doc.get('report_id') != key[2]):
            raise RuntimeError('local report directory identity is invalid')
        if key[2] == after:
            continue
        if key[2] <= previous:
            raise RuntimeError('local report directory order is invalid')
        previous = key[2]
        selected.append(doc)
    more = len(selected) > limit
    selected = selected[:limit]
    return selected, selected[-1]['report_id'] if more else None
