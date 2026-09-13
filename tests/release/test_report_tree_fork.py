from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_fork import (
    fork_report_tree,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    load_snapshot,
)


def test_forked_report_changes_independently(tmp_path: Path) -> None:
    package = tmp_path / "research" / "package-a"
    initialize_tree(
        package_root=package,
        branch_id="source",
        report_id="report-source",
        title="研究报告",
    )
    add_component(
        package_root=package, branch_id="source",
        component_id="chapter-a", kind="chapter", title="假设登记",
        parent_id=None, body="", content=None, display_kind="",
    )
    fork_report_tree(
        package_root=package,
        source_branch_id="source",
        target_branch_id="target",
        target_report_id="report-source",
    )

    add_component(
        package_root=package, branch_id="target",
        component_id="fork-note", kind="entry", title="分支结论",
        parent_id="chapter-a", body="仅属于新分支",
        content=None, display_kind="",
    )
    source = load_snapshot(package_root=package, branch_id="source")
    target = load_snapshot(package_root=package, branch_id="target")

    assert [item["component_id"] for item in source["components"]] == [
        "chapter-a",
    ]
    assert [item["component_id"] for item in target["components"]] == [
        "chapter-a", "fork-note",
    ]
    assert target["head"]["report_id"] == source["head"]["report_id"]


def test_cross_package_fork_preserves_asset_bytes_and_source(tmp_path):
    import hashlib
    from tools.cli.release.research_reporting.authoring.tree_model import add_asset
    from tools.cli.release.research_reporting.authoring.tree_fork import inherit_report_tree_across_packages
    source, target = tmp_path / 'source', tmp_path / 'target'
    initialize_tree(package_root=source, branch_id='main', report_id='report-1', title='report')
    asset_path = source / 'assets' / 'plot.png'
    asset_path.parent.mkdir()
    asset_path.write_bytes(b'original image bytes')
    digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    add_asset(package_root=source, branch_id='main', asset={
        'asset_ref': 'asset:plot', 'media_type': 'image/png', 'filename': 'plot.png',
        'caption': 'caption', 'alt_text': 'plot', 'local_ref': 'assets/plot.png',
        'content_hash': digest,
    })
    before = load_snapshot(package_root=source, branch_id='main')['head']
    result = inherit_report_tree_across_packages(
        source_package_root=source, target_package_root=target,
        source_branch_id='main', target_branch_id='review', target_report_id='report-1',
    )
    asset = result['head']['assets'][0]
    assert (target / asset['local_ref']).read_bytes() == asset_path.read_bytes()
    assert asset['content_hash'] == digest
    assert load_snapshot(package_root=source, branch_id='main')['head'] == before
    asset_path.unlink()
    assert (target / asset['local_ref']).read_bytes() == b'original image bytes'


def test_cross_package_fork_rejects_missing_asset_before_head_publication(tmp_path):
    import pytest
    from tools.cli.release.research_reporting.authoring.tree_model import add_asset
    from tools.cli.release.research_reporting.authoring.tree_fork import inherit_report_tree_across_packages
    source, target = tmp_path / 'source', tmp_path / 'target'
    initialize_tree(package_root=source, branch_id='main', report_id='report-1', title='report')
    add_asset(package_root=source, branch_id='main', asset={
        'asset_ref': 'asset:missing', 'media_type': 'image/png', 'filename': 'plot.png',
        'caption': '', 'alt_text': '', 'local_ref': 'assets/missing.png',
    })
    with pytest.raises(ValueError, match='missing'):
        inherit_report_tree_across_packages(
            source_package_root=source, target_package_root=target,
            source_branch_id='main', target_branch_id='review', target_report_id='report-1',
        )
    assert not (target / 'branches/review/authoring/HEAD.json').exists()


def test_fork_source_version_check_precedes_target_publication(tmp_path):
    import pytest
    from tools.cli.release.research_reporting.authoring.tree_fork import inherit_report_tree_across_packages
    source = tmp_path / 'source'
    initialize_tree(package_root=source, branch_id='main', report_id='report-one', title='report')
    add_component(package_root=source, branch_id='main', component_id='chapter', kind='chapter',
                  title='changed', parent_id=None, body='', content=None, display_kind='')
    with pytest.raises(ValueError, match='source version changed'):
        fork_report_tree(package_root=source, source_branch_id='main', target_branch_id='new',
                         target_report_id='report-one', expected_source_generation=0)
    with pytest.raises(ValueError, match='source version changed'):
        inherit_report_tree_across_packages(source_package_root=source, target_package_root=tmp_path / 'target',
                         source_branch_id='main', target_branch_id='new',
                         target_report_id='report-one', expected_source_generation=0)
    assert not (source / 'branches/new/authoring/HEAD.json').exists()
    assert not (tmp_path / 'target/branches/new/authoring/HEAD.json').exists()


def test_forked_staged_image_is_readable_by_existing_publication_adapter(tmp_path):
    from tools.cli.release.research_reporting.assets import stage_branch_image
    from tools.cli.release.research_reporting.authoring.tree_model import add_asset
    from tools.cli.release.research_reporting.public_research.projection import read_local_asset, asset_id_for
    from tools.cli.release.research_reporting.authoring.tree_fork import inherit_report_tree_across_packages
    source, target = tmp_path / 'source', tmp_path / 'target'
    initialize_tree(package_root=source, branch_id='main', report_id='r', title='r')
    image = tmp_path / 'image.png'
    image.write_bytes(b'image bytes')
    asset = stage_branch_image(package_root=source, branch_id='main', source_path=image)
    add_asset(package_root=source, branch_id='main', asset=asset)
    inherit_report_tree_across_packages(source_package_root=source, target_package_root=target,
                                       source_branch_id='main', target_branch_id='copy', target_report_id='r')
    snapshot = load_snapshot(package_root=target, branch_id='copy')
    assert read_local_asset(snapshot, asset_id_for(asset['asset_ref']))[0] == image.read_bytes()
