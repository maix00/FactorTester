"""Plan complete subtree copies; publish through the existing branch transaction."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import quote, unquote

from .tree_operations import apply_operation
from .tree_schema import identifier
from .tree_hierarchy import validate_parent_child, validate_root_child
from .tree_transactions import mutate_batch


def plan_subtree_copy(source: dict, target: dict, *, component_ids: list[str],
                      parent_id: str = 'root', copy_id: str,
                      after_component_id: str | None = None) -> dict:
    """Freeze source content and target revision without writing either branch.

    Asset bytes must be staged by the authorized transport before application;
    this plan returns the exact descriptors it needs, never dropping them.
    """
    identifier(copy_id, 'copy_id')
    identifier(parent_id, 'parent_id')
    if source['head']['report_id'] != target['head']['report_id']:
        raise ValueError('subtree copy requires branches of the same report')
    nodes = {n['component_id']: n for n in source['components']}
    if len(nodes) != len(source['components']):
        raise ValueError('source contains duplicate components')
    target_nodes = {n['component_id']: n for n in target['components']}
    if parent_id != 'root' and parent_id not in target_nodes:
        raise ValueError('target parent component does not exist')
    if after_component_id is not None:
        sibling = target_nodes.get(after_component_id)
        if sibling is None or (sibling.get('parent_id') or 'root') != parent_id:
            raise ValueError('insertion anchor must belong to the target parent')
    roots = set(component_ids)
    if not roots or len(roots) != len(component_ids) or not roots.issubset(nodes):
        raise ValueError('select distinct existing source components')
    children = {}
    for node in nodes.values():
        children.setdefault(node.get('parent_id') or 'root', []).append(node['component_id'])
    selected = []
    visiting = set()
    def visit(node_id):
        if node_id in visiting or node_id in selected:
            raise ValueError('overlapping or cyclic source subtrees')
        visiting.add(node_id)
        selected.append(node_id)
        for child in children.get(node_id, []):
            visit(child)
        visiting.remove(node_id)
    for node_id in component_ids:
        visit(node_id)
    for node_id in component_ids:
        validate_root_child(kind=nodes[node_id]['kind'], parent_id=parent_id)
        validate_parent_child(parent_kind='root' if parent_id == 'root' else target_nodes[parent_id]['kind'],
                              child_kind=nodes[node_id]['kind'])
    mapping = {old: 'copy-' + sha256(f'{copy_id}:{old}'.encode()).hexdigest()[:32]
               for old in selected}
    if set(mapping.values()) & set(target_nodes):
        raise ValueError('copy_id already exists in the target branch')
    asset_refs = set()
    def rewrite(value):
        if isinstance(value, dict):
            if value.get('asset_ref'):
                asset_refs.add(value['asset_ref'])
            result = {k: rewrite(v) for k, v in value.items()}
            if value.get('kind') == 'report_section' and value.get('target_ref', '').startswith('node:'):
                old = value['target_ref'][5:]
                if old in mapping:
                    result['target_ref'] = 'node:' + mapping[old]
            return result
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        if isinstance(value, str):
            def link(match):
                old = unquote(match.group(1))
                if old.startswith('node:') and old[5:] in mapping:
                    return 'factortester://report_section/' + quote('node:' + mapping[old[5:]], safe='')
                return match.group(0)
            return re.sub(r'factortester://report_section/([^\s)]+)', link, value)
        return deepcopy(value)
    bindings = {}
    for binding in source.get('bindings', []):
        bindings.setdefault(binding['component_id'], []).append(binding)
    operations = []
    previous = after_component_id
    for old in selected:
        node = nodes[old]
        copied_bindings = []
        for binding in bindings.get(old, []):
            item = rewrite({k: v for k, v in binding.items() if k != 'component_id'})
            item['binding_id'] = 'copy-' + sha256(f"{copy_id}:{binding['binding_id']}".encode()).hexdigest()[:32]
            copied_bindings.append(item)
        if old in roots:
            copied_bindings.append({
                'binding_id': 'copy-origin-' + sha256(f'{copy_id}:{old}'.encode()).hexdigest()[:32],
                'kind': 'graph_reference', 'target_ref': f'report-copy:{copy_id}',
                'label': 'Copied report subtree',
                'data': {'source_report_id': source['head']['report_id'],
                         'source_generation': source['head']['generation'],
                         'source_root_ref': source['head']['root_ref'],
                         'source_component_id': old, 'copy_id': copy_id},
            })
        operation = {'op': 'add', 'component_id': mapping[old],
                     'kind': node['kind'], 'parent_id': parent_id if old in roots else mapping[node['parent_id']],
                     **{k: rewrite(node.get(k)) for k in ('title', 'body', 'content', 'display_kind')},
                     'bindings': copied_bindings}
        if old in roots:
            if previous is not None:
                operation['after_component_id'] = previous
            previous = mapping[old]
        operations.append(operation)
    assets = {a['asset_ref']: a for a in source['head'].get('assets', [])}
    if not asset_refs.issubset(assets):
        raise ValueError('source subtree references an unregistered asset')
    return {'source': {k: source['head'][k] for k in ('report_id', 'generation', 'root_ref')},
            'target': {k: target['head'][k] for k in ('report_id', 'generation', 'root_ref')},
            'copy_id': copy_id, 'component_map': mapping,
            'target_assets': deepcopy(target['head'].get('assets', [])),
            'assets': [deepcopy(assets[ref]) for ref in sorted(asset_refs)],
            'operations': operations}


def apply_subtree_copy(paths: dict[str, Path], plan: dict, *, staged_assets: list[dict],
                       submission=None) -> dict:
    """The caller stages verified asset bytes, then obtains one atomic HEAD."""
    required = {a['asset_ref']: a for a in plan['assets']}
    staged = {a['asset_ref']: a for a in staged_assets}
    if len(staged) != len(staged_assets) or set(staged) != set(required):
        raise ValueError('all copied assets must be staged exactly once')
    for ref, asset in staged.items():
        expected = required[ref].get('content_hash')
        if expected and asset.get('content_hash') != expected:
            raise ValueError('staged copy asset hash mismatch')
    existing = {a['asset_ref']: a for a in plan['target_assets']}
    additions = []
    for ref, asset in staged.items():
        if ref in existing:
            if not asset.get('content_hash') or existing[ref].get('content_hash') != asset['content_hash']:
                raise ValueError('target has a conflicting asset reference')
        else:
            additions.append({'op': 'asset', 'asset': asset})
    operations = additions + plan['operations']
    return mutate_batch(paths, operations, apply_operation, submission=submission,
                        expected_head=plan['target'])
