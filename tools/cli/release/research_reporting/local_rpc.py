"""Narrow local Research protocol for a trusted native host.

The host must authenticate the current session and resolve Profile access;
web messages never supply identity, filesystem paths or allowed Profiles.
"""
from __future__ import annotations

from pathlib import Path

from .local_catalog import LocalResearchCatalog

SCHEMA = 'tr-local-research-bridge:v1'


class LocalResearchRPC:
    def __init__(self, root: Path, *, issuer: str, identity_id: str, profiles: list[dict]) -> None:
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
        }
        if not isinstance(action, str) or action not in keys or set(message) != keys[action]:
            raise ValueError('invalid local Research message')
        for key in keys[action] - {'action', 'limit', 'offset'}:
            value = message[key]
            if (not isinstance(value, str) or len(value) > (10000 if key == 'description' else 512)
                    or any((ord(char) < 32 and not (key == 'description' and char in '\n\r\t'))
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
        else:
            value = {'report': self.store.create_report(profile_id=message['profile_id'], research_id=message['research_id'],
                     title=message['title'], operation_id=message['operation_id'])}
        return {'success': True, 'schema': SCHEMA, **value}
