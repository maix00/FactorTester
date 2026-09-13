"""Authenticated branch reservation and publication verification routes."""
from __future__ import annotations

import re
from urllib.parse import unquote
from server.manager.http.responses import json_response

_ROUTE = re.compile(r'/api/research/reports/([^/]+)/branches(?:/([^/]+)/publish)?')


class ResearchBranchRoutesMixin:
    def _get_report_branch_route(self, parsed, viewer: str) -> bool:
        match = _ROUTE.fullmatch(parsed.path)
        if not match or match.group(2):
            return False
        branches = self._research_catalog_service().list_report_branches(unquote(match.group(1)), viewer=viewer)
        json_response(self, {'success': True, 'branches': branches})
        return True

    def _post_report_branch_route(self, parsed, actor: str, data: dict) -> bool:
        match = _ROUTE.fullmatch(parsed.path)
        if not match:
            return False
        self._require_branch_profile_actor(data.get('profile_ref'))
        report_id = unquote(match.group(1))
        service = self._research_catalog_service()
        if not match.group(2):
            branch = service.reserve_report_branch(report_id, actor=actor,
                profile_ref=data.get('profile_ref'), branch_id=data.get('branch_id'), title=data.get('title', ''),
                source_branch_id=data.get('source_branch_id', ''),
                source_generation=data.get('source_generation', 0), source_revision=data.get('source_revision', ''))
        else:
            branch_id = unquote(match.group(2))
            publication_id = data.get('publication_id')
            research = self._research_service()
            try:
                candidates = [p for p in research.list_visible(actor) if p.get('publication_id') == publication_id]
                if len(candidates) != 1:
                    raise ValueError('published report object is unavailable or ambiguous')
                publication = candidates[0]
                if (publication.get('report_id'), publication.get('owner_ref'), publication.get('profile_ref'),
                    publication.get('branch_ref')) != (report_id, actor, data.get('profile_ref'), branch_id):
                    raise PermissionError('published object does not belong to the reserved report branch Profile')
                index = research.index(publication_id, actor)
            except PermissionError:
                raise
            except (ConnectionError, OSError) as error:
                json_response(self, {'success': False, 'error': str(error)}, 503)
                return True
            if (index.get('report_id') != report_id
                    or index.get('generation') != publication.get('generation')
                    or index.get('projection_hash') != publication.get('projection_hash')):
                raise ValueError('published report version changed during verification')
            branch = service.publish_report_branch(report_id, branch_id, actor=actor,
                profile_ref=data.get('profile_ref'), expected_generation=data.get('expected_generation'),
                expected_revision=data.get('expected_revision'), generation=index.get('generation'),
                revision=index.get('projection_hash'), publication_id=publication_id,
                storage_server_id=publication.get('storage_server_id'))
        json_response(self, {'success': True, 'branch': branch})
        return True

    def _require_branch_profile_actor(self, profile_ref: str) -> None:
        authentication = getattr(self.state, 'session_authentication', None)
        if callable(authentication) and authentication(self._bearer_token()) == 'agent':
            matcher = getattr(self.state, 'agent_session_matches', None)
            if not callable(matcher) or not matcher(self._bearer_token(), profile_ref,
                                                   self.headers.get('X-FactorTester-Agent-Claim', '')):
                raise PermissionError('Agent capability belongs to another Profile')
