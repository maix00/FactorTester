from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    apply_batch,
    initialize_tree,
)


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    return package, created["paths"]["head"]


def _add(
    package: Path, component_id: str, kind: str, parent_id: str | None,
) -> None:
    add_component(
        package_root=package, branch_id="main",
        component_id=component_id, kind=kind, title=component_id,
        parent_id=parent_id, body="", content=None, display_kind="external_review" if kind == "special" else "",
    )


def test_move_after_orders_siblings_and_requires_same_final_parent(
    tmp_path: Path,
) -> None:
    package, head = _tree(tmp_path)
    _add(package, "source", "chapter", None)
    _add(package, "target", "chapter", None)
    _add(package, "anchor", "entry", "target")
    _add(package, "one", "entry", "source")
    _add(package, "two", "entry", "source")

    saved = apply_batch(
        package_root=package, branch_id="main", operations=[
            {
                "op": "move", "component_id": "one",
                "parent_id": "target", "after_component_id": "anchor",
            },
            {
                "op": "move", "component_id": "two",
                "parent_id": "target", "after_component_id": "one",
            },
        ],
    )
    target_children = [
        item["component_id"] for item in saved["components"]
        if item["parent_id"] == "target"
    ]
    assert target_children == ["anchor", "one", "two"]

    before = head.read_bytes()
    with pytest.raises(ValueError, match="same parent"):
        apply_batch(
            package_root=package, branch_id="main", operations=[{
                "op": "move", "component_id": "one",
                "parent_id": "source", "after_component_id": "anchor",
            }],
        )
    assert head.read_bytes() == before


def test_move_rejects_cycles_and_parent_kind_without_publishing(
    tmp_path: Path,
) -> None:
    package, head = _tree(tmp_path)
    _add(package, "chapter", "chapter", None)
    _add(package, "section", "section", "chapter")
    _add(package, "subsection", "subsection", "section")
    _add(package, "other-chapter", "chapter", None)
    _add(package, "other-section", "section", "other-chapter")

    for operation, message in [
        ({
            "op": "move", "component_id": "section",
            "parent_id": "subsection", "after_component_id": None,
        }, "cycle"),
        ({
            "op": "move", "component_id": "chapter",
            "parent_id": "other-section", "after_component_id": None,
        }, "parent kind"),
    ]:
        before = head.read_bytes()
        with pytest.raises(ValueError, match=message):
            apply_batch(
                package_root=package, branch_id="main",
                operations=[operation],
            )
        assert head.read_bytes() == before


def test_move_rejects_raw_bindings_and_duplicate_move_slot(
    tmp_path: Path,
) -> None:
    package, _head = _tree(tmp_path)
    _add(package, "chapter-a", "chapter", None)
    _add(package, "chapter-b", "chapter", None)
    _add(package, "entry", "entry", "chapter-a")

    with pytest.raises(ValueError, match="fields are invalid"):
        apply_batch(
            package_root=package, branch_id="main", operations=[{
                "op": "move", "component_id": "entry",
                "parent_id": "chapter-b", "after_component_id": None,
                "bindings": [],
            }],
        )
    operation = {
        "op": "move", "component_id": "entry",
        "parent_id": "chapter-b", "after_component_id": None,
    }
    with pytest.raises(ValueError, match="more than once"):
        apply_batch(
            package_root=package, branch_id="main",
            operations=[operation, operation],
        )


def test_recursive_subsections_round_trip_and_special_peer_heading(tmp_path: Path) -> None:
    from tools.cli.release.research_reporting.authoring.tree_model import load_snapshot
    from tools.cli.release.research_reporting.authoring.tree_render import render_tree_markdown
    package, _ = _tree(tmp_path)
    for component_id, kind, parent in [
        ("chapter", "chapter", None), ("section", "section", "chapter"),
        ("duration", "subsection", "section"),
        ("why", "subsection", "duration"),
        ("reason", "subsection", "why"),
        ("audit", "special", "why"),
        ("nested", "subsection", "audit"),
        ("body", "entry", "nested"),
    ]:
        _add(package, component_id, kind, parent)
    saved = load_snapshot(package_root=package, branch_id="main")
    assert all(item["kind"] == "section" for item in saved["components"]
               if item["component_id"] in {"section", "duration", "why", "reason", "nested"})
    parents = {item["component_id"]: item["parent_id"] for item in saved["components"]}
    assert parents["why"] == "duration" and parents["nested"] == "audit"
    text = render_tree_markdown(saved).decode()
    assert "\n#### why\n" in text
    assert "\n##### reason\n" in text and "\n##### audit\n" in text
    assert "\n###### nested\n" in text
    moved = apply_batch(package_root=package, branch_id="main", operations=[{
        "op": "move", "component_id": "reason", "parent_id": "nested",
        "after_component_id": None,
    }])
    assert next(item for item in moved["components"] if item["component_id"] == "reason")["parent_id"] == "nested"
    with pytest.raises(ValueError, match="cycle"):
        apply_batch(package_root=package, branch_id="main", operations=[{
            "op": "move", "component_id": "why", "parent_id": "reason",
            "after_component_id": None,
        }])


def test_legacy_section_alias_preserves_stored_bytes_and_accepts_recursive_children():
    from tools.cli.release.research_reporting.authoring.tree_hierarchy import validate_parent_child
    from tools.cli.release.research_reporting.authoring.tree_schema import validate_node
    legacy = {"schema_version":1, "node_id":"old", "kind":"subsection", "title":"旧子节",
              "body":"", "content":None, "display_kind":"", "created_at":1.0, "children":[], "bindings":[]}
    assert validate_node(legacy) == legacy  # Reading must not change content-addressed identities.
    for parent in ["section", "subsection", "special"]:
        for child in ["section", "subsection", "special"]:
            validate_parent_child(parent_kind=parent, child_kind=child)
