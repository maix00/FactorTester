"""Narrow local Research protocol for a trusted native host.

The host must authenticate the current session and resolve Profile access;
web messages never supply identity, filesystem paths or allowed Profiles.
"""
from __future__ import annotations

from pathlib import Path

from .local_catalog import LocalResearchCatalog

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
            'get': {'action', 'profile_id', 'research_id'},
            'create': {'action', 'profile_id', 'title', 'description', 'operation_id'},
            'list_reports': {'action', 'profile_id', 'research_id', 'limit', 'offset'},
            'create_report': {'action', 'profile_id', 'research_id', 'title', 'operation_id'},
            'get_report': {'action', 'profile_id', 'research_id', 'report_id'},
            'get_report_chapter': {'action', 'profile_id', 'research_id', 'report_id', 'chapter_id'},
            'add_report_component': {'action', 'profile_id', 'research_id', 'report_id', 'component_id', 'kind',
                                     'parent_id', 'title', 'body', 'generation', 'root_ref'},
            'publish_report': {'action', 'profile_id', 'research_id', 'report_id'},
        }
        if self.manager is None:
            keys.pop('publish_report')
        if not isinstance(action, str) or action not in keys or set(message) != keys[action]:
            raise ValueError('invalid local Research message')
        for key in keys[action] - {'action', 'limit', 'offset', 'generation'}:
            value = message[key]
            if (not isinstance(value, str) or len(value) > (10000 if key in {'description', 'body'} else 512)
                    or any((ord(char) < 32 and not (key in {'description', 'body'} and char in '\n\r\t'))
                           or ord(char) == 127 for char in value)):
                raise ValueError('invalid local Research message')
        if action == 'capabilities':
            value = {'binding': self.binding, 'profiles': self.profiles, 'actions': list(keys)}
        elif action in {'list', 'list_reports'}:
            if type(message['limit']) is not int or type(message['offset']) is not int:
                raise ValueError('invalid local Research page')
            if action == 'list':
                value = self.store.page(profile_id=message['profile_id'], limit=message['limit'], offset=message['offset'])
            else:
                value = self.store.list_reports(profile_id=message['profile_id'], research_id=message['research_id'],
                    limit=message['limit'], offset=message['offset'])
        elif action == 'get':
            row = self.store.get(profile_id=message['profile_id'], research_id=message['research_id'])
            if row is None:
                return {'success': False, 'code': 'local_research_not_found'}
            value = {'research': row}
        elif action == 'create':
            value = {'research': self.store.create(profile_id=message['profile_id'], title=message['title'],
                     description=message['description'], operation_id=message['operation_id'])}
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
        else:
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
        return {'success': True, 'schema': SCHEMA, **value}
