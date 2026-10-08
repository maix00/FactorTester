from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    apply_batch,
    initialize_tree,
)


def _binding(
    binding_id: str, kind: str, target: str, label: str,
) -> dict[str, object]:
    return {
        "binding_id": binding_id, "kind": kind, "target_ref": target,
        "label": label, "data": {"label": label},
    }


def _tree(tmp_path: Path) -> Path:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    return package


def _add(
    package: Path, component_id: str, *, parent_id: str | None = None,
    bindings: list[dict[str, object]] | None = None,
) -> None:
    add_component(
        package_root=package, branch_id="main",
        component_id=component_id,
        kind="chapter" if parent_id is None else "entry",
        title=f"旧 {component_id}", parent_id=parent_id,
        body="旧正文", content=None, display_kind="",
        bindings=bindings,
    )


def test_replace_updates_authored_fields_without_moving_hierarchy(
    tmp_path: Path,
) -> None:
    package = _tree(tmp_path)
    target = "Product/Futures/CNFutures/_products/SI.GFE"
    _add(package, "chapter", bindings=[
        _binding("reference-old-product", "product", target, "旧工业硅"),
    ])
    _add(package, "child", parent_id="chapter")

    saved = apply_batch(
        package_root=package, branch_id="main",
        operations=[{
            "op": "replace", "component_id": "chapter",
            "title": "新章节", "body": "新正文",
            "content": "补充内容", "display_kind": "finding",
            "bindings": [
                _binding("reference-product", "product", target, "工业硅"),
                _binding("reference-job", "job", "job:one", "回测任务"),
            ],
        }],
    )

    chapter = next(
        item for item in saved["components"]
        if item["component_id"] == "chapter"
    )
    child = next(
        item for item in saved["components"]
        if item["component_id"] == "child"
    )
    assert (
        chapter["title"], chapter["body"], chapter["content"],
        chapter["display_kind"],
    ) == ("新章节", "新正文", "补充内容", "finding")
    assert child["parent_id"] == "chapter"
    bindings = {
        item["binding_id"]: item for item in saved["bindings"]
        if item["component_id"] == "chapter"
    }
    assert set(bindings) == {
        "reference-product", "reference-job",
    }
    assert "reference-old-product" not in bindings
    assert bindings["reference-product"]["label"] == "工业硅"
    assert bindings["reference-product"]["data"] == {"label": "工业硅"}


def test_replace_rejects_binding_id_owned_by_another_component_atomically(
    tmp_path: Path,
) -> None:
    package = _tree(tmp_path)
    _add(package, "first", bindings=[
        _binding("reference-shared", "job", "job:first", "任务一"),
    ])
    _add(package, "second")
    before = (
        package / "branches" / "main" / "authoring" / "HEAD.json"
    ).read_bytes()

    with pytest.raises(ValueError, match="binding_id already exists"):
        apply_batch(
            package_root=package, branch_id="main",
            operations=[{
                "op": "replace", "component_id": "second",
                "title": "非法替换", "body": "", "content": None,
                "display_kind": "", "bindings": [
                    _binding(
                        "reference-shared", "job", "job:second", "任务二",
                    ),
                ],
            }],
        )

    assert (
        package / "branches" / "main" / "authoring" / "HEAD.json"
    ).read_bytes() == before
