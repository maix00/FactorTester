"""Portable, verified report trees for collaboration over the object plane.

Only the reachable immutable tree is exported. Runtime credentials, submission
leases, SQLite caches and unrelated workspace files never enter the bundle.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

from .tree_paths import report_tree_paths
from .tree_hierarchy import validate_parent_child
from .bundle_job_artifacts import export_job_artifacts, restore_job_artifacts, artifact_requests
from .tree_schema import canonical_bytes, digest, validate_node
from .tree_store import (atomic_write, load_head, load_node, store_node,
                         tree_lock, validate_head, write_head)
from .tree_projection import project_snapshot
from .submission_status import require_no_pending
from .tree_sqlite_index import ensure_sqlite_index
from ..work_package_identity import ensure_work_package_identity
from ..public_research.projection import (
    _LocalResources, _local_targets, _resolve_local_resource, read_local_asset,
)

MAX_BUNDLE_BYTES = 64 * 1024 * 1024


def export_report_bundle(*, package_root: Path, branch_id: str,
                         expected_generation: int, expected_root_ref: str) -> bytes:
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        head = load_head(paths)
        if (head['generation'], head['root_ref']) != (expected_generation, expected_root_ref):
            raise ValueError('report bundle source version changed')
        require_no_pending(paths, head)
        snapshot = project_snapshot(paths, head)
        return bundle_from_snapshot(snapshot, package_root=package_root, branch_id=branch_id)


def bundle_from_snapshot(snapshot: dict, *, package_root: Path, branch_id: str) -> bytes:
    """Serialize a snapshot while the caller holds its report-tree lock."""
    paths, head = snapshot['paths'], snapshot['head']
    nodes = {}
    def visit(ref):
        if ref in nodes:
            raise ValueError('report tree contains a repeated node')
        node = load_node(paths, ref)
        nodes[ref] = node
        for child in node['children']:
            visit(child['ref'])
    visit(head['root_ref'])
    files, assets, links = {}, [], []
    total = 0
    def capture(raw, filename):
        nonlocal total
        key = hashlib.sha256(raw).hexdigest()
        if key not in files:
            total += len(raw)
            if total > MAX_BUNDLE_BYTES:
                raise ValueError('report bundle resources exceed size limit')
            files[key] = raw
        return {'sha256': key, 'size_bytes': len(raw), 'filename': Path(filename).name}
    for asset in head['assets']:
        asset_id = hashlib.sha256(asset['asset_ref'].encode()).hexdigest()[:24]
        resolved = None
        root = Path(package_root).resolve()
        candidates = ([root / asset['local_ref']] if asset.get('local_ref') else []) + [
            root / 'branches' / branch_id / 'assets' / asset['filename'],
            root / 'assets' / asset['filename'],
        ]
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                resolved = (candidate.read_bytes(), asset['media_type'], candidate.name)
                break
        if resolved is None:
            resolved = read_local_asset(snapshot, asset_id)
        if resolved is None:
            raise ValueError(f"report bundle asset is unavailable: {asset['asset_ref']}")
        raw, _, filename = resolved
        descriptor = capture(raw, filename)
        if asset.get('content_hash') and asset['content_hash'] != descriptor['sha256']:
            raise ValueError('report bundle asset hash mismatch')
        assets.append({'asset_ref': asset['asset_ref'], **descriptor})
    resources = _LocalResources(snapshot)
    for target in _local_targets(snapshot):
        path = _resolve_local_resource(resources, target)
        if path is None or not path.is_file():
            raise ValueError('report bundle local resource is unavailable')
        links.append({'target': target, **capture(path.read_bytes(), path.name)})
    job_artifacts = export_job_artifacts(snapshot, capture)
    manifest = {'schema_version': 2, 'source_branch_id': branch_id,
                'head': head, 'nodes': nodes, 'assets': assets, 'links': links, 'job_artifacts': job_artifacts}
    encoded = canonical_bytes(manifest)
    if total + len(encoded) > MAX_BUNDLE_BYTES:
        raise ValueError('report bundle exceeds size limit')
    stream = io.BytesIO()
    # Fixed ZIP timestamps make retries byte-identical for the same source.
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, raw in [('manifest.json', encoded), *[(f'objects/{key}', files[key]) for key in sorted(files)]]:
            archive.writestr(zipfile.ZipInfo(name), raw)
    return stream.getvalue()

def _read_bundle(payload: bytes, expected_sha256: str):
    if len(payload) > MAX_BUNDLE_BYTES + 1024 * 1024 or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError('report bundle size or checksum mismatch')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or 'manifest.json' not in names:
                raise ValueError('report bundle contains duplicate or missing members')
            if any(name != 'manifest.json' and not re.fullmatch(r'objects/[a-f0-9]{64}', name) for name in names):
                raise ValueError('report bundle contains an invalid member')
            if sum(item.file_size for item in archive.infolist()) > MAX_BUNDLE_BYTES:
                raise ValueError('report bundle expanded size exceeds limit')
            manifest = json.loads(archive.read('manifest.json'))
            if set(manifest) != {'schema_version', 'source_branch_id', 'head', 'nodes', 'assets', 'links', 'job_artifacts'} or manifest['schema_version'] != 2:
                raise ValueError('report bundle schema is invalid')
            files = {name.removeprefix('objects/'): archive.read(name) for name in names if name != 'manifest.json'}
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError('report bundle is invalid') from exc
    for key, raw in files.items():
        if hashlib.sha256(raw).hexdigest() != key:
            raise ValueError('report bundle resource checksum mismatch')
    for item in [*manifest['assets'], *manifest['links'], *manifest['job_artifacts']]:
        if not isinstance(item.get('filename'), str) or item['filename'] in {'', '.', '..'} or Path(item['filename']).name != item['filename']:
            raise ValueError('report bundle filename is invalid')
        if item['sha256'] not in files or len(files[item['sha256']]) != item['size_bytes']:
            raise ValueError('report bundle resource is missing or truncated')
    if set(files) != {item['sha256'] for item in [*manifest['assets'], *manifest['links'], *manifest['job_artifacts']]}:
        raise ValueError('report bundle contains unreferenced resources')
    return manifest, files


def validate_report_bundle(*, payload: bytes, expected_sha256: str, report_id: str,
                           source_generation: int, source_root_ref: str):
    """Validate every reachable node and byte before granting an active branch."""
    manifest, files = _read_bundle(payload, expected_sha256)
    head = validate_head(manifest['head'])
    if (head['report_id'], head['generation'], head['root_ref']) != (report_id, source_generation, source_root_ref):
        raise ValueError('report bundle source identity or version mismatch')
    nodes = manifest['nodes']
    visited, ids = set(), set()
    def check(ref):
        if ref in visited or ref not in nodes:
            raise ValueError('report bundle node is missing or repeated')
        node = validate_node(nodes[ref])
        expected = f"nodes/{digest(node)[:2]}/{digest(node)}.json"
        if expected != ref or node['node_id'] in ids:
            raise ValueError('report bundle node identity mismatch')
        visited.add(ref); ids.add(node['node_id'])
        for child in node['children']:
            if child['node_id'] != nodes.get(child['ref'], {}).get('node_id'):
                raise ValueError('report bundle child identity mismatch')
            validate_parent_child(parent_kind=node['kind'], child_kind=nodes[child['ref']]['kind'])
            check(child['ref'])
    if nodes.get(head['root_ref'], {}).get('kind') != 'root' or nodes[head['root_ref']].get('node_id') != 'root':
        raise ValueError('report bundle root is invalid')
    check(head['root_ref'])
    if visited != set(nodes):
        raise ValueError('report bundle contains unreachable nodes')
    asset_map = {item['asset_ref']: item for item in manifest['assets']}
    if len(asset_map) != len(manifest['assets']) or set(asset_map) != {item['asset_ref'] for item in head['assets']}:
        raise ValueError('report bundle asset manifest mismatch')
    requests = artifact_requests({'components': list(nodes.values())})
    jobs = {(item['job_id'], item['name']): item for item in manifest['job_artifacts']}
    if len(jobs) != len(manifest['job_artifacts']) or set(jobs) != set(requests):
        raise ValueError('report bundle Job artifact inventory mismatch')
    for key, expected in requests.items():
        if expected and jobs[key]['sha256'] != expected:
            raise ValueError('report bundle Job artifact version mismatch')
    return manifest, files


def import_report_bundle(*, payload: bytes, expected_sha256: str, package_root: Path,
                         branch_id: str, report_id: str, source_generation: int,
                         source_root_ref: str) -> dict:
    manifest, files = validate_report_bundle(payload=payload, expected_sha256=expected_sha256,
                                            report_id=report_id, source_generation=source_generation,
                                            source_root_ref=source_root_ref)
    head, nodes = manifest['head'], manifest['nodes']
    asset_map = {item['asset_ref']: item for item in manifest['assets']}
    paths = report_tree_paths(package_root, branch_id)
    receipt = paths['root'] / 'collaboration-fork.json'
    with tree_lock(paths):
        if paths['head'].exists():
            if receipt.is_file() and json.loads(receipt.read_text()).get('bundle_sha256') == expected_sha256:
                return {'paths': paths, 'head': load_head(paths), 'inherited': False}
            raise ValueError('target branch already exists with another origin')
        ensure_work_package_identity(Path(package_root), work_package_id=Path(package_root).name, report_id=report_id)
        restore_job_artifacts(manifest['job_artifacts'], files)
        replacements = {}
        resource_root = Path(package_root).resolve() / 'branches' / branch_id / 'resources'
        for item in manifest['links']:
            destination = resource_root / item['sha256'] / Path(item['filename']).name
            atomic_write(destination, files[item['sha256']])
            replacements[item['target']] = quote(str(destination.relative_to(resource_root.parent)), safe='/')
        def rewrite(value):
            if isinstance(value, str):
                for before in sorted(replacements, key=len, reverse=True):
                    if value == before:
                        value = replacements[before]
                    else:
                        value = value.replace('](' + before + ')', '](' + replacements[before] + ')')
                        if before.startswith(('file://', 'factortester://file/')):
                            value = value.replace(before, replacements[before])
                return value
            if isinstance(value, list): return [rewrite(item) for item in value]
            if isinstance(value, dict): return {key: rewrite(item) for key, item in value.items()}
            return value
        def materialize(ref):
            node = rewrite(deepcopy(nodes[ref]))
            node['children'] = [{**child, 'ref': materialize(child['ref'])} for child in nodes[ref]['children']]
            return store_node(paths, node)[0]
        target_head = deepcopy(head)
        for asset in target_head['assets']:
            item = asset_map[asset['asset_ref']]
            filename = item['sha256'] + Path(item['filename']).suffix
            relative = Path('branches') / branch_id / 'assets' / filename
            atomic_write(Path(package_root) / relative, files[item['sha256']])
            asset.update(filename=filename, local_ref=str(relative), content_hash=item['sha256'])
            asset.pop('external_ref', None)
        target_head['root_ref'] = materialize(head['root_ref'])
        target_head['changed_node_ids'] = ['root']
        ensure_sqlite_index(paths, load_node(paths, target_head['root_ref']), target_head['generation'])
        atomic_write(receipt, canonical_bytes({'bundle_sha256': expected_sha256,
                     'source_branch_id': manifest['source_branch_id'], 'source_head': head}))
        write_head(paths, target_head)
        return {'paths': paths, 'head': target_head, 'inherited': True}
