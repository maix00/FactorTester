"""Compare complete editable snapshots without mistaking ancestor hashes for edits."""
from __future__ import annotations

from copy import deepcopy


def diff_report_manifests(base: dict, other: dict, *, include_content: bool = False) -> dict:
    if base['head']['report_id'] != other['head']['report_id']:
        raise ValueError('branch diff requires the same report identity')
    def entries(manifest):
        result = {}
        for node in manifest['nodes'].values():
            value = deepcopy(node)
            value['children'] = [item['node_id'] for item in node['children']]
            result[node['node_id']] = value
        return result
    before, after = entries(base), entries(other)
    changes = []
    for node_id in sorted(before.keys() | after.keys()):
        left, right = before.get(node_id), after.get(node_id)
        if left == right:
            continue
        status = 'added' if left is None else 'removed' if right is None else 'modified'
        fields = sorted(key for key in (left or {}).keys() | (right or {}).keys()
                        if (left or {}).get(key) != (right or {}).get(key))
        changes.append({'component_id': node_id, 'status': status, 'fields': fields,
                        'title': (right or left)['title'],
                        **({'before': left, 'after': right} if include_content else {})})
    def assets(manifest):
        return {item['asset_ref']: item['sha256'] for item in manifest['assets']}
    a, b = assets(base), assets(other)
    resources = [{'asset_ref': key, 'before': a.get(key), 'after': b.get(key)}
                 for key in sorted(a.keys() | b.keys()) if a.get(key) != b.get(key)]
    resource_changes = []
    for kind, key_field in (('links', 'target'), ('job_artifacts', 'artifact_ref')):
        def inventory(manifest):
            return {(item.get(key_field) or f"{item.get('job_id')}:{item.get('name')}"): item['sha256']
                    for item in manifest.get(kind, [])}
        left, right = inventory(base), inventory(other)
        resource_changes.extend({'kind': kind, 'resource_ref': key, 'before': left.get(key), 'after': right.get(key)}
                                for key in sorted(left.keys() | right.keys()) if left.get(key) != right.get(key))
    return {'report_id': base['head']['report_id'], 'base_generation': base['head']['generation'],
            'other_generation': other['head']['generation'], 'changes': changes, 'asset_changes': resources,
            'component_change_count': len(changes), 'asset_change_count': len(resources),
            'resource_changes': resource_changes, 'resource_change_count': len(resource_changes)}
