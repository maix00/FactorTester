"""Public removal guard for Agent-authored report components."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_navigation import node_path
from .tree_store import load_node


def validate_agent_removal(
    paths: dict[str, Path],
    head: dict[str, Any],
    root: dict[str, Any],
    component_id: str,
    *,
    include_children: bool,
) -> list[str]:
    """Return the exact removable subtree or reject protected structure."""
    nodes, _edges = node_path(
        paths, root, component_id, head["generation"],
    )
    target = nodes[-1]
    _reject_protected(target)
    if target["children"] and not include_children:
        raise ValueError(
            "报告条目包含子项；确认整棵普通子树后使用 --include-children"
        )

    removable: list[str] = []
    protected: list[str] = []

    def visit(node: dict[str, Any]) -> None:
        removable.append(str(node["node_id"]))
        if node["kind"] in {"chapter", "special"}:
            protected.append(str(node["node_id"]))
        for child in node["children"]:
            visit(load_node(paths, child["ref"]))

    visit(target)
    if protected:
        raise ValueError(
            "不能删除包含特殊小节的报告子树；受保护组件: "
            + ", ".join(protected)
        )
    return removable


def _reject_protected(component: dict[str, Any]) -> None:
    if component["kind"] == "chapter":
        raise ValueError("研究图章节不能由 Agent 删除")
    if component["kind"] == "special":
        raise ValueError("特殊小节不能由 Agent 删除")
