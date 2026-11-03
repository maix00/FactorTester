"""Carry bounded, inert migration evidence inside the private authoring bundle."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re

from tools.cli.release.bounded_file import read_bounded_file
from .tree_schema import canonical_bytes, digest, validate_node
from .tree_store import validate_head

MAX_SOURCE_BYTES = 32 * 1024 * 1024
_FILENAME = 'migration-source.json'


def validate_migration_source(value, *, report_id):
    # Imported lazily: the converter itself uses the ordinary tree projection.
    from ..migration_report_tree import _convert_node
    fields = {'source_head', 'source_nodes', 'node_ref_mapping', 'source_bytes',
              'converted_references', 'changed', 'source_generation', 'generation',
              'source_root_ref', 'root_ref', 'source_variants', 'rejected_submission'}
    if not isinstance(value, dict) or set(value) not in (fields, fields | {'storage_cutover'}):
        raise ValueError('report migration source schema is invalid')
    head = validate_head(value['source_head'])
    if (head['report_id'] != report_id or value['source_generation'] != head['generation']
            or value['source_root_ref'] != head['root_ref']
            or type(value['source_bytes']) is not int or not 0 < value['source_bytes'] <= 64 * 1024 * 1024):
        raise ValueError('report migration source identity is invalid')
    nodes, mapping = value['source_nodes'], value['node_ref_mapping']
    if not isinstance(nodes, dict) or not isinstance(mapping, dict) or set(mapping) != set(nodes):
        raise ValueError('report migration source inventory is invalid')
    seen, ids, count = set(), set(), 0
    def visit(ref):
        nonlocal count
        if ref in seen or ref not in nodes:
            raise ValueError('report migration source node is missing or repeated')
        raw = nodes[ref]
        if not isinstance(raw, dict):
            raise ValueError('report migration source node is invalid')
        sha = digest(raw)
        if ref != f'nodes/{sha[:2]}/{sha}.json':
            raise ValueError('report migration source node checksum differs')
        converted, n = _convert_node(raw)
        converted = validate_node(converted)
        if converted['node_id'] in ids:
            raise ValueError('report migration source node identity is repeated')
        seen.add(ref); ids.add(converted['node_id']); count += n
        for child in converted['children']:
            if child['node_id'] != nodes.get(child['ref'], {}).get('node_id'):
                raise ValueError('report migration source child identity differs')
            child['ref'] = visit(child['ref'])
        sha = digest(validate_node(converted)); target = f'nodes/{sha[:2]}/{sha}.json'
        if mapping[ref] != target:
            raise ValueError('report migration source conversion differs')
        return target
    root = visit(head['root_ref'])
    if set(nodes) != seen or value['root_ref'] != root or value['converted_references'] != count:
        raise ValueError('report migration source conversion inventory differs')
    pending = value['rejected_submission']
    if pending is not None and (not isinstance(pending, dict) or pending.get('phase') != 'rejected'
            or pending.get('base_generation') != head['generation']
            or pending.get('submission_sequence') != head['generation'] + 1
            or pending.get('sidecars') != [] or pending.get('published_generation') is not None):
        raise ValueError('report migration source submission requires reconciliation')
    storage_cutover = value.get('storage_cutover', False)
    if type(storage_cutover) is not bool:
        raise ValueError('report migration source storage cutover flag is invalid')
    changed = storage_cutover or root != head['root_ref'] or pending is not None
    generation = head['generation'] + (2 if pending else 1) if changed else head['generation']
    if value['changed'] is not changed or value['generation'] != generation:
        raise ValueError('report migration source successor differs')
    variants = value['source_variants']
    if not isinstance(variants, list) or len(variants) > len(nodes):
        raise ValueError('report migration source variants are invalid')
    refs = set()
    for item in variants:
        if (not isinstance(item, dict) or set(item) != {'node_ref', 'observed_sha256', 'observed_content_base64', 'recovery'}
                or item['node_ref'] not in nodes or item['node_ref'] in refs
                or not isinstance(item['observed_content_base64'], str)
                or len(item['observed_content_base64']) > (8 * 1024 * 1024 + 2) // 3 * 4):
            raise ValueError('report migration source variant is invalid')
        raw = base64.b64decode(item['observed_content_base64'], validate=True)
        if hashlib.sha256(raw).hexdigest() != item['observed_sha256']:
            raise ValueError('report migration source variant checksum differs')
        recovery = item['recovery']
        if (not isinstance(recovery, dict) or set(recovery) != {'kind', 'object_id'}
                or recovery['kind'] != 'git_blob' or not isinstance(recovery['object_id'], str)
                or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', recovery['object_id'])):
            raise ValueError('report migration source recovery identity is invalid')
        refs.add(item['node_ref'])
    return value


def capture_migration_source(snapshot, capture):
    value = snapshot.get('migration_source')
    if value is None:
        root = snapshot.get('paths', {}).get('root')
        if root is None:
            return None
        receipt = Path(root) / 'collaboration-fork.json'
        if not receipt.is_file():
            return None
        metadata = json.loads(read_bounded_file(receipt, 2 * 1024 * 1024))
        expected = metadata.get('migration_source_sha256')
        if not expected:
            return None
        raw = read_bounded_file(Path(root) / _FILENAME, MAX_SOURCE_BYTES)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('cached report migration source checksum differs')
        value = json.loads(raw)
    validate_migration_source(value, report_id=snapshot['head']['report_id'])
    raw = canonical_bytes(value)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('report migration source exceeds size limit')
    return capture(raw, _FILENAME)


def validate_bundle_migration_source(manifest, files):
    descriptor = manifest.get('migration_source')
    if descriptor is None:
        if manifest.get('schema_version') == 4:
            raise ValueError('report migration source is missing')
        return
    if (not isinstance(descriptor, dict) or set(descriptor) != {'sha256', 'size_bytes', 'filename'}
            or descriptor['filename'] != _FILENAME or descriptor['size_bytes'] > MAX_SOURCE_BYTES):
        raise ValueError('report migration source descriptor is invalid')
    validate_migration_source(json.loads(files[descriptor['sha256']]), report_id=manifest['head']['report_id'])
