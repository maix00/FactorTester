"""Cross-branch copy through real scope, preflight, persistence and Git gates."""
import json

from click.testing import CliRunner

from tools.cli.commands import research_report_copy, research_report_copy_apply
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.report_space import initialize_report_space
from tools.cli.release.research_reporting.workspace import initialize_work_package
from tools.cli.release.research_reporting.authoring.tree_model import add_component, load_snapshot


def test_cli_copies_chapter_with_formula_internal_link_and_full_attachment(tmp_path):
    store = LocalProfileStore(tmp_path / 'client')
    profile = new_local_profile(profile_id='self', display_name='Alice', server_url='http://localhost:7998',
                                workspace_root=tmp_path / 'workspace')
    profile['session_binding'] = {'principal_ref': 'alice', 'session_ref': 'session-binding:test'}
    store.save(profile)
    report = {'report_id': 'report', 'research_id': 'research', 'owner_ref': 'alice',
              'profile_ref': 'self', 'workspace_id': 'workspace', 'title': 'Report'}
    package_id = initialize_report_space(store, 'self', report)['work_package_id']
    source_tree = initialize_work_package(workspace_root=tmp_path / 'workspace', work_package_id=package_id,
        branch_id='review', workspace_id='workspace', title='Review', branch_ref='report-branch:review')
    record = store.load('self')['research_records'][0]
    record['artifacts'].append(source_tree['descriptor'])
    store.upsert_research_record('self', record)
    package = tmp_path / 'workspace/research' / package_id
    for node_id, kind, parent, body, content in [
        ('chapter', 'chapter', None, '', None),
        ('section', 'section', 'chapter', '', None),
        ('text', 'entry', 'section', '[formula](factortester://report_section/node%3Aformula)', None),
        ('formula', 'math', 'section', '', {'latex': 'x^2', 'fallback': ''}),
        ('file', 'entry', 'section', '[all rows](rows.csv)', None),
    ]:
        add_component(package_root=package, branch_id='review', component_id=node_id, kind=kind,
                      title=node_id, parent_id=parent, body=body, content=content, display_kind='')
    raw = b'row,value\n' + b'1,2\n' * 350
    (package / 'branches/review/rows.csv').write_bytes(raw)
    before = load_snapshot(package_root=package, branch_id='review')['head']
    release_profile = tmp_path / 'release.json'
    release_profile.write_text(json.dumps({'release': {'install_root': str(tmp_path / 'client')}}))
    common = ['--profile', 'self', '--work-package-id', package_id, '--branch-id', 'main',
              '--release-profile', str(release_profile), '--json']
    runner = CliRunner()
    preview = runner.invoke(research_report_copy.copy_preview, common + [
        '--source-branch-id', 'review', '--component-id', 'chapter', '--copy-id', 'owner-selection'])
    assert preview.exit_code == 0, preview.output
    preview_file = tmp_path / 'preview.json'
    preview_file.write_text(preview.output)
    result = runner.invoke(research_report_copy_apply.copy_apply, common + ['--preview-file', str(preview_file)])
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert receipt['status'] == 'applied' and receipt['git']
    saved = load_snapshot(package_root=package, branch_id='main')
    assert len(saved['components']) == 5
    assert saved['head']['generation'] == 1
    assert load_snapshot(package_root=package, branch_id='review')['head'] == before
    plan = json.loads(preview.output)
    from tools.cli.release.research_reporting.authoring.copy_resources import destination_path
    assert destination_path(saved['paths'], plan['resources'][0]).read_bytes() == raw
    assert len(store.load('self')['research_records'][0]['artifacts']) == 2
    retry = runner.invoke(research_report_copy_apply.copy_apply, common + [
        '--preview-file', str(preview_file), '--submission-sequence', '1'])
    assert retry.exit_code == 0, retry.output
    assert json.loads(retry.output)['resumed'] is True
    assert load_snapshot(package_root=package, branch_id='main')['head'] == saved['head']


def test_report_reference_rejects_missing_target_and_file_escape(tmp_path):
    from types import SimpleNamespace
    import pytest
    from tools.cli.release.research_reporting.authoring.tree_model import initialize_tree
    from tools.cli.release.research_reporting.references.preflight import preflight_component
    from tools.cli.release.research_reporting.references.diagnostics import ReportPreflightError
    package = tmp_path / 'package'
    initialize_tree(package_root=package, branch_id='main', report_id='report', title='Report')
    scope = SimpleNamespace(package_root=package, branch_id='main')
    with pytest.raises(ReportPreflightError, match='does not exist in the target branch'):
        preflight_component(scope=scope, component_id='link', kind='entry', title='', content=None,
                            body='[missing](factortester://report_section/node%3Amissing)')
    private = tmp_path / 'outside.txt'
    private.write_text('must not enter report')
    (package / 'branches/main/escape.txt').symlink_to(private)
    with pytest.raises(ReportPreflightError):
        preflight_component(scope=scope, component_id='file', kind='entry', title='', content=None,
                            body='[outside](escape.txt)')
