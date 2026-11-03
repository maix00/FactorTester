"""Portable frozen source quotes; restored caches never require a Git worktree."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re

from tools.cli.release.bounded_file import read_bounded_file
from .tree_schema import canonical_bytes
from .tree_store import atomic_write

_META = 'selected-source-attachments.json'
_MAX_FILE = 8 * 1024 * 1024
_MAX_TOTAL = 20 * 1024 * 1024
_FIELDS = {'attachment_ref', 'attachment_kind', 'filename', 'relative_path', 'media_type',
           'content_hash', 'git_blob', 'revision', 'sha256', 'size_bytes'}


def git_blob_digest(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def capture_source_attachments(snapshot, capture):
    from ..public_research.attachments import build_related_objects
    _objects, attachments = build_related_objects(snapshot, snapshot['bindings'])
    result = []
    for item in attachments:
        raw = base64.b64decode(item['content_base64'], validate=True)
        result.append({**{k: v for k, v in item.items() if k != 'content_base64'},
                       **capture(raw, item['filename'])})
    return result


def validate_source_attachments(manifest, files):
    records = manifest.get('source_attachments', [])
    if not isinstance(records, list) or len(records) > 256:
        raise ValueError('frozen source attachment inventory is invalid')
    eligible = set()
    for node in manifest['nodes'].values():
        for binding in node['bindings']:
            data = binding.get('data', {})
            if binding['kind'] == 'factor':
                kind = 'factor_set_manifest' if binding['target_ref'].startswith('factor-set:') else 'factor_source'
                if isinstance(data.get('blob_hash'), str):
                    eligible.add((kind, data['blob_hash']))
    seen, total = set(), 0
    for item in records:
        if not isinstance(item, dict) or set(item) != _FIELDS:
            raise ValueError('frozen source attachment fields are invalid')
        sha = item['sha256']
        key = (item['attachment_kind'], item['git_blob'])
        if (not isinstance(sha, str) or re.fullmatch('[0-9a-f]{64}', sha) is None
                or sha in seen or item['content_hash'] != sha
                or item['attachment_ref'] != 'attachment:sha256:' + sha or key not in eligible
                or type(item['size_bytes']) is not int or not 0 < item['size_bytes'] <= _MAX_FILE
                or not isinstance(item['filename'], str) or Path(item['filename']).name != item['filename']
                or not isinstance(item['relative_path'], str) or len(item['relative_path']) > 2048
                or Path(item['relative_path']).is_absolute() or '..' in Path(item['relative_path']).parts
                or not isinstance(item['revision'], str) or len(item['revision']) > 128
                or not isinstance(item['media_type'], str) or len(item['media_type']) > 128):
            raise ValueError('frozen source attachment identity differs')
        raw = files[sha]
        if len(raw) != item['size_bytes'] or hashlib.sha256(raw).hexdigest() != sha or git_blob_digest(raw) != item['git_blob']:
            raise ValueError('frozen source attachment bytes differ')
        total += len(raw); seen.add(sha)
        if total > _MAX_TOTAL:
            raise ValueError('frozen source attachments exceed their byte budget')


def restore_source_attachments(paths, manifest, files):
    records = manifest.get('source_attachments', [])
    if not records:
        return None
    for item in records:
        atomic_write(paths['root'] / 'selected-sources' / item['sha256'], files[item['sha256']])
    encoded = canonical_bytes({'schema_version': 1, 'report_id': manifest['head']['report_id'], 'attachments': records})
    atomic_write(paths['root'] / _META, encoded)
    return hashlib.sha256(encoded).hexdigest()


def cached_source_attachment(snapshot, *, kind, data):
    paths = snapshot.get('paths', {})
    root = paths.get('root')
    if root is None:
        return None
    root = Path(root)
    if '_selected_source_records' not in snapshot:
        metadata, receipt = root / _META, root / 'collaboration-fork.json'
        origin = json.loads(read_bounded_file(receipt, 2 * 1024 * 1024)) if receipt.is_file() else {}
        expected = origin.get('source_attachment_manifest_sha256')
        if metadata.is_symlink() or (expected and not metadata.is_file()):
            raise ValueError('frozen source cache is unavailable')
        if metadata.is_file():
            encoded = read_bounded_file(metadata, 2 * 1024 * 1024)
            value = json.loads(encoded)
            if (not expected or hashlib.sha256(encoded).hexdigest() != expected
                    or value.get('schema_version') != 1 or value.get('report_id') != snapshot['head']['report_id']
                    or not isinstance(value.get('attachments'), list) or len(value['attachments']) > 256):
                raise ValueError('frozen source cache metadata differs')
            records = value['attachments']
        else:
            records = []
        snapshot['_selected_source_records'] = records
    matches = [item for item in snapshot['_selected_source_records']
               if item['git_blob'] == data.get('blob_hash')]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('frozen source cache identity is ambiguous')
    item = matches[0]
    sha = item['sha256']
    if re.fullmatch('[0-9a-f]{64}', sha) is None:
        raise ValueError('frozen source cache reference is invalid')
    path = root / 'selected-sources' / sha
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('frozen source cache escapes its report')
    raw = read_bounded_file(path, _MAX_FILE)
    if (len(raw) != item['size_bytes'] or hashlib.sha256(raw).hexdigest() != sha
            or git_blob_digest(raw) != item['git_blob']):
        raise ValueError('frozen source cache bytes differ')
    return {**{k: v for k, v in item.items() if k not in {'sha256', 'size_bytes'}},
            'content_base64': base64.b64encode(raw).decode('ascii')}
