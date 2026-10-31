"""Keycloak-authorized publication of a single Research report to CouchDB."""
from __future__ import annotations

import hashlib
import json
import os
import re

from server.identity.keycloak_authorization import (
    AuthorizationUnavailable, keycloak_authorized_many, keycloak_resource_name, keycloak_resource_uri,
)
from server.identity.server_admission import server_admission
from server.jobs.storage.couchdb_research_publication import _KEYS, _SAFE_MEDIA, commit_shared_report, publication_id
from server.jobs.storage.couchdb_research_reports import get_research_report
from tools.cli.release.research_reporting.public_research.object_uploads import projection_hash


def report_store_from_environment():
    """Build the same bounded report store for browser and signed peer reads."""
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore
    couch = str(os.environ.get('TRADERESEARCH_COUCHDB_URL')
                or os.environ.get('FACTORTESTER_COUCHDB_URL') or '').strip()
    if not couch:
        raise OSError('Research report store is unavailable')
    database = str(os.environ.get('TRADERESEARCH_COUCHDB_DB')
                   or os.environ.get('FACTORTESTER_COUCHDB_DB') or 'ft_objects').strip()
    return CouchDBObjectStore(couch, database,
        username=os.environ.get('TRADERESEARCH_COUCHDB_USER') or os.environ.get('FACTORTESTER_COUCHDB_USER', ''),
        password=os.environ.get('TRADERESEARCH_COUCHDB_PASSWORD') or os.environ.get('FACTORTESTER_COUCHDB_PASSWORD', ''))


class ResearchCouchPublicationService:
    def __init__(self, *, state, catalog, store, admission=server_admission,
                 authorize_many=keycloak_authorized_many):
        self.state, self.catalog, self.store = state, catalog, store
        self.admission, self.authorize_many = admission, authorize_many

    def _manager(self):
        return self.catalog._profile_grant_manager

    def _validate_target(self, research_id: str, report_id: str):
        self.catalog.require_keycloak_sharing()
        self.catalog._keycloak_share_target(research_id, 'report', report_id)

    def _validate_owner(self, research_id, report_id, resource, owner_id, owner_ref):
        report = self.catalog._report_row(report_id)
        if not owner_ref or owner_ref != str(report['owner_ref']):
            raise AuthorizationUnavailable('report owner requires identity repair')

    @staticmethod
    def _verified_identity(session, manager):
        if not isinstance(session, dict):
            raise PermissionError('verified Keycloak report publisher is required')
        actor = str(session.get('username') or '').strip()
        identity = manager.identity_provider(actor)
        if (identity is None or identity.username != actor
                or identity.subject != session.get('keycloak_subject')
                or identity.issuer.rstrip('/') != str(session.get('keycloak_issuer') or '').rstrip('/')
                or identity.identity_id != session.get('tr_identity_id')):
            raise PermissionError('verified Keycloak report publisher is required')
        return actor, identity

    def _context(self, *, session: dict, research_id: str, report_id: str, scopes: tuple[str, ...]):
        self._validate_target(research_id, report_id)
        manager = self._manager()
        actor, identity = self._verified_identity(session, manager)

        def resource_and_owner():
            settings = manager.settings_provider()
            resource = manager._resource(settings, manager.token_provider(settings), 'research_report', report_id)
            owners = (resource.get('attributes') or {}).get('traderesearch_owner_subject')
            resource_id = str(resource.get('_id') or resource.get('id') or '').strip()
            if (not resource_id or not isinstance(owners, list) or len(owners) != 1
                    or not isinstance(owners[0], str) or not owners[0]):
                raise AuthorizationUnavailable('report Keycloak identity is unavailable')
            owner = manager.user_provider(owners[0])
            attrs = owner.get('attributes') if isinstance(owner, dict) else None
            stable = attrs.get('tr_identity_id') if isinstance(attrs, dict) else None
            legacy = attrs.get('legacy_username') if isinstance(attrs, dict) else None
            if (not isinstance(owner, dict) or owner.get('id') != owners[0] or owner.get('enabled') is not True
                    or not isinstance(stable, list) or len(stable) != 1
                    or not isinstance(stable[0], str) or not stable[0]
                    or (legacy is not None and (not isinstance(legacy, list) or len(legacy) != 1))):
                raise AuthorizationUnavailable('report owner stable identity is unavailable')
            verified = manager.user_by_identity(stable[0])
            if not isinstance(verified, dict) or verified.get('id') != owners[0]:
                raise AuthorizationUnavailable('report owner stable identity is ambiguous')
            owner_ref = str(legacy[0] if legacy is not None else owner.get('username') or '').strip()
            self._validate_owner(research_id, report_id, resource, stable[0], owner_ref)
            return resource_id, stable[0], owner_ref

        resource_id, owner_id, owner_ref = resource_and_owner()
        uri, name = keycloak_resource_uri('research_report', report_id), keycloak_resource_name('research_report', report_id)

        def authorize_now():
            if not self.admission(session, state=self.state, use_cache=False)[0]:
                raise PermissionError('current Manager access is not authorized')
            current = manager.identity_provider(actor)
            if (current != identity or current.token != identity.token
                    or resource_and_owner() != (resource_id, owner_id, owner_ref)):
                raise PermissionError('report publisher or owner identity changed')
            self._validate_target(research_id, report_id)
            decisions = self.authorize_many(identity.token,
                permissions=[(uri, name, scope) for scope in scopes], use_cache=False)
            if any(decisions.get((uri, scope)) is not True for scope in scopes):
                raise PermissionError('current report access is not authorized')

        return resource_id, owner_id, owner_ref, authorize_now

    def publish(self, *, session: dict, research_id: str, report_id: str, branch_ref: str,
                projection: dict, expected_revision: str | None, _prepared=None, _authoring=None) -> dict:
        resource_id, owner_id, owner_ref, authorize_now = self._context(
            session=session, research_id=research_id, report_id=report_id, scopes=('write', 'share'))

        # Fail before reading or preparing untrusted report bytes as well as
        # immediately before the compare-and-set write.
        authorize_now()
        return commit_shared_report(self.store, manager_id=self.state.server_id, owner_id=owner_id,
            owner_ref=owner_ref, research_id=research_id, report_id=report_id, branch_ref=branch_ref,
            keycloak_resource_id=resource_id, projection=projection, expected_revision=expected_revision,
            authorize_now=authorize_now, prepared=_prepared, authoring=_authoring)

    def read(self, *, session: dict, research_id: str, report_id: str, publication_ref: str = '',
             branch_ref: str = '', attachment: str = '', metadata_only: bool = False, requires_publish: bool = False,
             requires_edit: bool = False) -> dict:
        if (type(metadata_only) is not bool or type(requires_publish) is not bool or type(requires_edit) is not bool
                or (metadata_only and attachment) or ((requires_publish or requires_edit) and not metadata_only)):
            raise ValueError('invalid report metadata request')
        scopes = ('read', 'write', 'share') if requires_publish else ('read', 'write') if requires_edit or attachment.startswith('report_authoring/') else ('read',)
        resource_id, owner_id, owner_ref, authorize_now = self._context(
            session=session, research_id=research_id, report_id=report_id, scopes=scopes)
        authorize_now()
        if branch_ref:
            derived = publication_id(self.state.server_id, owner_id, report_id, branch_ref)
            if publication_ref and publication_ref != derived:
                raise PermissionError('report publication does not belong to the selected branch')
            publication_ref = derived
        if not re.fullmatch(r'p-[0-9a-f]{64}', str(publication_ref or '')):
            raise ValueError('report publication or branch identity is required')
        document = get_research_report(self.store, publication_ref)
        branch = str(document.get('branch_ref') or '')
        if (document.get('publication_id') != publication_ref or document.get('research_id') != research_id
                or document.get('report_id') != report_id or document.get('owner_identity_id') != owner_id
                or document.get('keycloak_resource_id') != resource_id
                or publication_id(self.state.server_id, owner_id, report_id, branch) != publication_ref):
            raise PermissionError('report publication identity does not match')
        attachments = document.get('attachments')
        if not isinstance(attachments, dict):
            raise ValueError('report attachment index is invalid')
        authoring = document.get('authoring')
        if authoring is not None:
            from tools.cli.release.research_reporting.authoring.tree_schema import node_reference
            if (not isinstance(authoring, dict) or set(authoring) != {'sha256', 'root_ref', 'generation', 'size_bytes'}
                    or not re.fullmatch(r'[0-9a-f]{64}', str(authoring.get('sha256') or ''))
                    or authoring.get('generation') != document.get('generation')
                    or type(authoring.get('size_bytes')) is not int or not 0 < authoring['size_bytes'] <= 8 * 1024 * 1024):
                raise ValueError('report authoring metadata is invalid')
            node_reference(authoring['root_ref'])
        if attachment.startswith('report_authoring/') and (
                authoring is None or attachment != 'report_authoring/' + authoring['sha256']):
            raise ValueError('report authoring identity is invalid')
        record = document.get('publication')
        if (not isinstance(record, dict) or record.get('publication_id') != publication_ref
                or record.get('report_id') != report_id or record.get('owner_ref') != owner_ref
                or record.get('branch_ref') != branch or record.get('storage_server_id') != self.state.server_id
                or record.get('projection_hash') != document.get('projection_hash')
                or not re.fullmatch(r'[0-9a-f]{64}', str(record.get('projection_hash') or ''))
                or record.get('generation') != document.get('generation')
                or type(record.get('generation')) is not int or record['generation'] < 0
                or not isinstance(document.get('_rev'), str) or not document['_rev']):
            raise ValueError('report publication metadata is invalid')
        fields = ('publication_id', 'report_id', 'owner_ref', 'title', 'generation',
                  'projection_hash', 'branch_ref', 'storage_server_id')
        public_record = {**{key: record[key] for key in fields if key in record},
                         'authorization': 'keycloak', 'revision': document['_rev']}
        if metadata_only:
            authorize_now()
            return {'publication': public_record, **({'authoring': authoring} if authoring is not None else {}),
                    **({'edit_authorized': True} if requires_edit else {})}
        key = attachment or 'projection.json'
        if attachment and not any(attachment.startswith(kind + '/') for kind in (
                'research_asset', 'research_attachment', 'research_local_resource', 'report_authoring')):
            raise ValueError('report attachment reference is invalid')
        metadata = attachments.get(key)
        if not isinstance(metadata, dict) or not isinstance(metadata.get('name'), str):
            raise KeyError('report attachment is unavailable')
        if attachment.startswith('report_authoring/') and (metadata.get('sha256') != authoring['sha256']
                or metadata.get('size_bytes') != authoring['size_bytes']):
            raise ValueError('report authoring attachment metadata is invalid')
        name = metadata['name']
        expected_suffix = 'bin' if attachment else 'json'
        if not re.fullmatch(r'[0-9a-f]{64}\.' + expected_suffix, name) or metadata.get('sha256') != name[:64]:
            raise ValueError('report attachment identity is invalid')
        data = self.store.get_attachment(document['_id'], name)
        if (not isinstance(data, bytes) or len(data) > 8 * 1024 * 1024
                or metadata.get('size_bytes') != len(data)
                or metadata.get('sha256') != hashlib.sha256(data).hexdigest()):
            raise ValueError('report attachment integrity check failed')
        if attachment:
            authorize_now()
            media = str(metadata.get('content_type') or '').lower()
            return {'content': data, 'content_type': media if media in _SAFE_MEDIA else 'application/octet-stream'}
        result = json.loads(data)
        if (not isinstance(result, dict) or set(result) - _KEYS or result.get('report_id') != report_id
                or result.get('projection_hash') != document.get('projection_hash')
                or projection_hash(result) != document.get('projection_hash')):
            raise ValueError('report projection integrity check failed')
        authorize_now()
        return {'publication': public_record,
                'projection': result, **({'authoring': authoring} if authoring is not None else {})}
