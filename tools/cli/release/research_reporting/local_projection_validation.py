"""Compare a downloaded editable report with its source-free publication."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote

from .authoring.tree_projection import load_snapshot
from .public_research.object_uploads import detach_object_bytes, projection_hash
from .public_research.projection import (
    _job_artifact_path, asset_id_for, build_upload_projection, component_content_revision,
)


def bundle_matches_projection(*, package_root: Path, source_manifest: dict,
                              remote_projection: dict, expected_hash: str) -> bool:
    """Normalize names changed by safe local materialization before comparing.

    The original names and link targets come from the validated, checksummed
    authoring bundle, not from the independently supplied display projection.
    No report state or publication receipt is modified by this check.
    """
    source_head = source_manifest['head']
    source_assets = {asset_id_for(str(item['asset_ref'])): item for item in source_head['assets']}
    projection, _uploads = detach_object_bytes(build_upload_projection(
        load_snapshot(package_root=package_root, branch_id='main')))
    for item in projection['assets']:
        source_asset = source_assets.get(item['asset_id'])
        if source_asset is None:
            return False
        item['filename'] = str(source_asset.get('filename') or 'image').split('/')[-1]
        # Import embeds the bytes locally and removes this source-only URI.
        # Reconstruct the original projection using the validated source head.
        external_ref = str(source_asset.get('external_ref') or '').strip()
        if _job_artifact_path(external_ref, item['filename']) is not None:
            item['external_ref'] = external_ref

    source_nodes = {str(node['node_id']): node for node in source_manifest['nodes'].values()}
    for component in projection['components']:
        node = source_nodes.get(component['component_id'])
        if node is None:
            return False
        # Content revisions hash source paths; imported links are deliberately
        # rewritten to the local content-addressed resource directory.
        component['content_revision'] = component_content_revision(node)

    ids = {}
    for item in source_manifest['links']:
        original = str(item['target'])
        local = quote(str(Path('resources') / item['sha256'] / item['filename']), safe='/')
        local_id = hashlib.sha256(local.encode('utf-8')).hexdigest()[:24]
        original_id = hashlib.sha256(original.encode('utf-8')).hexdigest()[:24]
        if local_id in ids and ids[local_id] != original_id:
            return False
        ids[local_id] = original_id

    def restore(value):
        if isinstance(value, str):
            if value in ids:
                return ids[value]
            return re.sub(r'factortester-local://([0-9a-f]{24})',
                lambda match: 'factortester-local://' + ids.get(match.group(1), match.group(1)), value)
        if isinstance(value, list):
            return [restore(item) for item in value]
        if isinstance(value, dict):
            return {key: restore(item) for key, item in value.items()}
        return value

    projection = restore(projection)
    projection['updated_at'] = remote_projection['updated_at']
    return projection_hash(projection) == expected_hash
