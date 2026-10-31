"""Narrow local Research protocol for a trusted native host.

The host must authenticate the current session and resolve Profile access;
web messages never supply identity, filesystem paths or allowed Profiles.
"""
from __future__ import annotations

from pathlib import Path

from .local_catalog import LocalResearchCatalog, LocalResearchListingChanged

SCHEMA = 'tr-local-research-bridge:v1'


class LocalResearchRPC:
    def __init__(self, root: Path, *, issuer: str, identity_id: str, profiles: list[dict], manager: dict | None = None) -> None:
        normalized = []
        for item in profiles:
            if not isinstance(item, dict) or set(item) != {'profile_id', 'display_name'}:
                raise ValueError('invalid native Profile binding')
            identifier, label = item['profile_id'], item['display_name']
            if not isinstance(identifier, str) or not isinstance(label, str) or len(label) > 512:
                raise ValueError('invalid native Profile binding')
            normalized.append({'profile_id': identifier, 'display_name': label})
        identifiers = [item['profile_id'] for item in normalized]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError('ambiguous native Profile binding')
        self.store = LocalResearchCatalog(root, issuer=issuer, identity_id=identity_id, profiles=set(identifiers))
        self.binding = {'issuer': issuer.strip().rstrip('/'), 'identity_id': identity_id.strip()}
        self.profiles = normalized
        self.manager = manager

    def request(self, message: object) -> dict:
        if not isinstance(message, dict):
            raise TypeError('invalid local Research message')
        action = message.get('action')
        keys = {
            'capabilities': {'action'}, 'list': {'action', 'profile_id', 'limit', 'offset'},
            'list_researches': {'action', 'profile_id', 'limit', 'offset', 'expected_revision'},
            'get': {'action', 'profile_id', 'research_id'},
            'create': {'action', 'profile_id', 'title', 'description', 'operation_id'},
            'import_research': {'action', 'profile_id', 'research_id'},
            'queue_researches': {'action', 'profile_id', 'research_ids'},
            'list_reports': {'action', 'profile_id', 'research_id', 'limit', 'offset'},
            'list_profile_reports': {'action', 'profile_id', 'limit', 'offset', 'expected_revision'},
            'create_report': {'action', 'profile_id', 'research_id', 'title', 'operation_id'},
            'get_report': {'action', 'profile_id', 'research_id', 'report_id'},
            'get_report_chapter': {'action', 'profile_id', 'research_id', 'report_id', 'chapter_id'},
            'add_report_component': {'action', 'profile_id', 'research_id', 'report_id', 'component_id', 'kind',
                                     'parent_id', 'title', 'body', 'generation', 'root_ref'},
            'publish_report': {'action', 'profile_id', 'research_id', 'report_id'},
            'pull_report': {'action', 'profile_id', 'research_id', 'report_id'},
            'sync_reports': {'action', 'profile_id', 'after_report_id', 'limit'},
        }
        if self.manager is None:
            keys.pop('import_research')
            keys.pop('queue_researches')
            keys.pop('publish_report')
            keys.pop('pull_report')
            keys.pop('sync_reports')
        if not isinstance(action, str) or action not in keys or set(message) != keys[action]:
            raise ValueError('invalid local Research message')
        for key in keys[action] - {'action', 'limit', 'offset', 'generation', 'expected_revision', 'research_ids'}:
            value = message[key]
            if (not isinstance(value, str) or len(value) > (10000 if key in {'description', 'body'} else 512)
                    or any((ord(char) < 32 and not (key in {'description', 'body'} and char in '\n\r\t'))
                           or ord(char) == 127 for char in value)):
                raise ValueError('invalid local Research message')
        if action == 'capabilities':
            value = {'binding': self.binding, 'profiles': self.profiles, 'actions': list(keys)}
        elif action in {'list', 'list_researches', 'list_reports', 'list_profile_reports'}:
            if type(message['limit']) is not int or type(message['offset']) is not int:
                raise ValueError('invalid local Research page')
            if action == 'list':
                value = self.store.page(profile_id=message['profile_id'], limit=message['limit'], offset=message['offset'])
            elif action == 'list_reports':
                value = self.store.list_reports(profile_id=message['profile_id'], research_id=message['research_id'],
                    limit=message['limit'], offset=message['offset'])
            else:
                revision = message['expected_revision']
                if revision is not None and (type(revision) is not int or revision < 0):
                    raise ValueError('invalid local directory revision')
                if (message['offset'] == 0) != (revision is None):
                    raise ValueError('local directory continuation requires a revision')
                try:
                    method = self.store.consistent_page if action == 'list_researches' else self.store.list_profile_reports
                    value = method(profile_id=message['profile_id'], limit=message['limit'],
                                   offset=message['offset'], expected_revision=revision)
                except LocalResearchListingChanged:
                    return {'success': False, 'code': 'local_research_listing_changed'}
        elif action == 'get':
            row = self.store.get(profile_id=message['profile_id'], research_id=message['research_id'])
            if row is None:
                return {'success': False, 'code': 'local_research_not_found'}
            value = {'research': row}
        elif action == 'create':
            value = {'research': self.store.create(profile_id=message['profile_id'], title=message['title'],
                     description=message['description'], operation_id=message['operation_id'])}
        elif action == 'import_research':
            from tools.cli.http import HttpClientError
            from .local_server_research import import_server_research
            try:
                value = import_server_research(self.store, binding=self.binding, manager=self.manager,
                    profile_id=message['profile_id'], research_id=message['research_id'])
            except HttpClientError as exc:
                if exc.status in {401, 403}:
                    return {'success': False, 'code': 'local_report_publication_denied'}
                raise
        elif action == 'queue_researches':
            from .local_server_research import queue_server_researches
            value = {'queued': queue_server_researches(self.store, manager=self.manager,
                     profile_id=message['profile_id'], research_ids=message['research_ids'])}
        elif action == 'create_report':
            value = {'report': self.store.create_report(profile_id=message['profile_id'], research_id=message['research_id'],
                     title=message['title'], operation_id=message['operation_id'])}
        elif action == 'get_report':
            value = self.store.get_report_index(profile_id=message['profile_id'], research_id=message['research_id'],
                     report_id=message['report_id'])
        elif action == 'get_report_chapter':
            value = self.store.get_report_chapter(profile_id=message['profile_id'], research_id=message['research_id'],
                     report_id=message['report_id'], chapter_id=message['chapter_id'])
        elif action == 'add_report_component':
            from .authoring.tree_transactions import ReportVersionConflict
            try:
                value = self.store.add_report_component(**{key: message[key] for key in keys[action] - {'action'}})
            except ReportVersionConflict:
                return {'success': False, 'code': 'local_report_version_conflict'}
        elif action == 'publish_report':
            from tools.cli.http import HttpClientError
            from .local_publication import publish_local_report
            try:
                value = publish_local_report(self.store, binding=self.binding, manager=self.manager,
                    profile_id=message['profile_id'], research_id=message['research_id'], report_id=message['report_id'])
            except HttpClientError as exc:
                if exc.status == 409:
                    return {'success': False, 'code': 'local_report_publication_conflict'}
                if exc.status in {401, 403}:
                    return {'success': False, 'code': 'local_report_publication_denied'}
                raise
        elif action == 'pull_report':
            from tools.cli.http import HttpClientError
            from .local_pull import LocalReportSyncConflict, pull_local_report
            try:
                value = pull_local_report(self.store, binding=self.binding, manager=self.manager,
                    profile_id=message['profile_id'], research_id=message['research_id'], report_id=message['report_id'])
            except LocalReportSyncConflict:
                return {'success': False, 'code': 'local_report_sync_conflict'}
            except HttpClientError as exc:
                if exc.status in {401, 403}:
                    return {'success': False, 'code': 'local_report_publication_denied'}
                raise
        else:
            from .local_auto_sync import sync_published_reports
            value = sync_published_reports(self.store, binding=self.binding, manager=self.manager,
                profile_id=message['profile_id'], after_report_id=message['after_report_id'], limit=message['limit'])
        return {'success': True, 'schema': SCHEMA, **value}
