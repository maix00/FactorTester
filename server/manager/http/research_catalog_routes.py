"""Canonical Manager routes for Research ownership and relationships."""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response
from .research_branch_routes import ResearchBranchRoutesMixin
from cryptography.fernet import Fernet, InvalidToken

# Opaque, process-local cursors cannot reveal IDs of denied rows. A Manager
# restart invalidates them; clients restart their scan without deleting data.
_OWNED_SYNC_CURSOR = Fernet(Fernet.generate_key())


class ResearchCatalogRoutesMixin(ResearchBranchRoutesMixin):
    """Expose the Research catalog without duplicating report/Evidence stores."""

    def _research_catalog_service(self):
        service = getattr(self.state, "research_catalog", None)
        if service is None:
            raise RuntimeError("Research catalog is unavailable")
        return service

    def _research_couch_service(self, *, local=False):
        from server.manager.services.research_couchdb_publication import ResearchCouchPublicationService, report_store_from_environment
        store = report_store_from_environment()
        if local:
            from server.manager.services.local_report_publication import LocalReportPublicationService
            return LocalReportPublicationService(state=self.state, store=store)
        return ResearchCouchPublicationService(state=self.state, catalog=self._research_catalog_service(), store=store)

    def _refresh_research_catalog(self, principal: str) -> None:
        client = getattr(self.state, "client_state", None)
        if client is not None:
            client._refresh_account_domain_async(principal)

    def _research_catalog_session(self):
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return None
        return session

    def _research_catalog_body(self, maximum: int = 2 * 1024 * 1024) -> dict:
        value = self._json_body(maximum)
        if not isinstance(value, dict):
            raise TypeError("request body must be an object")
        return value

    def _research_catalog_error(self, exc: Exception) -> None:
        from server.identity.keycloak_authorization import AuthorizationUnavailable
        from server.manager.services.research_catalog import (
            KeycloakResearchCreationUnavailable, KeycloakResearchSharingUnavailable,
        )
        code = None
        if isinstance(exc, KeycloakResearchCreationUnavailable):
            status, code = 409, "keycloak_research_creation_unavailable"
        elif isinstance(exc, KeycloakResearchSharingUnavailable):
            status, code = 409, "keycloak_sharing_unavailable"
        elif isinstance(exc, AuthorizationUnavailable):
            status = 503
        elif isinstance(exc, PermissionError):
            status = 403
        elif isinstance(exc, LookupError):
            status = 404
        elif isinstance(exc, (TypeError, ValueError)):
            status = 400
        else:
            status = 500
        json_response(self, {"success": False, "error": str(exc), **({"code": code} if code else {})}, status)

    def _get_research_catalog_routes(self, parsed) -> bool:
        if not self._is_research_catalog_path(parsed.path):
            return False
        session = self._research_catalog_session()
        if session is None:
            return True
        viewer = str(session["username"])
        publication = re.fullmatch(
            r"/api/research/([^/]+)/reports/([^/]+)/couchdb-publication"
            r"(?:/(p-[0-9a-f]{64})(?:/attachments/(research_asset|research_attachment|research_local_resource|report_authoring)/([^/]+))?)?",
            parsed.path,
        )
        local_publication = re.fullmatch(
            r"/api/research/local-report-publication"
            r"(?:/(p-[0-9a-f]{64})(?:/attachments/(research_asset|research_attachment|research_local_resource|report_authoring)/([^/]+))?)?",
            parsed.path,
        )
        local_grants = parsed.path == '/api/research/local-report-publication/grants'
        local_discovery = parsed.path == '/api/research/owned-local-report-sync'
        if publication is None and local_publication is None and not local_grants and not local_discovery and parsed.path not in {'/api/research/owned-sync', '/api/research/owned-report-sync'}:
            self._refresh_research_catalog(viewer)
        # A byte-owner peer verifies its own catalog. Resolve a local catalog
        # only when the selected local operation actually needs it.
        service = None if publication or local_publication or local_grants or local_discovery else self._research_catalog_service()
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if local_discovery:
                if set(query) - {'cursor', 'limit'} or any(len(query.get(key, [])) > 1 for key in ('cursor', 'limit')):
                    raise ValueError('invalid local Report synchronization query')
                stable_id = str(session.get('tr_identity_id') or '')
                if not stable_id:
                    raise PermissionError('verified stable identity is required')
                token = query.get('cursor', [''])[0]
                if len(token) > 2048:
                    raise ValueError('invalid local Report synchronization cursor')
                after = ''
                if token:
                    try:
                        cursor = json.loads(_OWNED_SYNC_CURSOR.decrypt(token.encode('ascii'), ttl=3600))
                        if (not isinstance(cursor, dict) or set(cursor) != {'kind', 'identity_id', 'manager_id', 'report_id'}
                                or cursor['kind'] != 'owned-local-report' or cursor['identity_id'] != stable_id
                                or cursor['manager_id'] != self.state.server_id
                                or not re.fullmatch(r'report:v1:[A-Za-z0-9_-]{24,128}', cursor['report_id'])):
                            raise ValueError('invalid cursor identity')
                        after = cursor['report_id']
                    except (InvalidToken, UnicodeError, ValueError, KeyError, TypeError):
                        raise ValueError('invalid local Report synchronization cursor') from None
                payload = self._research_couch_service(local=True).owned_page(session=session, after=after,
                    limit=int(query.get('limit', ['50'])[0]))
                cursor = payload.pop('next_cursor')
                payload['next_cursor'] = (_OWNED_SYNC_CURSOR.encrypt(json.dumps({'kind': 'owned-local-report',
                    'identity_id': stable_id, 'manager_id': self.state.server_id, 'report_id': cursor},
                    separators=(',', ':')).encode()).decode('ascii') if cursor else None)
                json_response(self, {'success': True, **payload})
                return True
            if local_grants:
                if len(query.get('research_id', [])) != 1 or len(query.get('report_id', [])) != 1:
                    raise ValueError('Research and Report references are required')
                value = self._research_couch_service(local=True).list_grants(session=session,
                    research_id=query['research_id'][0], report_id=query['report_id'][0])
                json_response(self, {'success': True, 'grants': value})
                return True
            if publication or local_publication:
                if publication:
                    research_id, report_id, publication_ref = unquote(publication.group(1)), unquote(publication.group(2)), publication.group(3)
                    kind, object_id = publication.group(4), publication.group(5)
                else:
                    if len(query.get('research_id', [])) != 1 or len(query.get('report_id', [])) != 1:
                        raise ValueError('Research and Report references are required')
                    research_id, report_id = query['research_id'][0], query['report_id'][0]
                    publication_ref, kind, object_id = local_publication.group(1), local_publication.group(2), local_publication.group(3)
                attachment = (kind + '/' + unquote(object_id)) if kind else ''
                if query.get('metadata_only', ['0']) not in (['0'], ['1']):
                    raise ValueError('invalid report metadata option')
                metadata_only = query.get('metadata_only') == ['1']
                if query.get('requires_publish', ['0']) not in (['0'], ['1']):
                    raise ValueError('invalid report authorization option')
                requires_publish = query.get('requires_publish') == ['1']
                if query.get('requires_edit', ['0']) not in (['0'], ['1']):
                    raise ValueError('invalid report authorization option')
                requires_edit = query.get('requires_edit') == ['1']
                if query.get('owner_metadata', ['0']) not in (['0'], ['1']):
                    raise ValueError('invalid owner metadata option')
                owner_metadata = query.get('owner_metadata') == ['1']
                if owner_metadata and (not local_publication or not metadata_only or attachment):
                    raise ValueError('owner metadata requires local report metadata')
                if metadata_only and attachment:
                    raise ValueError('metadata is not an attachment')
                if (requires_publish or requires_edit) and not metadata_only:
                    raise ValueError('authorization preflight requires metadata')
                if len(query.get('server_id', [])) > 1:
                    raise ValueError('only one report server may be selected')
                server_id = str(query.get('server_id', [''])[0] or '').strip()
                if owner_metadata and server_id and server_id not in {'local', self.state.server_id}:
                    raise ValueError('remote owner metadata is not available through this route')
                branch_ref = '' if publication_ref else str(query.get('branch_ref', [''])[0])
                view = query.get('view', [''])[0]
                if (len(query.get('view', [])) > 1 or view not in {'', 'index', 'chapter', 'markdown'}
                        or (view and (metadata_only or attachment or local_publication))
                        or (view == 'chapter' and (len(query.get('chapter_id', [])) != 1 or not query['chapter_id'][0]))):
                    raise ValueError('invalid report reader view')
                if server_id and server_id not in {'local', self.state.server_id}:
                    from server.identity.server_admission import server_admission
                    from server.modules.single_factor_test.execution_nodes import peer_execution_route
                    route = peer_execution_route(self.state, server_id)
                    value = self.state.federation_gateway.public_data(route, kind='shared-report', operation='read',
                        principal=viewer, delegated_user_token=self._bearer_token(), payload={
                            'research_id': research_id, 'report_id': report_id,
                            'publication_ref': publication_ref or '', 'branch_ref': branch_ref, 'attachment': attachment,
                            'metadata_only': metadata_only, 'requires_publish': requires_publish, 'requires_edit': requires_edit,
                            **({'source_kind': 'catalog'} if publication else {})})
                    if not server_admission(session, state=self.state, use_cache=False)[0]:
                        raise PermissionError('current Manager access is not authorized')
                    if attachment:
                        try:
                            raw = base64.b64decode(value['content_base64'], validate=True)
                        except (KeyError, TypeError, ValueError, binascii.Error):
                            raise ValueError('peer report attachment is invalid') from None
                        if len(raw) > 8 * 1024 * 1024:
                            raise ValueError('peer report attachment exceeds its limit')
                        from server.jobs.storage.couchdb_research_publication import _SAFE_MEDIA
                        media = str(value.get('content_type') or '').lower()
                        value = {'content': raw, 'content_type': media if media in _SAFE_MEDIA else 'application/octet-stream'}
                    else:
                        record, projected = value.get('publication'), value.get('projection')
                        if (not isinstance(record, dict) or (not metadata_only and not isinstance(projected, dict))
                                or (requires_edit and value.get('edit_authorized') is not True)
                                or (requires_publish and value.get('publish_authorized') is not True)
                                or record.get('report_id') != report_id or (not metadata_only and projected.get('report_id') != report_id)
                                or record.get('storage_server_id') != server_id
                                or (publication_ref and record.get('publication_id') != publication_ref)
                                or (branch_ref and record.get('branch_ref') != branch_ref)):
                            raise PermissionError('peer report identity does not match')
                        value = {'publication': record, **({'projection': projected} if not metadata_only else {}),
                                 **({'authoring': value['authoring']} if 'authoring' in value else {}),
                                 **({'edit_authorized': True} if requires_edit else {}),
                                 **({'publish_authorized': True} if requires_publish else {})}
                else:
                    value = self._research_couch_service(local=bool(local_publication)).read(session=session,
                        research_id=research_id, report_id=report_id,
                        publication_ref=publication_ref or '', branch_ref=branch_ref, attachment=attachment,
                        **({'metadata_only': True} if metadata_only else {}),
                        **({'requires_publish': True} if requires_publish else {}),
                        **({'requires_edit': True} if requires_edit else {}))
                    if owner_metadata:
                        value['owner_metadata'] = self._research_couch_service(local=True).owner_metadata(
                            session=session, research_id=research_id, report_id=report_id)
                if attachment:
                    raw, content_type = value['content'], value['content_type']
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Cache-Control', 'private, no-store')
                    self.send_header('Content-Disposition', 'attachment' if content_type == 'application/octet-stream' else 'inline')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return True
                if view:
                    projection = value['projection']
                    if view == 'index':
                        from tools.cli.release.research_reporting.public_research.projection import projection_index
                        value = projection_index(projection)
                    elif view == 'chapter':
                        from tools.cli.release.research_reporting.public_research.projection import chapter_projection
                        value = chapter_projection(projection, query['chapter_id'][0])
                    else:
                        from tools.cli.release.research_reporting.report_export import markdown_export, document_identity
                        record = value['publication']
                        try:
                            raw, media, _ = markdown_export(projection, query.get('format', ['md'])[0],
                                identity=document_identity(branch=record['branch_ref'], owner=record['owner_ref'],
                                    generation=record['generation'], revision=record['revision'],
                                    projection_hash=record['projection_hash'], report_id=report_id))
                        except NotImplementedError as error:
                            json_response(self, {'success': False, 'error': str(error)}, 501)
                            return True
                        self.send_response(200)
                        self.send_header('Content-Type', media)
                        self.send_header('Cache-Control', 'private, no-store')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.send_header('Content-Length', str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                        return True
                payload = value
            elif self._get_report_branch_route(parsed, viewer):
                return True
            elif parsed.path == "/api/research/capabilities/keycloak-sharing":
                payload = {"capabilities": service.keycloak_sharing_capabilities()}
            elif parsed.path == "/api/research/owned-sync":
                if any(len(query.get(key, [])) > 1 for key in ('cursor', 'limit')) or set(query) - {'cursor', 'limit'}:
                    raise ValueError('invalid owned Research synchronization query')
                stable_id = str(session.get('tr_identity_id') or '')
                if not stable_id:
                    raise PermissionError('verified stable identity is required')
                token = query.get('cursor', [''])[0]
                if len(token) > 2048:
                    raise ValueError('invalid owned Research synchronization cursor')
                if token:
                    try:
                        cursor = json.loads(_OWNED_SYNC_CURSOR.decrypt(token.encode('ascii'), ttl=3600))
                        if not isinstance(cursor, dict) or set(cursor) != {'identity_id', 'updated_at', 'research_id'} or cursor['identity_id'] != stable_id:
                            raise ValueError('invalid cursor identity')
                        after_time, after_ref = cursor['updated_at'], cursor['research_id']
                    except (InvalidToken, UnicodeError, ValueError, KeyError, TypeError):
                        raise ValueError('invalid owned Research synchronization cursor') from None
                else:
                    after_time, after_ref = 0, ''
                payload = service.owned_sync_page(viewer=viewer, after_time=after_time,
                    after_ref=after_ref, limit=int(query.get('limit', ['50'])[0]))
                cursor = payload.pop('next_cursor')
                payload['next_cursor'] = (_OWNED_SYNC_CURSOR.encrypt(json.dumps({
                    'identity_id': stable_id, **cursor}, separators=(',', ':')).encode()).decode('ascii') if cursor else None)
            elif parsed.path == "/api/research/owned-report-sync":
                if (set(query) - {'research_id', 'cursor', 'limit'} or len(query.get('research_id', [])) != 1
                        or any(len(query.get(key, [])) > 1 for key in ('cursor', 'limit'))):
                    raise ValueError('invalid owned Report synchronization query')
                stable_id, research_id = str(session.get('tr_identity_id') or ''), query['research_id'][0]
                if not stable_id:
                    raise PermissionError('verified stable identity is required')
                token = query.get('cursor', [''])[0]
                if len(token) > 2048:
                    raise ValueError('invalid owned Report synchronization cursor')
                after_ref = ''
                if token:
                    try:
                        cursor = json.loads(_OWNED_SYNC_CURSOR.decrypt(token.encode('ascii'), ttl=3600))
                        if (not isinstance(cursor, dict) or set(cursor) != {'identity_id', 'research_id', 'report_id'}
                                or cursor['identity_id'] != stable_id or cursor['research_id'] != research_id):
                            raise ValueError('invalid cursor identity')
                        after_ref = cursor['report_id']
                    except (InvalidToken, UnicodeError, ValueError, KeyError, TypeError):
                        raise ValueError('invalid owned Report synchronization cursor') from None
                payload = service.owned_report_sync_page(viewer=viewer, research_id=research_id, after_ref=after_ref,
                    limit=int(query.get('limit', ['50'])[0]))
                cursor = payload.pop('next_cursor')
                payload['next_cursor'] = (_OWNED_SYNC_CURSOR.encrypt(json.dumps({'identity_id': stable_id,
                    'research_id': research_id, 'report_id': cursor}, separators=(',', ':')).encode()).decode('ascii')
                    if cursor else None)
            elif parsed.path == "/api/research":
                scope = str(query.get("scope", ["all"])[0] or "all")
                subordinate_refs = (
                    self._research_catalog_subordinate_refs(viewer)
                    if scope == "subordinates" else []
                )
                value = service.list_researches(
                    viewer=viewer,
                    include_archived=query.get("include_archived") == ["1"],
                    scope=scope,
                    subordinate_refs=subordinate_refs,
                )
                payload = {"researches": value, "items": value, "scope": scope}
            elif parsed.path == "/api/research/principals":
                needle = str(query.get("q", [""])[0]).strip().casefold()
                if set(query) - {"q"}:
                    raise ValueError("legacy Research relation filters are not supported")
                try:
                    candidates = self._subordinate_users(session)
                except PermissionError:
                    # A non-administrator has no managed directory scope.
                    candidates = []
                values = []
                for item in candidates:
                    username = str(item.get("username") or "").strip()
                    if (
                        not username or username == viewer
                        or (needle and needle not in username.casefold())
                    ):
                        continue
                    values.append({"principal_ref": username, "label": username})
                payload = {"principals": sorted(values, key=lambda item: item["label"])[:100]}
            elif parsed.path == "/api/research/reports":
                scope = str(query.get("scope", ["all"])[0] or "all")
                value = service.list_reports_for_scope(
                    viewer=viewer,
                    include_archived=query.get("include_archived") == ["1"],
                    scope=scope,
                    subordinate_refs=(self._research_catalog_subordinate_refs(viewer)
                                      if scope == "subordinates" else []),
                )
                value = self._research_catalog_publication_branches(value, viewer)
                payload = {
                    "reports": value,
                    "items": value,
                    "count": len(value),
                    "scope": scope,
                }
            else:
                research_id, child = self._research_catalog_target(parsed.path)
                if child is None:
                    payload = {
                        "research": service.get_research_summary(
                            research_id, viewer=viewer,
                        ),
                    }
                elif child == "members":
                    payload = {
                        "members": service.list_members(
                            research_id, viewer=viewer,
                        ),
                    }
                elif child == "workspaces":
                    payload = {
                        "workspaces": service.list_workspaces(
                            research_id, viewer=viewer,
                        ),
                    }
                elif child == "reports":
                    reports = service.list_reports(
                        research_id, viewer=viewer,
                    )
                    payload = {
                        "reports": self._research_catalog_publication_branches(
                            reports, viewer,
                        ),
                    }
                elif child == "evidence":
                    payload = {
                        "evidence_links": service.list_evidence_links(
                            research_id, viewer=viewer,
                        ),
                    }
                elif child == "collaboration-branches":
                    # Use the same readable metadata projection as the report
                    # page; no local workspace scan or report-byte download.
                    reports = self._research_catalog_publication_branches(
                        service.list_reports(research_id, viewer=viewer), viewer,
                    )
                    seen: set[str] = set()
                    branches: list[dict[str, Any]] = []
                    for rep in reports:
                        for br in rep.get("branches") or []:
                            publication_id = str(
                                br.get("publication_id") or "",
                            ).strip()
                            if not publication_id or publication_id in seen:
                                continue
                            seen.add(publication_id)
                            branches.append({
                                **br,
                                "report_id": str(rep.get("report_id") or ""),
                                "owner_ref": str(rep.get("owner_ref") or ""),
                                "research_id": research_id,
                                "profile_ref": str(
                                    br.get("profile_ref") or ""
                                ),
                            })
                    payload = {"branches": branches}
                elif child == "manifest":
                    manifest = service.research_manifest(
                        research_id, viewer=viewer,
                    )
                    manifest["source_server_id"] = str(self.state.server_id)
                    payload = {"manifest": manifest}
                elif child == "keycloak-share-links":
                    service.require_keycloak_sharing()
                    payload = {"share_links": service.list_keycloak_share_links(
                        research_id, actor=viewer, target_kind=str(query.get("target_kind", ["research"])[0]),
                        report_id=str(query.get("report_id", [""])[0]))}
                elif child == "keycloak-sharing-capabilities":
                    payload = {"capabilities": service.keycloak_target_sharing_capabilities(
                        research_id, actor=viewer, target_kind=str(query.get("target_kind", ["research"])[0]),
                        report_id=str(query.get("report_id", [""])[0]))}
                elif child == "keycloak-grants":
                    service.require_keycloak_grants()
                    payload = {"grants": service.list_explicit_grants(
                        research_id, actor=viewer, target_kind=str(query.get("target_kind", ["research"])[0]),
                        report_id=str(query.get("report_id", [""])[0]))}
                else:
                    raise KeyError("research route not found")
        except (LookupError, PermissionError, TypeError, ValueError, RuntimeError, OSError) as exc:
            if (publication or local_publication or local_grants) and isinstance(exc, OSError) and not isinstance(exc, PermissionError):
                from urllib.error import HTTPError
                missing = isinstance(exc, FileNotFoundError) or isinstance(exc, HTTPError) and exc.code == 404
                json_response(self, {"success": False,
                    "code": "research_publication_not_found" if missing else "research_store_unavailable",
                    "error": "Research publication not found" if missing else "Research report store is unavailable"},
                    404 if missing else 503)
                return True
            self._research_catalog_error(exc)
            return True
        json_response(self, {"success": True, **payload})
        return True

    def _research_catalog_publication_branches(
        self, reports: list[dict], viewer: str,
    ) -> list[dict]:
        """Attach readable server projections without loading report bytes."""
        try:
            publications = self._research_service().list_visible(viewer)
        except (AttributeError, ConnectionError, OSError, RuntimeError, ValueError):
            publications = []
        by_report: dict[str, list[dict]] = {}
        for item in publications:
            if not isinstance(item, dict):
                continue
            report_id = str(item.get("report_id") or "").strip()
            publication_id = str(item.get("publication_id") or "").strip()
            if report_id and publication_id:
                by_report.setdefault(report_id, []).append(item)
        result = []
        for original in reports:
            value = dict(original)
            local = [dict(item) for item in value.get("branches") or []]
            # A registered head is authoritative even when the publication store
            # also retains older immutable snapshots of this branch.
            registered = [item for item in local if item.get("branch_id") and item.get("status") == "active"]
            metadata = {item['publication_id']: item for item in by_report.get(str(value.get('report_id') or ''), [])}
            for item in registered:
                publication = metadata.get(item.get('publication_id'), {})
                if publication.get('owner_ref') == item.get('principal_ref') and publication.get('updated_at'):
                    item['updated_at'] = publication['updated_at']
            projected = []
            for item in by_report.get(str(value.get("report_id") or ""), []):
                if str(item.get("owner_ref") or "") != str(value.get("owner_ref") or ""):
                    continue
                projected.append({
                    "branch_ref": str(item.get("branch_ref") or "main"),
                    "title": str(item.get("branch_ref") or "main"),
                    "profile_ref": str(item.get("profile_ref") or value.get("profile_ref") or ""),
                    "principal_ref": str(item.get("owner_ref") or ""),
                    "updated_at": item.get("updated_at") or 0,
                    "source_kind": "publication",
                    "source_ref": str(item.get("publication_id") or ""),
                    "publication_id": str(item.get("publication_id") or ""),
                    "selected": not projected,
                })
            if projected:
                for item in local:
                    item["selected"] = False
            # A branch has several transports, not several identities. Publications
            # are readable across Managers; authoring refs are local-only fallbacks.
            seen = set()
            branches = []
            for item in [*registered, *projected, *local]:
                key = (
                    str(item.get("principal_ref") or value.get("owner_ref") or ""),
                    str(item.get("profile_ref") or value.get("profile_ref") or ""),
                    str(item.get("branch_ref") or item.get("publication_id") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                branches.append(item)
            value["branches"] = branches
            content_times = [item.get("updated_at") for item in branches if item.get("updated_at")]
            if content_times:
                value["updated_at"] = max(content_times)
            result.append(value)
        return result

    def _post_research_catalog_routes(self, parsed) -> bool:
        if not self._is_research_catalog_path(parsed.path):
            return False
        session = self._research_catalog_session()
        if session is None:
            return True
        actor = str(session["username"])
        publication = re.fullmatch(r"/api/research/([^/]+)/reports/([^/]+)/couchdb-publication", parsed.path)
        local_publication = parsed.path == '/api/research/local-report-publication'
        local_grants = parsed.path == '/api/research/local-report-publication/grants'
        service = None if local_publication or local_grants else self._research_catalog_service()
        try:
            data = self._research_catalog_body(32 * 1024 * 1024 if publication or local_publication else 2 * 1024 * 1024)
            if local_grants:
                if set(data) != {'research_id', 'report_id', 'identity_id', 'scopes'}:
                    raise ValueError('report grant fields are invalid')
                changed = self._research_couch_service(local=True).set_grant(session=session,
                    research_id=data['research_id'], report_id=data['report_id'],
                    identity_id=data['identity_id'], scopes=data['scopes'])
                json_response(self, {'success': True, 'changed': changed})
                return True
            if local_publication:
                if set(data) - {'research_id', 'report_id', 'branch_ref', 'projection', 'expected_revision', 'authoring', 'research_title'}:
                    raise ValueError('unsupported report publication fields')
                value = self._research_couch_service(local=True).publish_local(session=session,
                    research_id=data.get('research_id'), report_id=data.get('report_id'),
                    branch_ref=str(data.get('branch_ref') or ''), projection=data.get('projection'),
                    expected_revision=data.get('expected_revision'), authoring=data.get('authoring'),
                    research_title=data.get('research_title'))
                json_response(self, {'success': True, 'publication': value}, 201)
                return True
            if publication:
                if set(data) - {"branch_ref", "projection", "expected_revision", "authoring"}:
                    raise ValueError("unsupported report publication fields")
                value = self._research_couch_service().publish(
                    session=session, research_id=unquote(publication.group(1)), report_id=unquote(publication.group(2)),
                    branch_ref=str(data.get("branch_ref") or ""), projection=data.get("projection"),
                    expected_revision=data.get("expected_revision"),
                    **({'authoring': data['authoring']} if 'authoring' in data else {}))
                json_response(self, {"success": True, "publication": value}, 201)
                return True
            if self._post_report_branch_route(parsed, actor, data):
                return True
            if parsed.path == "/api/research/keycloak-create":
                service.require_keycloak_research_creation()
                if set(data) - {"title", "description", "profile_ref"}:
                    raise ValueError("legacy Research access fields are not supported")
                value = service.create_research(
                    owner_ref=actor,
                    title=data.get("title"),
                    description=str(data.get("description") or ""),
                    profile_ref=str(data.get("profile_ref") or ""),
                )
                json_response(self, {"success": True, "research": value}, 201)
                return True
            if parsed.path in {"/api/research/migrations/reports", "/api/research/migrations/reports/discover"}:
                json_response(self, {"success": False, "error": "Legacy report import is retired; use reviewed Keycloak migration"}, 410)
                return True
            if parsed.path == "/api/research/keycloak-share-links/redeem":
                service.require_keycloak_sharing()
                value = service.redeem_share_link(
                    str(data.get("token") or ""), actor=actor,
                )
                json_response(self, {"success": True, "grant": value})
                return True
            research_id, child = self._research_catalog_target(parsed.path)
            if child == "members":
                value = service.add_membership(
                    research_id,
                    actor=actor,
                    principal_ref=data.get("principal_ref"),
                    profile_ref=data.get("profile_ref"),
                    role=str(data.get("role") or "contributor"),
                    status=str(data.get("status") or "active"),
                )
                json_response(self, {"success": True, "member": value}, 201)
                return True
            if child == "workspaces":
                value = service.create_workspace(
                    research_id,
                    actor=actor,
                    principal_ref=data.get("principal_ref") or actor,
                    profile_ref=data.get("profile_ref"),
                    title=str(data.get("title") or ""),
                )
                json_response(self, {"success": True, "workspace": value}, 201)
                return True
            if child == "reports":
                if {"visibility", "authorized_users"} & set(data):
                    raise ValueError("legacy Research report ACL fields are not supported")
                if data.get("report_id"):
                    value = service.register_report(
                        research_id,
                        actor=actor,
                        report_id=data.get("report_id"),
                        title=str(data.get("title") or ""),
                        profile_ref=str(data.get("profile_ref") or ""),
                        workspace_id=str(data.get("workspace_id") or ""),
                        build_source=str(data.get("build_source") or "client"),
                        build_source_ref=str(data.get("build_source_ref") or ""),
                        source_ref=str(data.get("source_ref") or ""),
                    )
                else:
                    value = service.create_report_space(
                        research_id,
                        actor=actor,
                        title=str(data.get("title") or ""),
                        profile_ref=str(data.get("profile_ref") or ""),
                    )
                json_response(self, {"success": True, "report": value}, 201)
                return True
            if child == "keycloak-share-links":
                service.require_keycloak_sharing()
                value = service.create_share_link(
                    target_kind=str(data.get("target_kind") or "research"),
                    research_id=research_id,
                    report_id=str(data.get("report_id") or ""),
                    actor=actor,
                    mode=str(data.get("mode") or "permanent"),
                    expires_at=float(data.get("expires_at") or 0),
                )
                json_response(self, {"success": True, "share_link": value}, 201)
                return True
            if child == "keycloak-grants":
                service.require_keycloak_grants()
                value = service.set_explicit_grant(research_id, actor=actor,
                    principal_ref=data.get("principal_ref"), scopes=data.get("scopes"),
                    target_kind=str(data.get("target_kind") or "research"),
                    report_id=str(data.get("report_id") or ""))
                json_response(self, {"success": True, "grant": value})
                return True
            if child == "evidence":
                value = service.link_evidence(
                    research_id,
                    actor=actor,
                    evidence_ref=data.get("evidence_ref"),
                    evidence_owner_ref=str(data.get("evidence_owner_ref") or ""),
                    report_id=str(data.get("report_id") or ""),
                    branch_ref=str(data.get("branch_ref") or ""),
                    job_id=str(data.get("job_id") or ""),
                    profile_ref=str(data.get("profile_ref") or ""),
                    purpose=str(data.get("purpose") or ""),
                )
                json_response(self, {"success": True, "evidence_link": value}, 201)
                return True
            raise KeyError("research route not found")
        except (LookupError, PermissionError, TypeError, ValueError, RuntimeError, OSError) as exc:
            from server.jobs.storage.couchdb_research_publication import ResearchPublicationConflict
            if isinstance(exc, ResearchPublicationConflict):
                json_response(self, {"success": False, "code": "research_publication_conflict",
                                     "error": "Research publication revision changed"}, 409)
                return True
            if (publication or local_publication or local_grants) and isinstance(exc, OSError) and not isinstance(exc, PermissionError):
                json_response(self, {"success": False, "code": "research_store_unavailable",
                                     "error": "Research report store is unavailable"}, 503)
                return True
            self._research_catalog_error(exc)
            return True

    def _patch_research_catalog_routes(self, parsed) -> bool:
        share_match = re.fullmatch(
            r"/api/research/([^/]+)/keycloak-share-links/([^/]+)", parsed.path,
        )
        if share_match:
            session = self._research_catalog_session()
            if session is None:
                return True
            try:
                data = self._research_catalog_body()
                if data.get("revoked") is not True:
                    raise ValueError("share link patch requires revoked=true")
                self._research_catalog_service().require_keycloak_sharing()
                value = self._research_catalog_service().revoke_share_link(
                    unquote(share_match.group(1)),
                    unquote(share_match.group(2)),
                    actor=str(session["username"]),
                )
            except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
                self._research_catalog_error(exc)
                return True
            json_response(self, {"success": True, "share_link": value})
            return True
        report_match = re.fullmatch(
            r"/api/research/([^/]+)/reports/([^/]+)", parsed.path,
        )
        if report_match:
            session = self._research_catalog_session()
            if session is None:
                return True
            try:
                data = self._research_catalog_body()
                if {"visibility", "authorized_users"} & set(data):
                    raise ValueError("legacy Research report ACL fields are not supported")
                value = self._research_catalog_service().update_report(
                    unquote(report_match.group(1)),
                    unquote(report_match.group(2)),
                    actor=str(session["username"]),
                )
            except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
                self._research_catalog_error(exc)
                return True
            json_response(self, {"success": True, "report": value})
            return True
        match = re.fullmatch(r"/api/research/([^/]+)", parsed.path)
        if not match:
            return False
        session = self._research_catalog_session()
        if session is None:
            return True
        try:
            data = self._research_catalog_body()
            if {"visibility", "authorized_users"} & set(data):
                raise ValueError("legacy Research ACL fields are not supported")
            value = self._research_catalog_service().update_research(
                unquote(match.group(1)),
                actor=str(session["username"]),
                title=data.get("title"),
                description=data.get("description"),
                status=data.get("status"),
            )
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
            self._research_catalog_error(exc)
            return True
        json_response(self, {"success": True, "research": value})
        return True

    def _delete_research_catalog_routes(self, parsed) -> bool:
        research_match = re.fullmatch(r"/api/research/([^/]+)", parsed.path)
        report_match = re.fullmatch(
            r"/api/research/([^/]+)/reports/([^/]+)", parsed.path,
        )
        member_match = re.fullmatch(
            r"/api/research/([^/]+)/members/([^/]+)", parsed.path,
        )
        if not research_match and not report_match and not member_match:
            return False
        session = self._research_catalog_session()
        if session is None:
            return True
        actor = str(session["username"])
        try:
            if research_match:
                value = self._research_catalog_service().remove_research(
                    unquote(research_match.group(1)), actor=actor,
                )
                payload = {"research": value}
            elif report_match:
                value = self._research_catalog_service().remove_report(
                    unquote(report_match.group(1)),
                    unquote(report_match.group(2)),
                    actor=actor,
                )
                payload = {"report": value}
            else:
                value = self._research_catalog_service().remove_membership(
                    unquote(member_match.group(1)),
                    profile_ref=unquote(member_match.group(2)),
                    principal_ref=parse_qs(parsed.query).get("principal_ref", [None])[0],
                    actor=actor,
                )
                payload = {"member": value}
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError) as exc:
            self._research_catalog_error(exc)
            return True
        json_response(self, {"success": True, **payload})
        return True

    @staticmethod
    def _is_research_catalog_path(path: str) -> bool:
        return path == "/api/research" or path.startswith("/api/research/")

    def _research_catalog_subordinate_refs(self, viewer: str) -> list[str]:
        # The directory helper consumes verified claims, not a username.
        # Never let a caller-provided viewer substitute another user's claims.
        session = self._session()
        if not isinstance(session, dict) or str(session.get("username") or "") != str(viewer):
            raise PermissionError("verified user session required")
        subordinate_users = self._subordinate_users(session)
        return [
            str(item.get("username") or item.get("owner_ref") or "").strip()
            for item in subordinate_users
            if isinstance(item, dict)
        ]

    @staticmethod
    def _research_catalog_target(path: str) -> tuple[str, str | None]:
        match = re.fullmatch(
            r"/api/research/([^/]+)(?:/(members|workspaces|reports|evidence|manifest|collaboration-branches|keycloak-share-links|keycloak-grants|keycloak-sharing-capabilities))?",
            path,
        )
        if not match:
            raise KeyError("research route not found")
        return unquote(match.group(1)), match.group(2)


__all__ = ["ResearchCatalogRoutesMixin"]
