"""Compose registered Profile authoring with the shared branch/object APIs."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

from tools.cli.commands.research_report_scope_identity import resolve_branch_report_scope
from tools.cli.release.local_profile import LocalProfileStore
from .authoring.tree_bundle import MAX_BUNDLE_BYTES, import_report_bundle
from .authoring.tree_projection import load_snapshot
from .public_research.client import PublicResearchClient
from .workspace import initialize_work_package


def publish_local_branch(client, store: LocalProfileStore, *, profile_id: str,
                         work_package_id: str, branch_id: str) -> dict:
    scope = resolve_branch_report_scope(client_root=store.root.parent, profile_id=profile_id,
                                        work_package_id=work_package_id, branch_id=branch_id)
    head = load_snapshot(package_root=scope.package_root, branch_id=branch_id)['head']
    report_id = head['report_id']
    branches = client.report_branch_status(report_id)['branches']
    existing = next((item for item in branches if item['branch_id'] == branch_id), None)
    if existing is None:
        existing = client.reserve_report_branch(report_id, {'profile_ref': profile_id, 'branch_id': branch_id,
                                                           'title': head['title']})['branch']
    principal = (scope.profile.get('session_binding') or {}).get('principal_ref')
    if (existing['principal_ref'], existing['profile_ref']) != (principal, profile_id):
        raise PermissionError('shared branch belongs to another Profile')
    published = PublicResearchClient(store.root.parent, session=client.session).publish(
        profile_id=profile_id, work_package_id=work_package_id, branch_id=branch_id,
        visibility='private', include_authoring=True)
    if published['status'] != 'synced':
        return published
    result = client.publish_report_branch(report_id, branch_id, {
        'profile_ref': profile_id, 'publication_id': published['publication_id'],
        'expected_generation': existing['generation'], 'expected_revision': existing['revision'],
    })
    return {**published, 'branch': result['branch']}


def download_bundle(client, publication_id: str, descriptor: dict) -> bytes:
    """Use the existing 7997 ticket, never forward the Manager session bearer."""
    size = descriptor['size_bytes']
    if not isinstance(size, int) or not 0 < size <= MAX_BUNDLE_BYTES + 1024 * 1024:
        raise ValueError('report bundle declared size is invalid')
    issued = client._expect_success(client.session.post('/api/transfers/objects/download-access', {
        'publication_id': publication_id, 'object_kind': 'research_local_resource',
        'object_id': descriptor['resource_id'],
    }))
    access = issued['access']
    request = Request(access['url'], headers={'Authorization': 'Bearer ' + access['bearer']}, method='GET')
    with urlopen(request, timeout=120) as response:
        payload = response.read(size + 1)
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != descriptor['content_hash']:
        raise ValueError('downloaded report bundle checksum or size mismatch')
    return payload


def fork_remote_branch(client, store: LocalProfileStore, *, profile_id: str,
                       report_id: str, source_branch_id: str, branch_id: str) -> dict:
    profile = store.load(profile_id)
    principal = (profile.get('session_binding') or {}).get('principal_ref')
    if not principal or profile.get('status') != 'active':
        raise PermissionError('fork requires an authenticated active Profile')
    if branch_id == source_branch_id:
        raise ValueError('fork requires a distinct branch')
    branches = client.report_branch_status(report_id)['branches']
    existing = next((item for item in branches if item['branch_id'] == branch_id), None)
    package_id = 'report-' + hashlib.sha256(report_id.encode()).hexdigest()[:24]
    package_root = Path(profile['workspace_root']).expanduser() / 'research' / package_id
    receipt = package_root / 'branches' / branch_id / 'authoring/collaboration-fork.json'
    if existing and receipt.is_file():
        provenance = json.loads(receipt.read_text())
        if (existing['principal_ref'], existing['profile_ref'], existing['source_branch_id']) != (principal, profile_id, source_branch_id):
            raise PermissionError('existing fork belongs to another writer or source')
        if (provenance['source_branch_id'], provenance['source_head']['report_id'], provenance['source_head']['generation']) != (source_branch_id, report_id, existing['source_generation']):
            raise ValueError('local fork provenance differs from the reserved branch')
        # After local registration, retries only complete publication. They must
        # not follow a source branch that has advanced since the original fork.
        if any(item['record_id'] == package_id and any(
            artifact.get('artifact_ref') == f'artifact:research/{package_id}/branches/{branch_id}/authoring/HEAD.json'
            for artifact in item.get('artifacts', [])) for item in profile['research_records']):
            result = publish_local_branch(client, store, profile_id=profile_id,
                                          work_package_id=package_id, branch_id=branch_id)
            return {**result, 'work_package_id': package_id, 'inherited': False,
                    'source_branch_id': source_branch_id, 'source_revision': existing['source_revision']}
    source = next((item for item in branches if item['branch_id'] == source_branch_id and item['status'] == 'active'), None)
    if source is None:
        raise ValueError('source collaboration branch is unavailable')
    index = client.read_publication_branch(source['publication_id'])
    if 'index' in index:
        index = index['index']
    if (index.get('report_id'), index.get('generation'), index.get('projection_hash')) != (report_id, source['generation'], source['revision']):
        raise ValueError('source publication changed; refresh the branch before retrying')
    bundle = index.get('authoring_bundle')
    if not bundle:
        raise ValueError('source branch must upload an editable snapshot before it can be forked')
    client.create_research_workspace(source['research_id'], {
        'principal_ref': principal, 'profile_ref': profile_id, 'title': profile_id,
    })
    branch = client.reserve_report_branch(report_id, {
        'profile_ref': profile_id, 'branch_id': branch_id, 'title': index['title'],
        'source_branch_id': source_branch_id, 'source_generation': source['generation'], 'source_revision': source['revision'],
    })['branch']
    if (branch['principal_ref'], branch['profile_ref']) != (principal, profile_id):
        raise PermissionError('reserved branch belongs to another Profile')
    payload = download_bundle(client, source['publication_id'], bundle)
    package_id = 'report-' + hashlib.sha256(report_id.encode()).hexdigest()[:24]
    package_root = Path(profile['workspace_root']).expanduser() / 'research' / package_id
    inherited = import_report_bundle(payload=payload, expected_sha256=bundle['content_hash'], package_root=package_root,
        branch_id=branch_id, report_id=report_id, source_generation=source['generation'], source_root_ref=bundle['root_ref'])
    tree = initialize_work_package(workspace_root=Path(profile['workspace_root']), work_package_id=package_id,
        branch_id=branch_id, workspace_id=branch['workspace_id'], title=index['title'], branch_ref=f'report-branch:{branch_id}')
    # Reload after publication of the tree; retain every other local branch artifact.
    profile = store.load(profile_id)
    record = next((dict(item) for item in profile['research_records'] if item['record_id'] == package_id), None)
    if record is None:
        now = time.time()
        record = {'record_id': package_id, 'title': index['title'], 'status': 'pending',
            'scope': {'profile_id': profile_id, 'research_id': source['research_id']}, 'factor_family_versions': [],
            'agent_id': profile_id, 'created_at': now, 'updated_at': now,
            'workspace_ref': 'workspace:' + branch['workspace_id'], 'run_ref': '',
            'graph_instance_ref': 'work-package:' + package_id, 'graph_branch_ref': '', 'branch_bindings': [],
            'checkpoint_ref': '', 'evidence_refs': [], 'artifacts': [], 'timeline_refs': [],
            'provenance': {'created_by': 'factortester research reports branch-fork',
                           'research_id': source['research_id'], 'report_id': report_id}}
    record['artifacts'] = [item for item in record['artifacts'] if item['artifact_ref'] != tree['descriptor']['artifact_ref']] + [tree['descriptor']]
    store.upsert_research_record(profile_id, record)
    result = publish_local_branch(client, store, profile_id=profile_id, work_package_id=package_id, branch_id=branch_id)
    return {**result, 'work_package_id': package_id, 'inherited': inherited['inherited'],
            'source_branch_id': source_branch_id, 'source_revision': source['revision']}
