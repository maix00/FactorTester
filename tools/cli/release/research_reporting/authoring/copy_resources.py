"""Freeze and stage only local files referenced by selected report subtrees."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.parse import quote, unquote

from ..public_research.projection import _LocalResources, _local_targets, _resolve_local_resource
from .tree_store import atomic_write

MAX_RESOURCE_BYTES = 64 * 1024 * 1024


def plan_resources(source: dict, operations: list[dict]) -> list[dict]:
    selected = {**source, 'head': {}, 'components': operations, 'bindings': []}
    resolver = _LocalResources(source)
    result, total = [], 0
    for target in _local_targets(selected):
        path = _resolve_local_resource(resolver, target)
        if path is None or not path.is_file():
            raise ValueError('copied subtree local resource is unavailable')
        raw = path.read_bytes()
        total += len(raw)
        if total > MAX_RESOURCE_BYTES:
            raise ValueError('copied subtree resources exceed size limit')
        digest = sha256(raw).hexdigest()
        destination = quote(f'resources/{digest}/{path.name}', safe='/')
        result.append({'target': target, 'destination': destination,
                       'sha256': digest, 'size_bytes': len(raw)})
    return result


def rewrite_resources(value, resources: list[dict]):
    if isinstance(value, str):
        for item in sorted(resources, key=lambda item: len(item['target']), reverse=True):
            before, after = item['target'], item['destination']
            if value == before:
                value = after
            else:
                value = value.replace('](' + before + ')', '](' + after + ')')
                if before.startswith(('file://', 'factortester://file/')):
                    value = value.replace(before, after)
        return value
    if isinstance(value, list):
        return [rewrite_resources(item, resources) for item in value]
    if isinstance(value, dict):
        return {key: rewrite_resources(item, resources) for key, item in value.items()}
    return value


def destination_path(paths: dict, item: dict) -> Path:
    relative = Path(unquote(item['destination']))
    if relative.is_absolute() or '..' in relative.parts or relative.parts[:2] != ('resources', item['sha256']):
        raise ValueError('copy resource destination is invalid')
    branch = paths['root'].parent.resolve()
    destination = (branch / relative).resolve()
    if not destination.is_relative_to(branch):
        raise ValueError('copy resource destination escapes target branch')
    return destination


def stage_resources(source: dict, target_paths: dict, resources: list[dict]) -> None:
    resolver = _LocalResources(source)
    for item in resources:
        path = _resolve_local_resource(resolver, item['target'])
        if path is None or not path.is_file():
            raise ValueError('copied subtree local resource is unavailable')
        raw = path.read_bytes()
        if len(raw) != item['size_bytes'] or sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('copy resource changed since preview')
        atomic_write(destination_path(target_paths, item), raw)


def verify_resources(paths: dict, resources: list[dict]) -> None:
    for item in resources:
        path = destination_path(paths, item)
        if not path.is_file():
            raise ValueError('all copy resources must be staged before publication')
        raw = path.read_bytes()
        if len(raw) != item['size_bytes'] or sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('staged copy resource hash mismatch')
