"""Register and publish one explicitly selected client-local report.

The only durable registration record is a CouchDB recovery receipt. It is
never an authorization grant: every operation still checks current Keycloak
permissions. No server-side Research Profile or private report tree is made.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode

from server.identity.keycloak_authorization import AuthorizationUnavailable, keycloak_resource_name
from server.identity.keycloak_research import KeycloakResearchGrantManager
from server.jobs.storage.couchdb_research_publication import prepare_projection, publication_id
from server.manager.services.research_couchdb_publication import ResearchCouchPublicationService
from tools.cli.release.research_reporting.generation import report_workspace_lock


def _validate_refs(research_id: str, report_id: str) -> None:
    for prefix, value in (('research:v1:', research_id), ('report:v1:', report_id)):
        if not isinstance(value, str) or not value.startswith(prefix) or not re.fullmatch(
                r'[A-Za-z0-9_-]{24,128}', value[len(prefix):]):
            raise ValueError('new local Research and Report identifiers must be opaque v1 references')


def _receipt_id(manager_id: str, owner_id: str, report_id: str) -> str:
    raw = json.dumps([manager_id, owner_id, report_id], ensure_ascii=False, separators=(',', ':')).encode()
    return 'research-report-registration:' + hashlib.sha256(raw).hexdigest()


class LocalReportPublicationService(ResearchCouchPublicationService):
    def __init__(self, *, state, store, manager=None, admission=None, authorize_many=None):
        options = {}
        if admission is not None: options['admission'] = admission
        if authorize_many is not None: options['authorize_many'] = authorize_many
        super().__init__(state=state, catalog=None, store=store, **options)
        self._local_manager = manager or KeycloakResearchGrantManager()

    def _manager(self):
        return self._local_manager

    def _validate_target(self, research_id: str, report_id: str):
        _validate_refs(research_id, report_id)

    def _read_receipt(self, ref):
        try:
            status, body = self.store._request('GET', ref)
        except HTTPError as exc:
            if exc.code == 404: return None
            raise
        if status != 200:
            raise RuntimeError('report registration store returned an invalid response')
        value = json.loads(body)
        if not isinstance(value, dict):
            raise AuthorizationUnavailable('report registration receipt is invalid')
        return value

    def _put_receipt(self, receipt):
        try:
            status, body = self.store._request('PUT', receipt['_id'], json.dumps(
                receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
        except HTTPError as exc:
            if exc.code == 409:
                raise AuthorizationUnavailable('report registration changed; retry') from None
            raise
        response = json.loads(body)
        if status not in {201, 202} or not isinstance(response, dict) or response.get('ok') is not True:
            raise RuntimeError('report registration store did not confirm the update')
        if not isinstance(response.get('rev'), str):
            raise RuntimeError('report registration revision is unavailable')
        return {**receipt, '_rev': response['rev']}

    def _validate_receipt(self, receipt, *, research_id, report_id, owner_id, subject, issuer):
        expected = _receipt_id(str(self.state.server_id), owner_id, report_id)
        if (not isinstance(receipt, dict) or receipt.get('_id') != expected
                or receipt.get('kind') != 'research_report_registration'
                or receipt.get('research_id') != research_id or receipt.get('report_id') != report_id
                or receipt.get('owner_identity_id') != owner_id or receipt.get('owner_subject') != subject
                or receipt.get('issuer') != issuer or receipt.get('manager_id') != self.state.server_id
                or receipt.get('state') not in {'pending', 'creating', 'registered'}
                or not isinstance(receipt.get('creation_intent'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', receipt['creation_intent'])
                or not isinstance(receipt.get('_rev'), str)):
            raise AuthorizationUnavailable('report registration identity requires repair')
        return receipt

    def _validate_owner(self, research_id, report_id, resource, owner_id, owner_ref):
        owners = (resource.get('attributes') or {}).get('traderesearch_owner_subject')
        issuer = str(self._manager().settings_provider().get('issuer') or '').rstrip('/')
        receipt = self._read_receipt(_receipt_id(str(self.state.server_id), owner_id, report_id))
        if not isinstance(owners, list) or len(owners) != 1:
            raise AuthorizationUnavailable('report owner identity is unavailable')
        self._validate_receipt(receipt, research_id=research_id, report_id=report_id,
                               owner_id=owner_id, subject=owners[0], issuer=issuer)
        if (receipt['state'] != 'registered' or not owner_ref
                or (resource.get('attributes') or {}).get('traderesearch_creation_intent') != [receipt['creation_intent']]):
            raise AuthorizationUnavailable('report registration requires repair')

    def publish_local(self, *, session: dict, research_id: str, report_id: str, branch_ref: str,
                      projection: dict, expected_revision: str | None) -> dict:
        self._validate_target(research_id, report_id)
        manager = self._manager()
        actor, identity = self._verified_identity(session, manager)
        if not self.admission(session, state=self.state, use_cache=False)[0]:
            raise PermissionError('current Manager access is not authorized')
        owner = manager.user_by_identity(identity.identity_id)
        if (not isinstance(owner, dict) or owner.get('id') != identity.subject or owner.get('enabled') is not True
                or (owner.get('attributes') or {}).get('tr_identity_id') != [identity.identity_id]):
            raise PermissionError('current Keycloak identity is not available')
        publication_id(str(self.state.server_id), identity.identity_id, report_id, branch_ref)
        if expected_revision is not None and (not isinstance(expected_revision, str) or len(expected_revision) > 256):
            raise ValueError('expected CouchDB revision is invalid')
        prepared = prepare_projection(projection, report_id=report_id)
        marker_id = _receipt_id(str(self.state.server_id), identity.identity_id, report_id)
        lock_root = Path(self.state.state_root) / '.local-report-registration' / hashlib.sha256(report_id.encode()).hexdigest()[:2]
        with report_workspace_lock(lock_root):
            if not self.admission(session, state=self.state, use_cache=False)[0]:
                raise PermissionError('current Manager access is not authorized')
            receipt = self._read_receipt(marker_id)
            if receipt is None:
                receipt = self._put_receipt({'_id': marker_id, 'kind': 'research_report_registration',
                    'manager_id': self.state.server_id, 'research_id': research_id, 'report_id': report_id,
                    'owner_identity_id': identity.identity_id, 'owner_subject': identity.subject,
                    'issuer': identity.issuer.rstrip('/'), 'creation_intent': secrets.token_hex(32), 'state': 'pending'})
            receipt = self._validate_receipt(receipt, research_id=research_id, report_id=report_id,
                owner_id=identity.identity_id, subject=identity.subject, issuer=identity.issuer.rstrip('/'))
            settings = manager.settings_provider()
            pat = manager.token_provider(settings)
            name = keycloak_resource_name('research_report', report_id)
            query = urlencode({'name': name, 'first': 0, 'max': 10, 'deep': 'true'})
            try:
                _, found, _ = manager.request(settings, pat, 'GET', 'resource_set?' + query)
            except Exception as exc:
                raise AuthorizationUnavailable('report Keycloak resource search is unavailable') from exc
            rows = found if isinstance(found, list) else found.get('resources', []) if isinstance(found, dict) else None
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise AuthorizationUnavailable('report Keycloak resource search is invalid')
            matches = [row for row in rows if row.get('name') == name]
            if len(matches) > 1:
                raise AuthorizationUnavailable('report Keycloak resource is ambiguous')
            if not matches:
                if receipt['state'] != 'pending':
                    raise AuthorizationUnavailable('report registration outcome needs repair')
                receipt = self._put_receipt({**receipt, 'state': 'creating'})
                if not self.admission(session, state=self.state, use_cache=False)[0]:
                    raise PermissionError('current Manager access is not authorized')
                manager.ensure_resource(resource_type='research_report', resource_ref=report_id,
                    owner_subject=identity.subject, creation_intent=receipt['creation_intent'], create_only=True)
            resource = manager._resource(settings, pat, 'research_report', report_id)
            attrs = resource.get('attributes') or {}
            if (attrs.get('traderesearch_owner_subject') != [identity.subject]
                    or attrs.get('traderesearch_creation_intent') != [receipt['creation_intent']]):
                raise AuthorizationUnavailable('report resource belongs to another registration')
            if receipt['state'] != 'registered':
                receipt = self._put_receipt({**receipt, 'state': 'registered'})
        # Existing resources are only evaluated, never re-ensured: a revoked
        # Keycloak owner policy cannot be recreated by a publication retry.
        return super().publish(session=session, research_id=research_id, report_id=report_id,
                               branch_ref=branch_ref, projection=projection,
                               expected_revision=expected_revision, _prepared=prepared)

    def list_grants(self, *, session: dict, research_id: str, report_id: str) -> list[dict]:
        manager = self._manager()
        actor, _identity = self._verified_identity(session, manager)
        _resource, _owner, _ref, authorize_now = self._context(
            session=session, research_id=research_id, report_id=report_id, scopes=('share',))
        authorize_now()
        grants = manager.list_user_grants(actor=actor, resource_type='research_report', resource_ref=report_id)
        authorize_now()
        return grants

    def set_grant(self, *, session: dict, research_id: str, report_id: str,
                  identity_id: str, scopes: list[str]) -> bool:
        if (not isinstance(identity_id, str) or not identity_id.strip() or len(identity_id) > 512
                or '\x00' in identity_id or not isinstance(scopes, list)
                or any(not isinstance(scope, str) or scope not in {'read', 'use', 'write'} for scope in scopes)):
            raise ValueError('invalid report grant')
        manager = self._manager()
        actor, _identity = self._verified_identity(session, manager)
        _resource, _owner, _ref, authorize_now = self._context(
            session=session, research_id=research_id, report_id=report_id, scopes=('share',))
        authorize_now()
        user = manager.user_by_identity(identity_id)
        if (not isinstance(user, dict) or not isinstance(user.get('id'), str) or not user['id']
                or type(user.get('enabled')) is not bool
                or (scopes and user['enabled'] is not True)
                or (user.get('attributes') or {}).get('tr_identity_id') != [identity_id]):
            raise LookupError('Keycloak recipient identity is unavailable or ambiguous')
        # Recheck admission and the same report immediately before the grant.
        # A username is never used as a cross-realm identity.
        authorize_now()
        return manager.set_user_grant(actor=actor, resource_type='research_report', resource_ref=report_id,
            source='explicit', identity_id=identity_id, subject=user['id'], scopes=scopes)
