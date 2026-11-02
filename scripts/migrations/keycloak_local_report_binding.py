"""Review and backfill an old local report's immutable Research binding.

Only metadata is changed. This never creates, updates, or deletes a Keycloak
policy. Operators must quiesce Manager and Keycloak authorization writes,
restore-test their backups and retain a protected migration journal first.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

from server.identity.keycloak_authorization import _RESOURCE_SCOPES, keycloak_resource_name, keycloak_resource_uri
from server.jobs.storage.couchdb_research_publication import publication_id
from server.jobs.storage.couchdb_research_reports import document_id
from server.manager.services.local_report_publication import _receipt_id, _research_binding, _validate_refs

_SCOPES = tuple(sorted(_RESOURCE_SCOPES))


class BindingBackend:
    """Read one origin from existing CouchDB/Keycloak adapters, without policy writes."""

    def __init__(self, *, state, store, manager, adapter, research_id, report_id, owner_id, evaluator=None):
        from server.identity.keycloak_policy_evaluation import KeycloakPolicyEvaluator
        self.state, self.store, self.manager, self.adapter = state, store, manager, adapter
        self.research_id, self.report_id, self.owner_id = research_id, report_id, owner_id
        _validate_refs(research_id, report_id)
        self.settings = dict(manager.settings_provider())
        self.issuer = str(self.settings.get('issuer') or '').rstrip('/')
        if not self.issuer:
            raise ValueError('Keycloak issuer is required')
        self.evaluator = evaluator or KeycloakPolicyEvaluator(allowed_kinds=('research_report',),
            allowed_scopes=_SCOPES, adapter=adapter, settings=self.settings)

    def _settings(self):
        current = self.manager.settings_provider()
        for key in ('issuer', 'base_url', 'backchannel_base_url', 'realm', 'authz_client_id', 'authz_client_secret'):
            if current.get(key) != self.settings.get(key):
                raise ValueError('Keycloak configuration changed during report binding')
        return current

    def read_evidence(self) -> dict:
        from server.identity.keycloak_migration_directory import active_human_subjects
        from server.jobs.storage.couchdb_research_reports import get_research_report
        directory = active_human_subjects(self.adapter)
        subject = directory.get(self.owner_id, '')
        settings = self._settings()
        pat = self.manager.token_provider(settings)
        resource = self.manager._resource(settings, pat, 'research_report', self.report_id)
        resource_id = str(resource.get('_id') or resource.get('id') or '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', resource_id):
            raise ValueError('Keycloak resource identity is invalid')
        policies = self.manager._resource_policies(settings, pat, resource_id)
        if (not isinstance(policies, list) or len(policies) > 5000
                or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] for row in policies)
                or len({row['id'] for row in policies}) != len(policies)):
            raise ValueError('report Keycloak policy inventory is invalid')
        policies = sorted(policies, key=lambda row: row['id'])
        manager_id = str(self.state.server_id)
        status, raw = self.store._request('GET', _receipt_id(manager_id, self.owner_id, self.report_id))
        if status != 200:
            raise ValueError('report registration is unavailable')
        receipt = json.loads(raw)
        publication = get_research_report(self.store, publication_id(manager_id, self.owner_id, self.report_id, 'main'))
        return {'manager_id': manager_id, 'issuer': self.issuer, 'research_id': self.research_id,
                'report_id': self.report_id, 'owner_id': self.owner_id, 'owner_subject': subject,
                'receipt': receipt, 'publication': publication, 'resource': resource,
                'policies': policies, 'directory': directory}

    def read_decisions(self, directory: dict, report_id: str) -> dict:
        if report_id != self.report_id:
            raise ValueError('report identity changed')
        result = {}
        for identity in sorted(directory):
            values = self.evaluator.evaluate(identity, candidates=[('research_report', report_id, _SCOPES)])
            for scope in _SCOPES:
                result[(identity, scope)] = values[('research_report', report_id, scope)]
        return result

    def update_resource(self, resource: dict) -> None:
        settings = self._settings()
        resource_id = str(resource.get('_id') or resource.get('id') or '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', resource_id):
            raise ValueError('Keycloak resource identity is invalid')
        self.manager.request(settings, self.manager.token_provider(settings), 'PUT',
                             'resource_set/' + resource_id, resource)


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def review(*, manager_id: str, issuer: str, research_id: str, report_id: str,
           owner_id: str, owner_subject: str, receipt: dict, publication: dict,
           resource: dict, policies: list, directory: dict, decisions: dict) -> dict:
    """Freeze exact origin, identities, resource and all enumerated decisions."""
    _validate_refs(research_id, report_id)
    if not all(isinstance(value, str) and value.strip() == value and value for value in
               (manager_id, issuer, owner_id, owner_subject)):
        raise ValueError('exact Manager, issuer and owner identities are required')
    if not isinstance(directory, dict) or not 1 <= len(directory) <= 20000:
        raise ValueError('bounded active Keycloak directory is required')
    if (directory.get(owner_id) != owner_subject or len(set(directory.values())) != len(directory)
            or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in directory.items())):
        raise ValueError('Keycloak identity directory is inconsistent')
    expected_decisions = {(identity, scope) for identity in directory for scope in _SCOPES}
    if (not isinstance(decisions, dict) or set(decisions) != expected_decisions
            or any(type(value) is not bool for value in decisions.values())):
        raise ValueError('complete current Keycloak decisions are required')
    if (not isinstance(policies, list) or len(policies) > 5000
            or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] for row in policies)
            or len({row['id'] for row in policies}) != len(policies)):
        raise ValueError('complete Keycloak policy inventory is required')
    intent = receipt.get('creation_intent') if isinstance(receipt, dict) else None
    expected_id = _receipt_id(manager_id, owner_id, report_id)
    if (not isinstance(receipt, dict) or receipt.get('_id') != expected_id
            or receipt.get('kind') != 'research_report_registration' or receipt.get('state') != 'registered'
            or receipt.get('research_id') != research_id or receipt.get('report_id') != report_id
            or receipt.get('manager_id') != manager_id or receipt.get('owner_identity_id') != owner_id
            or receipt.get('owner_subject') != owner_subject or receipt.get('issuer') != issuer.rstrip('/')
            or not isinstance(receipt.get('_rev'), str) or not receipt['_rev']
            or not isinstance(intent, str) or not re.fullmatch(r'[0-9a-f]{64}', intent)):
        raise ValueError('registered report origin is inconsistent')
    identifier = publication_id(manager_id, owner_id, report_id, 'main')
    projection = publication.get('publication') if isinstance(publication, dict) else None
    if (not isinstance(publication, dict) or publication.get('_id') != document_id(identifier)
            or publication.get('kind') != 'research_report' or publication.get('publication_id') != identifier
            or publication.get('research_id') != research_id or publication.get('report_id') != report_id
            or publication.get('branch_ref') != 'main' or publication.get('owner_identity_id') != owner_id
            or type(publication.get('generation')) is not int or publication['generation'] < 0
            or not isinstance(publication.get('projection_hash'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', publication['projection_hash'])
            or not isinstance(projection, dict) or projection.get('publication_id') != identifier
            or projection.get('report_id') != report_id or projection.get('branch_ref') != 'main'
            or projection.get('storage_server_id') != manager_id
            or projection.get('generation') != publication['generation']
            or projection.get('projection_hash') != publication['projection_hash']
            or not isinstance(projection.get('owner_ref'), str) or not projection['owner_ref'].strip()
            or not isinstance(publication.get('_rev'), str) or not publication['_rev']):
        raise ValueError('published report origin is inconsistent')
    resource_id = str(resource.get('_id') or resource.get('id') or '') if isinstance(resource, dict) else ''
    attrs = resource.get('attributes') if isinstance(resource, dict) else None
    uris = resource.get('uris') if isinstance(resource, dict) else None
    if (not resource_id or publication.get('keycloak_resource_id') != resource_id
            or resource.get('name') != keycloak_resource_name('research_report', report_id)
            or resource.get('type') != 'urn:traderesearch:resource:research_report'
            or not isinstance(uris, list) or keycloak_resource_uri('research_report', report_id) not in uris
            or not isinstance(attrs, dict) or attrs.get('traderesearch_owner_subject') != [owner_subject]
            or attrs.get('traderesearch_ref_hash') != [hashlib.sha256(report_id.encode()).hexdigest()]
            or attrs.get('traderesearch_creation_intent') != [intent]):
        raise ValueError('Keycloak report resource does not match its origin')
    existing = attrs.get('traderesearch_research_binding')
    target = _research_binding(research_id, report_id)
    if existing is not None and existing != [target]:
        raise ValueError('Keycloak report is bound to another Research')
    decision_rows = sorted((identity, scope, allowed) for (identity, scope), allowed in decisions.items())
    frozen = {'schema': 'tr-local-report-binding-review:v1', 'manager_id': manager_id,
              'issuer': issuer.rstrip('/'), 'receipt_sha256': _hash(receipt),
              'publication_sha256': _hash(publication), 'resource_sha256': _hash(resource),
              'policies_sha256': _hash(sorted(policies, key=lambda row: row['id'])),
              'directory_sha256': _hash(directory), 'decisions_sha256': _hash(decision_rows),
              'binding_sha256': target, 'status': 'already_bound' if existing is not None else 'ready'}
    return {**frozen, 'sha256': _hash(frozen)}


def stage(*, approved: dict, read_evidence, read_decisions, update_resource, record) -> dict:
    """Backfill one resource without re-granting; require manual recovery on failure.

    ``read_evidence`` must freshly return the complete keyword arguments for
    ``review`` except decisions; ``read_decisions`` must freshly evaluate all
    active users and scopes. ``record`` must durably journal each call.
    """
    def capture():
        evidence = read_evidence()
        decisions = read_decisions(evidence['directory'], evidence['report_id'])
        return evidence, decisions, review(**evidence, decisions=decisions)

    evidence, decisions, current = capture()
    if current != approved:
        raise ValueError('report binding evidence changed after review')
    if current['status'] == 'already_bound':
        return {'status': 'already_bound', 'cutover_ready': False}
    resource = copy.deepcopy(evidence['resource'])
    attrs = resource['attributes']
    attrs['traderesearch_research_binding'] = [current['binding_sha256']]
    record({'event': 'binding_intent', 'plan_sha256': current['sha256'],
            'resource_sha256': current['resource_sha256']})
    try:
        update_resource(resource)
        after, actual, new = capture()
        expected_resource = copy.deepcopy(after['resource'])
        expected_attrs = expected_resource.get('attributes')
        if not isinstance(expected_attrs, dict) or expected_attrs.pop('traderesearch_research_binding', None) != [current['binding_sha256']]:
            raise ValueError('updated report binding is not confirmed')
        if (expected_resource != evidence['resource'] or actual != decisions
                or after['directory'] != evidence['directory'] or after['policies'] != evidence['policies']
                or after['receipt'] != evidence['receipt']
                or after['publication'] != evidence['publication'] or new['status'] != 'already_bound'):
            raise ValueError('report resource or effective permissions changed during migration')
    except Exception:
        record({'event': 'binding_unresolved', 'plan_sha256': current['sha256']})
        raise
    record({'event': 'binding_verified', 'plan_sha256': current['sha256']})
    return {'status': 'bound', 'cutover_ready': False}
