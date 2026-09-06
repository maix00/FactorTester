"""Hydrate one authorized Strategy revision on detail/edit/execution demand."""
import hashlib
import json
from urllib.request import Request, urlopen

from server.manager.services.data_plane_client import loopback_client_access
from tools.data.sqlite.db import connect_sqlite


class StrategyRevisionHydrator:
    def __init__(self, state):
        self.state = state

    def __call__(self, revision_ref, *, principal):
        service = self.state.strategy_library
        revision = service.store.get_revision(revision_ref)
        if not revision:
            raise KeyError('strategy revision not found')
        entry = service.store.get_entry(revision['strategy_ref'])
        if not entry or not service._access(entry, principal)['can_view']:
            raise PermissionError('strategy revision is outside your visible scope')
        row = self.state.account_domain_sync.local.get_entity(entry['owner_ref'], 'strategy_revision', revision_ref)
        metadata = (row or {}).get('payload') or {}
        size = int(metadata.get('object_bytes') or 0)
        digest = str(metadata.get('object_sha256') or '')
        if not 0 < size <= 4 * 1024 * 1024 or len(digest) != 64:
            raise ValueError('strategy revision source manifest is unavailable')
        access = self.state.prepare_object_download(
            principal=principal, storage_server_id=metadata['storage_server_id'],
            object_kind='strategy_revision', object_id=revision_ref,
            expected_size=size, expected_sha256=digest,
            idempotency_key=f'hydrate-strategy:{self.state.server_id}:{revision_ref}:{digest}',
            content_type='application/json',
        )
        url, tls = loopback_client_access(access['url'])
        request = Request(url, headers={'Authorization': f"Bearer {access['bearer']}"})
        with urlopen(request, timeout=30, context=tls) as response:
            raw = response.read(size + 1)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('strategy revision source object hash mismatch')
        value = json.loads(raw)
        if value.get('revision_ref') != revision_ref or value.get('source_sha256') != revision['source_sha256']:
            raise ValueError('strategy revision metadata mismatch')
        source = value.get('source_code')
        if not isinstance(source, str) or hashlib.sha256(source.encode('utf-8')).hexdigest() != revision['source_sha256']:
            raise ValueError('strategy source hash mismatch')
        with connect_sqlite(service.store.db_path) as db:
            db.execute('UPDATE strategy_library_revisions SET source_code=?,hooks_json=? WHERE revision_ref=? AND source_sha256=?',
                       (value['source_code'], json.dumps(value.get('hooks') or []), revision_ref, revision['source_sha256']))
        return service.store.get_revision(revision_ref)
