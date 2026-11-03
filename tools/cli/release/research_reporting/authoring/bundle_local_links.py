"""Explicit missing-resource records retained across report cache materialization."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from tools.cli.release.bounded_file import read_bounded_file


def unavailable_relative(item):
    digest = hashlib.sha256(item['target'].encode()).hexdigest()
    return Path('resources') / ('unavailable-' + digest) / item['filename']


def inherited_unavailable(snapshot):
    root = snapshot.get('paths', {}).get('root')
    if root is None:
        return set()
    receipt = Path(root) / 'collaboration-fork.json'
    if not receipt.is_file():
        return set()
    value = json.loads(read_bounded_file(receipt, 2 * 1024 * 1024))
    return {quote(unavailable_relative(item).as_posix(), safe='/')
            for item in value.get('unavailable_links', [])}


def validate_unavailable_links(manifest):
    from ..public_research.projection import _local_targets
    records = manifest.get('unavailable_links', [])
    if not isinstance(records, list) or len(records) > 256:
        raise ValueError('unavailable report resource inventory is invalid')
    declared = set(_local_targets({'head': manifest['head'],
        'components': [{k: v for k, v in node.items() if k in {'body', 'content'}}
                       for node in manifest['nodes'].values()],
        'bindings': [binding for node in manifest['nodes'].values() for binding in node['bindings']]}))
    seen = {item['target'] for item in manifest['links']}
    for item in records:
        if (not isinstance(item, dict) or set(item) != {'target', 'filename', 'reason'}
                or not isinstance(item['target'], str) or len(item['target']) > 4096
                or item['target'] not in declared or item['target'] in seen
                or item['reason'] != 'source_unavailable'
                or not isinstance(item['filename'], str) or not item['filename']
                or item['filename'] in {'.', '..'} or '/' in item['filename'] or '\\' in item['filename']):
            raise ValueError('unavailable report resource identity is invalid')
        seen.add(item['target'])


def bundle_link_relative(item, *, schema_version):
    """Keep distinct source links distinct even when bytes and filenames match."""
    root = Path("resources") / item["sha256"]
    if schema_version >= 5:
        root /= hashlib.sha256(item["target"].encode("utf-8")).hexdigest()[:24]
    return root / item["filename"]
