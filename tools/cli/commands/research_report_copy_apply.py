"""Apply a reviewed local copy through the normal submission and finalize gates."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring.tree_copy import plan_subtree_copy, apply_subtree_copy
from tools.cli.release.research_reporting.authoring.tree_fork import _copy_assets
from tools.cli.release.research_reporting.authoring.copy_resources import stage_resources
from .research_report_common import scope_options, read_json, output
from .research_report_scope import resolve_branch_report_scope, load_authoring, load_current_authoring
from .research_report_submission import begin_batch_submission, reject_mutation
from .research_report_submission_finalize import finalize_report_command


@click.command('copy-apply')
@scope_options
@click.option('--preview-file', required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--submission-sequence', type=click.IntRange(min=1), default=None)
@click.option('--json', 'as_json', is_flag=True)
@friendly_errors
def copy_apply(profile_id: str, report_workspace_id: str, branch_id: str,
               release_profile: Path | None, preview_file: Path,
               submission_sequence: int | None, as_json: bool) -> None:
    """按 copy-preview 输出复制；源/目标版本或预览内容变化时拒绝提交。"""
    preview = read_json(preview_file)
    if not isinstance(preview, dict) or preview.get('status') != 'preview':
        raise ValueError('expected a copy-preview JSON document')
    selection = preview.get('selection')
    if not isinstance(selection, dict):
        raise ValueError('copy preview is missing source selection')
    root = load_profile_root(release_profile)
    target = resolve_branch_report_scope(client_root=root, profile_id=profile_id,
                                        report_workspace_id=report_workspace_id, branch_id=branch_id)
    if _resume_published_copy(target, preview, submission_sequence, as_json):
        return
    source = resolve_branch_report_scope(client_root=root, profile_id=selection['source_profile'],
                                        report_workspace_id=selection['source_report_workspace_id'],
                                        branch_id=selection['source_branch_id'])
    if source.package_root.resolve() == target.package_root.resolve() and source.branch_id == target.branch_id:
        raise ValueError('source and target must be distinct branches')
    owner = (target.profile.get('session_binding') or {}).get('principal_ref')
    if not owner or (source.profile.get('session_binding') or {}).get('principal_ref') != owner:
        raise PermissionError('cross-user source must be read through Manager authorization')
    snapshot = load_authoring(target)
    source_snapshot = load_authoring(source)
    plan = plan_subtree_copy(source_snapshot, snapshot,
                            component_ids=selection['component_ids'], parent_id=selection['parent_id'],
                            after_component_id=selection.get('after_component_id'), copy_id=preview['copy_id'])
    if any(preview.get(key) != value for key, value in plan.items()):
        raise ValueError('source, target or copy preview changed; generate a new preview')
    stage_resources(source_snapshot, snapshot['paths'], plan['resources'])
    # Only the independently reconstructed source bindings may be preserved.
    # User-authored bindings never enter the normal preflight request.
    clean = [{k: deepcopy(v) for k, v in op.items() if k != 'bindings'} for op in plan['operations']]
    submission, enriched = begin_batch_submission(scope=target, requested_sequence=submission_sequence,
                                                  operations=clean, as_json=as_json)
    try:
        for original, validated in zip(plan['operations'], enriched, strict=True):
            bindings = deepcopy(original['bindings'])
            seen = {(b['kind'], b['target_ref']) for b in bindings}
            bindings.extend(b for b in validated.get('bindings', []) if (b['kind'], b['target_ref']) not in seen)
            validated['bindings'] = bindings
        plan['operations'] = enriched
        assets = deepcopy(plan['assets'])
        _copy_assets(source.package_root.resolve(), target.package_root.resolve(), assets,
                     source.branch_id, target.branch_id)
        head = apply_subtree_copy(snapshot['paths'], plan, staged_assets=assets, submission=submission)
    except Exception as error:
        reject_mutation(scope=target, submission=submission, error=error, as_json=as_json)
    saved = load_current_authoring(target)
    final = finalize_report_command(scope=target, submission=submission,
                                   descriptor=saved['descriptor'], message=f"Copy report subtrees {plan['copy_id']}",
                                   as_json=as_json)
    output({'status': 'applied', 'generation': head['generation'], 'copy_id': plan['copy_id'],
            'source': plan['source'], 'component_map': plan['component_map'],
            'submission_sequence': submission.sequence, 'git': final['git']}, as_json)


def _resume_published_copy(target, preview: dict, sequence: int | None, as_json: bool) -> bool:
    if sequence is None:
        return False
    snapshot = load_authoring(target)
    expected = preview.get('target') or {}
    if sequence != snapshot['head']['generation'] or sequence != expected.get('generation', -2) + 1:
        return False
    # The existing receipt/lease verifies the exact payload; no caller-supplied
    # plan is applied on this path and the source need not still be online.
    clean = [{k: deepcopy(v) for k, v in op.items() if k != 'bindings'}
             for op in preview['operations']]
    submission, _ = begin_batch_submission(scope=target, requested_sequence=sequence,
                                           operations=clean, as_json=as_json)
    if submission.phase not in {'published', 'finalized'}:
        raise ValueError('copy submission has not published its target generation')
    saved = load_current_authoring(target)
    final = finalize_report_command(scope=target, submission=submission,
                                   descriptor=saved['descriptor'],
                                   message=f"Copy report subtrees {preview['copy_id']}", as_json=as_json)
    output({'status': 'applied', 'generation': snapshot['head']['generation'],
            'copy_id': preview['copy_id'], 'source': preview['source'],
            'component_map': preview['component_map'], 'submission_sequence': sequence,
            'git': final['git'], 'resumed': True}, as_json)
    return True
