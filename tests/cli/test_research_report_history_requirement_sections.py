from pathlib import Path

import pytest

from tools.cli.commands.research_report_history_requirement_sections import (
    migrate_requirement_sections,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    load_snapshot,
)


def test_legacy_requirement_content_is_promoted_in_place(tmp_path: Path) -> None:
    package = tmp_path / "package"
    initialize_tree(
        package_root=package,
        branch_id="branch",
        report_id="report",
        title="研究报告",
    )
    _add(package, "chapter", "chapter", None)
    _add(package, "before", "entry", "chapter")
    _add(
        package,
        "legacy",
        "entry",
        "chapter",
        title="列表",
        body="保留原始正文",
        bindings=[_report_binding()],
    )
    _add(package, "after", "entry", "chapter")

    result = migrate_requirement_sections(
        package_root=package,
        branch_id="branch",
        contexts=[{
            "requirement_presentations": [{
                "requirement_id": "data.temporal_coverage",
                "title_zh": "时间覆盖",
            }],
        }],
    )
    snapshot = load_snapshot(package_root=package, branch_id="branch")
    components = {
        item["component_id"]: item for item in snapshot["components"]
    }
    chapter_children = [
        item["component_id"] for item in snapshot["components"]
        if item["parent_id"] == "chapter"
    ]

    assert result["migrated_count"] == 1
    assert chapter_children == ["before", "legacy", "after"]
    assert components["legacy"]["kind"] == "special"
    assert components["legacy"]["display_kind"] == (
        "obligation_requirement"
    )
    assert components["legacy"]["title"] == "时间覆盖"
    assert components["legacy"]["parent_id"] == "chapter"
    assert "保留原始正文" in components["legacy"]["body"]
    assert "factortester://entry_requirement/" in components["legacy"]["body"]
    assert components["legacy"]["content"] is None
    special_bindings = [
        item for item in snapshot["bindings"]
        if item["component_id"] == "legacy"
    ]
    assert {item["kind"] for item in special_bindings} == {
        "entry_requirement", "report_requirement",
    }

    generation = snapshot["head"]["generation"]
    repeated = migrate_requirement_sections(
        package_root=package,
        branch_id="branch",
        contexts=[{
            "requirement_presentations": [{
                "requirement_id": "data.temporal_coverage",
                "title_zh": "时间覆盖",
            }],
        }],
    )
    assert repeated["migrated_count"] == 0
    assert load_snapshot(
        package_root=package, branch_id="branch",
    )["head"]["generation"] == generation


def test_migration_refuses_to_guess_a_missing_title(tmp_path: Path) -> None:
    package = tmp_path / "package"
    initialize_tree(
        package_root=package,
        branch_id="branch",
        report_id="report",
        title="研究报告",
    )
    _add(package, "chapter", "chapter", None)
    _add(
        package,
        "legacy",
        "entry",
        "chapter",
        bindings=[_report_binding()],
    )

    with pytest.raises(ValueError, match="no Graph title_zh"):
        migrate_requirement_sections(
            package_root=package,
            branch_id="branch",
            contexts=[],
        )
    snapshot = load_snapshot(package_root=package, branch_id="branch")
    assert snapshot["head"]["generation"] == 2
    assert snapshot["components"][-1]["component_id"] == "legacy"


def test_explicit_historical_mapping_wraps_pre_binding_content(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    initialize_tree(
        package_root=package,
        branch_id="branch",
        report_id="report",
        title="研究报告",
    )
    _add(package, "chapter", "chapter", None)
    _add(
        package,
        "historical-mechanism",
        "entry",
        "chapter",
        body="保留历史机制正文",
    )

    result = migrate_requirement_sections(
        package_root=package,
        branch_id="branch",
        contexts=[],
        requirement_titles={
            "hypothesis_validity.mechanism_chain": "机制作用链",
        },
        component_requirement_hints={
            "historical-mechanism": {
                "requirement_id": "hypothesis_validity.mechanism_chain",
                "subject_ref": "obligation:price-momentum-core-hypothesis",
                "content_kind": "list",
            },
        },
    )
    snapshot = load_snapshot(package_root=package, branch_id="branch")
    components = {
        item["component_id"]: item for item in snapshot["components"]
    }
    special_bindings = [
        item for item in snapshot["bindings"]
        if item["component_id"] == "historical-mechanism"
    ]

    assert result["migrated_count"] == 1
    assert components["historical-mechanism"]["kind"] == "special"
    assert components["historical-mechanism"]["display_kind"] == (
        "obligation_requirement"
    )
    assert components["historical-mechanism"]["parent_id"] == "chapter"
    assert components["historical-mechanism"]["title"] == (
        "historical-mechanism"
    )
    assert "保留历史机制正文" in components["historical-mechanism"]["body"]
    assert "factortester://entry_requirement/" in components[
        "historical-mechanism"
    ]["body"]
    report_binding = next(
        item for item in special_bindings
        if item["kind"] == "report_requirement"
    )
    assert report_binding["target_ref"] == (
        "report.requirement.hypothesis_validity.mechanism_chain"
    )
    assert report_binding["data"]["subject_ref"] == (
        "obligation:price-momentum-core-hypothesis"
    )
    assert report_binding["data"]["content_kind"] == "list"


def _add(
    package: Path,
    component_id: str,
    kind: str,
    parent_id: str | None,
    *,
    title: str | None = None,
    body: str = "",
    bindings: list[dict] | None = None,
) -> None:
    add_component(
        package_root=package,
        branch_id="branch",
        component_id=component_id,
        kind=kind,
        title=title or component_id,
        parent_id=parent_id,
        body=body,
        content=None,
        display_kind="",
        bindings=bindings,
    )


def _report_binding() -> dict:
    return {
        "binding_id": "legacy-report-requirement",
        "kind": "report_requirement",
        "target_ref": "report.requirement.data.temporal_coverage",
        "label": "报告义务",
        "data": {
            "report_requirement_id": (
                "report.requirement.data.temporal_coverage"
            ),
            "subject_ref": "requirement:data.temporal_coverage",
            "content_kind": "narrative",
        },
    }
