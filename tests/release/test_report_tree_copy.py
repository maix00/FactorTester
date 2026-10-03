from copy import deepcopy
import pytest

from tools.cli.release.research_reporting.authoring.tree_model import initialize_tree, add_component, load_snapshot
from tools.cli.release.research_reporting.authoring.tree_copy import plan_subtree_copy, apply_subtree_copy


def component(package, branch, node_id, kind, parent=None, body='', content=None):
    add_component(package_root=package, branch_id=branch, component_id=node_id,
                  kind=kind, title=node_id, parent_id=parent, body=body,
                  content=content, display_kind='')


def pair(tmp_path):
    for branch in ('source', 'target'):
        initialize_tree(package_root=tmp_path, branch_id=branch, report_id='report-one', title='report')
    component(tmp_path, 'source', 'chapter', 'chapter')
    component(tmp_path, 'source', 'section', 'section', 'chapter')
    component(tmp_path, 'source', 'formula', 'math', 'section', content={'latex': 'x^2', 'fallback': ''})
    component(tmp_path, 'source', 'text', 'entry', 'section',
              body='[formula](factortester://report_section/node%3Aformula)')
    return [load_snapshot(package_root=tmp_path, branch_id=b) for b in ('source', 'target')]


def test_copy_complete_subtree_remaps_links_preserves_source_and_publishes_once(tmp_path):
    source, target = pair(tmp_path)
    before = deepcopy(source['head'])
    plan = plan_subtree_copy(source, target, component_ids=['chapter'], copy_id='one')
    assert len(plan['operations']) == 4
    head = apply_subtree_copy(target['paths'], plan, staged_assets=[])
    assert head['generation'] == target['head']['generation'] + 1
    saved = load_snapshot(package_root=tmp_path, branch_id='target')
    assert len(saved['components']) == 4
    assert saved['components'][2]['content']['latex'] == 'x^2'
    assert plan['component_map']['formula'] in saved['components'][3]['body']
    assert load_snapshot(package_root=tmp_path, branch_id='source')['head'] == before
    with pytest.raises(ValueError, match='target version changed'):
        apply_subtree_copy(target['paths'], plan, staged_assets=[])


def test_copy_refuses_stale_target_without_overwriting_intervening_edit(tmp_path):
    source, target = pair(tmp_path)
    plan = plan_subtree_copy(source, target, component_ids=['chapter'], copy_id='one')
    component(tmp_path, 'target', 'concurrent', 'chapter')
    current = load_snapshot(package_root=tmp_path, branch_id='target')
    with pytest.raises(ValueError, match='target version changed'):
        apply_subtree_copy(target['paths'], plan, staged_assets=[])
    assert load_snapshot(package_root=tmp_path, branch_id='target')['head'] == current['head']


def test_copy_rejects_overlapping_selection_and_missing_assets(tmp_path):
    source, target = pair(tmp_path)
    with pytest.raises(ValueError, match='overlapping'):
        plan_subtree_copy(source, target, component_ids=['chapter', 'section'], copy_id='one')
    source['components'][2].update(kind='image', content={'asset_ref': 'asset:missing'})
    with pytest.raises(ValueError, match='unregistered asset'):
        plan_subtree_copy(source, target, component_ids=['chapter'], copy_id='two')


def test_cli_copy_preview_resolves_profiles_and_never_writes(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from click.testing import CliRunner
    from tools.cli.commands import research_report_copy as command
    source, target = pair(tmp_path)
    def scope(**kwargs):
        return SimpleNamespace(package_root=tmp_path, branch_id=kwargs['branch_id'],
                               profile={'session_binding': {'principal_ref': 'alice'}})
    monkeypatch.setattr(command, 'load_profile_root', lambda _: tmp_path)
    monkeypatch.setattr(command, 'resolve_branch_report_scope', scope)
    monkeypatch.setattr(command, 'load_authoring', lambda s: source if s.branch_id == 'source' else target)
    result = CliRunner().invoke(command.copy_preview, [
        '--profile', 'self', '--report-workspace-id', 'package', '--branch-id', 'target',
        '--source-branch-id', 'source', '--component-id', 'chapter', '--copy-id', 'review', '--json',
    ])
    assert result.exit_code == 0, result.output
    preview = json.loads(result.output)
    assert preview['status'] == 'preview'
    assert len(preview['operations']) == 4
    assert load_snapshot(package_root=tmp_path, branch_id='target')['head'] == target['head']


def test_copy_provenance_survives_reload_and_preview_checks_target_structure(tmp_path):
    source, target = pair(tmp_path)
    with pytest.raises(ValueError, match='parent component'):
        plan_subtree_copy(source, target, component_ids=['section'], parent_id='missing', copy_id='bad')
    with pytest.raises(ValueError, match='anchor'):
        plan_subtree_copy(source, target, component_ids=['chapter'], after_component_id='missing', copy_id='bad')
    plan = plan_subtree_copy(source, target, component_ids=['chapter'], copy_id='audit')
    apply_subtree_copy(target['paths'], plan, staged_assets=[])
    saved = load_snapshot(package_root=tmp_path, branch_id='target')
    origin = next(b for b in saved['bindings'] if b['target_ref'] == 'report-copy:audit')
    assert origin['data']['source_root_ref'] == source['head']['root_ref']
    assert origin['data']['source_generation'] == source['head']['generation']
    assert origin['data']['source_component_id'] == 'chapter'


def test_cli_copy_apply_rebuilds_preview_and_uses_real_submission_gate(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from click.testing import CliRunner
    from tools.cli.commands import research_report_copy_apply as command
    for branch in ('source', 'target'):
        initialize_tree(package_root=tmp_path, branch_id=branch, report_id='report', title='report')
    component(tmp_path, 'source', 'chapter', 'chapter')
    component(tmp_path, 'source', 'section', 'section', 'chapter')
    source, target = [load_snapshot(package_root=tmp_path, branch_id=b) for b in ('source', 'target')]
    plan = plan_subtree_copy(source, target, component_ids=['chapter'], copy_id='cli-copy')
    preview = {'status': 'preview', **deepcopy(plan), 'selection': {
        'source_profile': 'self', 'source_report_workspace_id': 'package', 'source_branch_id': 'source',
        'component_ids': ['chapter'], 'parent_id': 'root', 'after_component_id': None}}
    path = tmp_path / 'preview.json'
    path.write_text(json.dumps(preview))
    def scope(**kwargs):
        return SimpleNamespace(package_root=tmp_path, branch_id=kwargs['branch_id'],
                               branch_ref='report-branch:' + kwargs['branch_id'],
                               profile={'session_binding': {'principal_ref': 'alice'}})
    monkeypatch.setattr(command, 'load_profile_root', lambda _: tmp_path)
    monkeypatch.setattr(command, 'resolve_branch_report_scope', scope)
    monkeypatch.setattr(command, 'load_current_authoring', lambda s: {'descriptor': {}})
    # Only persistence into the local Profile registry and Git is isolated here;
    # source reads, preflight, submission lease and atomic tree publication are real.
    finalizations = []
    def finalize(**kwargs):
        finalizations.append(kwargs['submission'].phase)
        if len(finalizations) == 1:
            raise RuntimeError('simulated interruption after HEAD publication')
        return {'git': {'commit': 'test'}}
    monkeypatch.setattr(command, 'finalize_report_command', finalize)
    runner = CliRunner()
    args = ['--profile', 'self', '--report-workspace-id', 'package', '--branch-id', 'target',
            '--preview-file', str(path), '--json']
    preview['operations'][0]['title'] = 'tampered'
    path.write_text(json.dumps(preview))
    result = runner.invoke(command.copy_apply, args)
    assert result.exit_code != 0 and 'preview changed' in result.output
    assert load_snapshot(package_root=tmp_path, branch_id='target')['head'] == target['head']
    preview['operations'] = plan['operations']
    path.write_text(json.dumps(preview))
    result = runner.invoke(command.copy_apply, args)
    assert result.exit_code != 0 and 'simulated interruption' in result.output
    published = load_snapshot(package_root=tmp_path, branch_id='target')['head']
    result = runner.invoke(command.copy_apply, args + ['--submission-sequence', '1'])
    assert result.exit_code == 0, result.output
    assert load_snapshot(package_root=tmp_path, branch_id='target')['head'] == published
    assert json.loads(result.output)['status'] == 'applied'
    saved = load_snapshot(package_root=tmp_path, branch_id='target')
    assert len(saved['components']) == 2
    assert saved['head']['generation'] == 1


def test_selected_subtree_copies_complete_local_files_and_checks_preview_hash(tmp_path):
    from hashlib import sha256
    from tools.cli.release.research_reporting.authoring.copy_resources import stage_resources, destination_path
    source, target = pair(tmp_path)
    attachment = tmp_path / 'branches/source/data.csv'
    raw = b'row,value\n' + b'1,2\n' * 350
    attachment.write_bytes(raw)
    component(tmp_path, 'source', 'attachment', 'entry', 'section', body='[full data](data.csv)')
    # An unrelated missing link must not block copying the selected chapter.
    component(tmp_path, 'source', 'other-chapter', 'chapter')
    component(tmp_path, 'source', 'other-file', 'entry', 'other-chapter', body='[missing](missing.csv)')
    source = load_snapshot(package_root=tmp_path, branch_id='source')
    plan = plan_subtree_copy(source, target, component_ids=['chapter'], copy_id='with-file')
    assert len(plan['resources']) == 1
    assert plan['resources'][0]['sha256'] == sha256(raw).hexdigest()
    with pytest.raises(ValueError, match='staged'):
        apply_subtree_copy(target['paths'], plan, staged_assets=[])
    attachment.write_bytes(b'changed after preview')
    with pytest.raises(ValueError, match='changed since preview'):
        stage_resources(source, target['paths'], plan['resources'])
    attachment.write_bytes(raw)
    stage_resources(source, target['paths'], plan['resources'])
    apply_subtree_copy(target['paths'], plan, staged_assets=[])
    attachment.unlink()
    saved = load_snapshot(package_root=tmp_path, branch_id='target')
    copied = next(n for n in saved['components'] if n['component_id'] == plan['component_map']['attachment'])
    assert copied['body'] == f"[full data]({plan['resources'][0]['destination']})"
    assert destination_path(target['paths'], plan['resources'][0]).read_bytes() == raw
