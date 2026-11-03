"""Read-only compatibility conversion of a frozen, owned report tree.

Retired references become inert citations with their original metadata kept
in the private editable source. Source files and Graph services are never
written or executed. The caller retains the original tree as a business
version before publishing the successor.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import base64
import json
import re
import subprocess
from urllib.parse import unquote

from tools.cli.release.bounded_file import read_bounded_file
from ..report_link_kinds import REPORT_LINK_KINDS
from .historical_references import RETIRED_REFERENCE_KINDS, historical_reference, historical_anchor
from .authoring.inline_links import validate_typed_target
from .authoring.tree_projection import project_snapshot
from .authoring.tree_schema import digest, node_reference, validate_node
from .authoring.tree_store import validate_head

_URL = re.compile(r'(?:factortester|traderesearch)://([A-Za-z0-9_-]+)/([^\s()\[\]<>]+)')
_MAX_BYTES = 64 * 1024 * 1024


def _retired(kind, target):
    if kind in RETIRED_REFERENCE_KINDS:
        return True
    if kind not in REPORT_LINK_KINDS:
        raise ValueError('historical report contains an unclassified reference kind')
    try:
        validate_typed_target(kind=kind, target_ref=target, field='historical report')
    except ValueError:
        return True
    return False


def _convert_node(raw):
    value = deepcopy(raw)
    citations, converted = {}, 0
    for binding in value['bindings']:
        kind, target = binding['kind'], binding['target_ref']
        if not _retired(kind, target):
            continue
        ref = historical_reference(kind, target)
        original = {'kind': kind, 'target_ref': target, 'data': deepcopy(binding.get('data', {})), 'urls': []}
        binding.update(kind='historical_reference', target_ref=ref,
                       data={'historical_reference': original})
        citations[(kind, target)] = binding
        converted += 1

    def rewrite(item):
        nonlocal converted
        if isinstance(item, dict):
            return {key: rewrite(child) for key, child in item.items()}
        if isinstance(item, list):
            return [rewrite(child) for child in item]
        if not isinstance(item, str):
            return item
        def replace(match):
            nonlocal converted
            kind, target = match.group(1).replace('-', '_'), unquote(match.group(2))
            if not _retired(kind, target):
                return match.group(0)
            binding = citations.get((kind, target))
            if binding is None:
                key = hashlib.sha256((value['node_id'] + '\0' + kind + '\0' + target).encode()).hexdigest()[:24]
                binding = {'binding_id': 'historical-' + key, 'kind': 'historical_reference',
                           'target_ref': historical_reference(kind, target), 'label': kind,
                           'data': {'historical_reference': {'kind': kind, 'target_ref': target, 'data': {}, 'urls': []}}}
                citations[(kind, target)] = binding
                value['bindings'].append(binding)
                converted += 1
            urls = binding['data']['historical_reference']['urls']
            if match.group(0) not in urls:
                urls.append(match.group(0)); urls.sort()
            return historical_anchor(binding['target_ref'])
        return _URL.sub(replace, item)
    value['body'], value['content'] = rewrite(value['body']), rewrite(value['content'])
    return value, converted


def recover_node_from_git(package_root, path):
    """Read an exact Git blob without filters, hooks, network or source execution."""
    package_root = package_root.resolve()
    relative = path.resolve().relative_to(package_root).as_posix()
    command = ['git', '--no-replace-objects', '-c', 'core.hooksPath=/dev/null',
               '-c', 'core.fsmonitor=false', '-C', str(package_root)]
    identity = subprocess.run([*command, 'rev-parse', '--verify', 'HEAD:' + relative],
                              capture_output=True, check=True, timeout=10).stdout.decode().strip()
    if re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', identity) is None:
        raise ValueError('historical Git blob identity is invalid')
    size = int(subprocess.run([*command, 'cat-file', '-s', identity],
                             capture_output=True, check=True, timeout=10).stdout)
    if not 0 < size <= 8 * 1024 * 1024:
        raise ValueError('historical Git node exceeds its byte budget')
    result = subprocess.run([*command, 'cat-file', 'blob', identity],
                            capture_output=True, check=True, timeout=10)
    if len(result.stdout) != size:
        raise ValueError('historical Git blob size changed')
    algorithm = hashlib.sha1 if len(identity) == 40 else hashlib.sha256
    actual = algorithm(b'blob ' + str(size).encode() + b'\0' + result.stdout).hexdigest()
    if actual != identity:
        raise ValueError('historical Git blob checksum differs')
    return result.stdout, {'kind': 'git_blob', 'object_id': identity}


def upgrade_historical_report(paths, *, head, recover_node=None, pending_submission=None):
    """Return an in-memory successor plus exact source/root mappings."""
    original_head = validate_head(deepcopy(head))
    source, output, mappings, seen_ids = {}, {}, {}, set()
    used, converted = 0, 0
    root = paths['root'].resolve()
    visiting = set()
    variants = []
    if pending_submission is not None:
        pending = pending_submission
        if (pending.get('phase') != 'rejected' or pending.get('base_generation') != original_head['generation']
                or pending.get('submission_sequence') != original_head['generation'] + 1
                or pending.get('sidecars') or pending.get('published_generation') is not None):
            raise ValueError('historical submission requires independent reconciliation')

    def visit(ref):
        nonlocal used, converted
        node_reference(ref)
        if ref in visiting or ref in source:
            raise ValueError('historical report contains repeated or cyclic nodes')
        path = root / ref
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('historical report node escapes its source')
        raw_bytes = read_bounded_file(path, 8 * 1024 * 1024)
        used += len(raw_bytes)
        if used > _MAX_BYTES:
            raise ValueError('historical report source exceeds its byte budget')
        raw = json.loads(raw_bytes)
        sha = digest(raw)
        if ref != f'nodes/{sha[:2]}/{sha}.json':
            if recover_node is None:
                raise ValueError('historical report node checksum differs')
            recovered, evidence = recover_node(path)
            used += len(recovered)
            if used > _MAX_BYTES:
                raise ValueError('historical report source exceeds its byte budget')
            restored = json.loads(recovered); sha = digest(restored)
            if ref != f'nodes/{sha[:2]}/{sha}.json':
                raise ValueError('recovered historical node checksum differs')
            variants.append({'node_ref': ref, 'observed_sha256': hashlib.sha256(raw_bytes).hexdigest(),
                             'observed_content_base64': base64.b64encode(raw_bytes).decode('ascii'),
                             'recovery': evidence})
            raw = restored
        if raw['node_id'] in seen_ids:
            raise ValueError('historical report node identity is repeated')
        seen_ids.add(raw['node_id']); visiting.add(ref); source[ref] = raw
        value, count = _convert_node(raw)
        converted += count
        for child in value['children']:
            target = visit(child['ref'])
            if output[target]['node_id'] != child['node_id']:
                raise ValueError('historical report child identity differs')
            child['ref'] = target
        visiting.remove(ref)
        value = validate_node(value)
        sha = digest(value); target = f'nodes/{sha[:2]}/{sha}.json'
        output[target] = value; mappings[ref] = target
        return target

    next_root = visit(original_head['root_ref'])
    changed = next_root != original_head['root_ref'] or pending_submission is not None
    successor = deepcopy(original_head)
    if changed:
        generation = (pending_submission['submission_sequence'] + 1 if pending_submission
                      else original_head['generation'] + 1)
        successor.update(root_ref=next_root, generation=generation,
                         changed_node_ids=sorted(source[ref]['node_id'] for ref, target in mappings.items() if ref != target))
    successor = validate_head(successor)
    snapshot = project_snapshot(paths, successor, node_values=output)
    receipt = {'source_head': original_head, 'source_nodes': source, 'node_ref_mapping': mappings,
               'source_bytes': used, 'converted_references': converted, 'changed': changed,
               'source_generation': original_head['generation'], 'generation': successor['generation'],
               'source_root_ref': original_head['root_ref'], 'root_ref': successor['root_ref'],
               'source_variants': variants, 'rejected_submission': deepcopy(pending_submission)}
    snapshot['migration_source'] = receipt
    return snapshot, receipt
