"""Rebuildable local content baselines bound to a publication receipt.

The Manager and SQLite receipt remain the authorities.  This cache records the
local authoring bytes represented by that receipt, including resources which
are not part of the immutable report-tree hash.  An absent or stale cache must
never be treated as evidence that such resources have not changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

from .authoring.tree_bundle import bundle_from_snapshot
from .authoring.tree_projection import project_snapshot
from .public_research.projection import _local_targets

_SHA = re.compile(r'^[0-9a-f]{64}$')
_FIELDS = {'publication_id', 'revision', 'generation', 'local_root_ref', 'content_sha256'}
_RECHECK_SECONDS = 60


def _path(store, report_id: str, manager_hash: str) -> Path:
    if not isinstance(report_id, str) or not report_id or not _SHA.fullmatch(manager_hash):
        raise ValueError('invalid report baseline identity')
    parent = store.workspace_root / '.report-baselines'
    if parent.is_symlink():
        raise ValueError('report baseline directory is a symbolic link')
    return parent / (hashlib.sha256(report_id.encode()).hexdigest() + '-' + manager_hash + '.json')


def content_digest(root: Path, paths: dict, head: dict) -> str:
    """Caller holds the tree lock; output includes all editable resources."""
    data = bundle_from_snapshot(project_snapshot(paths, head), package_root=root, branch_id='main')
    return hashlib.sha256(data).hexdigest()


def needs_baseline(paths: dict, head: dict) -> bool:
    """Older trees with independently mutable resources cannot prove a base."""
    if any(not asset.get('content_hash') for asset in head['assets']):
        return True
    return bool(_local_targets(project_snapshot(paths, head)))


def read_baseline(store, *, report_id: str, manager_hash: str, receipt) -> str | None:
    path = _path(store, report_id, manager_hash)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
                return None
            value = json.load(source)
    except (OSError, ValueError, UnicodeError):
        return None
    if (not isinstance(value, dict) or set(value) != _FIELDS
            or type(value['generation']) is not int or value['generation'] < 0
            or any(not isinstance(value[key], str) or not value[key] for key in
                   ('publication_id', 'revision', 'local_root_ref'))
            or not isinstance(value['content_sha256'], str) or not _SHA.fullmatch(value['content_sha256'])
            or any(value[key] != receipt[key] for key in ('publication_id', 'revision', 'generation', 'local_root_ref'))):
        return None
    return value['content_sha256']


def content_check_due(store, *, report_id: str, manager_hash: str) -> bool:
    """Bound polling cost while eventually checking external authoring bytes."""
    path = _path(store, report_id, manager_hash)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        return True
    age = time.time() - metadata.st_mtime
    return age < 0 or age >= _RECHECK_SECONDS


def mark_content_checked(store, *, report_id: str, manager_hash: str, receipt, content_sha256: str) -> None:
    """Advance only the baseline that was actually checked, even across replacement."""
    path = _path(store, report_id, manager_hash)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
            return
        value = json.load(source)
        if (not isinstance(value, dict) or set(value) != _FIELDS
                or value.get('content_sha256') != content_sha256
                or any(value.get(key) != receipt[key] for key in
                       ('publication_id', 'revision', 'generation', 'local_root_ref'))):
            return
        os.utime(source.fileno(), None)


def write_baseline(store, *, report_id: str, manager_hash: str, receipt, content_sha256: str) -> None:
    if not _SHA.fullmatch(content_sha256):
        raise ValueError('invalid report baseline digest')
    path = _path(store, report_id, manager_hash)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('report baseline path is a symbolic link')
    value = {key: receipt[key] for key in ('publication_id', 'revision', 'generation', 'local_root_ref')}
    value['content_sha256'] = content_sha256
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    descriptor, temporary = tempfile.mkstemp(prefix='.baseline-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def remove_baseline(store, *, report_id: str, manager_hash: str) -> None:
    path = _path(store, report_id, manager_hash)
    if path.is_symlink():
        raise ValueError('report baseline path is a symbolic link')
    path.unlink(missing_ok=True)
