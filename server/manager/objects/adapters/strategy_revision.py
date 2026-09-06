"""Immutable Strategy revision bytes carried by the existing 7997 transport."""
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from server.manager.storage.account_domain.strategy_sync import revision_bytes
from server.services.strategy_library.store import StrategyLibraryStore


class StrategyRevisionOriginAdapter:
    def __init__(self, *, database, cache_root):
        self.store = StrategyLibraryStore(database)
        self.cache_root = Path(cache_root)

    def __call__(self, transfer):
        revision = self.store.get_revision(str(transfer.object_id))
        if not revision or not revision.get('source_code'):
            raise FileNotFoundError('strategy revision bytes are unavailable')
        raw = revision_bytes(revision)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != transfer.expected_sha256 or len(raw) != transfer.expected_size:
            raise ValueError('strategy revision object identity mismatch')
        target = self.cache_root / 'strategy-revisions' / f'{digest}.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name(f'.{digest}.{uuid4().hex}.tmp')
            temporary.write_bytes(raw)
            temporary.chmod(0o600)
            os.replace(temporary, target)
        return target
