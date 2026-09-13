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
        '--profile', 'self', '--work-package-id', 'package', '--branch-id', 'target',
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
