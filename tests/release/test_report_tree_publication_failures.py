from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring import tree_publication
from tools.cli.release.research_reporting.authoring.binding_index import (
    binding_exists,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_store import load_head


def _tree(tmp_path: Path) -> tuple[Path, dict]:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    return package, created


def _add(package: Path, *, bindings=None) -> dict:
    return add_component(
        package_root=package, branch_id="main",
        component_id="chapter", kind="chapter", title="假设登记",
        parent_id=None, body="", content=None, display_kind="",
        bindings=bindings, include_snapshot=False,
    )


def test_head_failure_precedes_all_future_generation_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, created = _tree(tmp_path)
    monkeypatch.setattr(
        tree_publication, "write_head",
        lambda _paths, _head: (_ for _ in ()).throw(OSError("head failed")),
    )

    with pytest.raises(OSError, match="head failed"):
        _add(package)

    assert load_head(created["paths"])["generation"] == 0
    assert not (created["paths"]["locators"] / "chapter.json").exists()
    assert not (created["paths"]["nodes"] / "chapter").exists()


def test_index_failure_leaves_readable_provisional_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, created = _tree(tmp_path)
    binding = {
        "binding_id": "evidence-a", "kind": "evidence",
        "target_ref": "evidence:a", "label": "证据", "data": {},
    }
    original = tree_publication.publish_binding_index
    monkeypatch.setattr(
        tree_publication, "publish_binding_index",
        lambda *_args: (_ for _ in ()).throw(OSError("index failed")),
    )

    result = _add(package, bindings=[binding])

    assert result["head"]["generation"] == 1
    assert result["head"]["locator_generation"] == 1
    assert load_snapshot(
        package_root=package, branch_id="main",
    )["components"][0]["component_id"] == "chapter"
    assert not binding_exists(created["paths"], "evidence-a", 1)

    monkeypatch.setattr(tree_publication, "publish_binding_index", original)
    add_component(
        package_root=package, branch_id="main", component_id="section",
        kind="section", title="后续", parent_id="chapter", body="",
        content=None, display_kind="", include_snapshot=False,
    )
    assert binding_exists(created["paths"], "evidence-a", 2)


def test_locator_failure_keeps_fallback_generation_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, _created = _tree(tmp_path)
    monkeypatch.setattr(
        tree_publication, "write_locators",
        lambda *_args: (_ for _ in ()).throw(OSError("locator failed")),
    )

    result = _add(package)

    assert result["head"]["generation"] == 1
    assert result["head"]["locator_generation"] == 0
    assert load_snapshot(
        package_root=package, branch_id="main",
    )["components"][0]["component_id"] == "chapter"


def test_indexed_head_failure_never_deletes_provisional_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, created = _tree(tmp_path)
    original = tree_publication.write_head
    calls = 0

    def fail_second(paths: dict, head: dict) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("indexed HEAD failed")
        original(paths, head)

    monkeypatch.setattr(tree_publication, "write_head", fail_second)
    result = _add(package)

    assert result["head"]["generation"] == 1
    assert result["head"]["locator_generation"] == 0
    assert load_head(created["paths"])["root_ref"] == result["head"]["root_ref"]
    assert load_snapshot(
        package_root=package, branch_id="main",
    )["components"][0]["component_id"] == "chapter"


def test_post_replace_head_error_is_confirmed_as_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, created = _tree(tmp_path)
    original = tree_publication.write_head

    def durable_then_fail(paths: dict, head: dict) -> None:
        original(paths, head)
        raise OSError("directory fsync failed")

    monkeypatch.setattr(tree_publication, "write_head", durable_then_fail)
    result = _add(package)

    assert result["head"] == load_head(created["paths"])
    assert load_snapshot(
        package_root=package, branch_id="main",
    )["components"][0]["component_id"] == "chapter"
