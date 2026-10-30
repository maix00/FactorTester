"""Plan explicit object-owner bindings for a reviewed Keycloak cutover.

Metadata only: never load factor source or report attachments. The caller
provides the reviewed legacy-owner -> subject map. Report placeholder owners
can only be resolved through an exact Job identity, never a default user.
Apply uses the existing Keycloak resource registrar, not a second policy store.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json


def plan_resources(documents: list[dict], subjects: dict[str, str], *,
                   jobs: dict[str, dict] | None = None) -> dict:
    records, unresolved, public = {}, [], []
    for doc in documents:
        kind, ref = str(doc.get('kind') or ''), str(doc.get('_id') or '')
        owner = str(doc.get('owner_ref') or doc.get('owner') or '')
        if kind in {'factor_family', 'factor_family_head'}:
            if doc.get('source_kind') == 'public':
                public.append(ref)
                continue
            factor_id = str(doc.get('factor_id') or '')
            resource_type, resource_ref = 'factor_source', f'custom:{owner}:{factor_id}'
            valid = bool(factor_id and owner and doc.get('source_kind') == 'custom')
        elif kind in {'report', 'job_test_report'}:
            if owner == '__legacy_report_migration__':
                job = (jobs or {}).get(str(doc.get('job_id') or ''))
                owner = str((job or {}).get('owner') or '')
            resource_type, resource_ref, valid = 'job_test_report', ref, bool(ref)
        elif kind in {'strategy_version', 'strategy_revision'}:
            resource_type, resource_ref = 'strategy', str(doc.get('strategy_ref') or ref)
            valid = bool(resource_ref)
        elif kind in {'research_report', 'product_group'}:
            resource_type, resource_ref, valid = kind, ref, bool(ref)
        else:
            unresolved.append({'document_id': ref, 'reason': 'unsupported_kind'})
            continue
        subject = subjects.get(owner)
        if not valid or not subject:
            unresolved.append({'document_id': ref, 'reason': 'unmapped_owner_or_identity'})
            continue
        key = (resource_type, resource_ref)
        record = records.setdefault(key, {'resource_type': resource_type,
            'resource_ref': resource_ref, 'owner': owner, 'owner_subject': subject,
            'documents': []})
        if record['owner_subject'] != subject:
            raise ValueError('conflicting owners for the same frozen resource')
        record['documents'].append({'document_id': ref, 'expected_rev': doc.get('_rev'),
            'previous_owner': doc.get('owner'),
            'previous_resource_id': doc.get('keycloak_resource_id')})
    ordered = sorted(records.values(), key=lambda row: (row['resource_type'], row['resource_ref']))
    ref_hash = hashlib.sha256(json.dumps(sorted(str(d.get('_id') or '') for d in documents),
        separators=(',', ':')).encode()).hexdigest()
    return {'resources': ordered, 'unresolved': unresolved, 'public_documents': public,
            'summary': {'documents': len(documents), 'resources': len(ordered),
                'unresolved': len(unresolved), 'public': len(public),
                'ref_sha256': ref_hash,
                'kinds': dict(Counter(str(d.get('kind')) for d in documents))}}


def apply_resources(plan: dict, *, register) -> list[dict]:
    if plan['unresolved']:
        raise ValueError('unresolved object mappings block cutover')
    return [{**record, 'resource_id': register(resource_type=record['resource_type'],
        resource_ref=record['resource_ref'], owner_subject=record['owner_subject'])}
        for record in plan['resources']]


def bind_document(store, record: dict, document: dict) -> None:
    """CAS-add a permission binding; preserve all bytes and attachment stubs.

    The reviewed record doubles as a rollback journal of the changed fields.
    Any concurrent edit or preexisting different binding blocks this document.
    """
    from urllib.parse import quote
    path = quote(document['document_id'], safe='')
    _, raw = store._request('GET', path)
    current = json.loads(raw)
    if current.get('_rev') != document['expected_rev']:
        raise ValueError('document changed after the reviewed inventory')
    previous = current.get('keycloak_resource_id')
    if previous and previous != record['resource_id']:
        raise ValueError('existing authorization binding conflicts with migration')
    if current.get('owner') != document['previous_owner']:
        raise ValueError('document owner changed after the reviewed inventory')
    current['keycloak_resource_id'] = record['resource_id']
    if record['resource_type'] == 'job_test_report':
        current['owner'] = record['owner']
    store._request('PUT', path, json.dumps(current).encode())
