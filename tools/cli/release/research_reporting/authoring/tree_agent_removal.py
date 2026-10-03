"""Public removal guard for Agent-authored report components."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .tree_navigation import node_path
from .tree_store import load_node

# ``job collect-report`` writes one ``test_result`` section per Job plus one
# ``evidence_fragment`` section per mounted artifact, both keyed by the Job id.
# They are the Agent's own mounts, so the Agent must be able to withdraw them
# again (otherwise a re-mount after a retry can never be cleaned up). System
# lifecycle special sections stay protected.
AGENT_MOUNTED_EVIDENCE_KINDS = frozenset({"test_result", "evidence_fragment"})
_JOB_MOUNT_NODE_ID = re.compile(r"job-[0-9a-f]{32}(?:-|$)")


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
        if _is_protected(node):
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


def _is_protected(component: dict[str, Any]) -> bool:
    if component["kind"] == "chapter":
        return True
    if component["kind"] != "special":
        return False
    return not is_agent_mounted_job_evidence(component)


def is_agent_mounted_job_evidence(component: dict[str, Any]) -> bool:
    """True for the Job evidence mounts the Agent itself created."""
    return (
        str(component.get("display_kind") or "")
        in AGENT_MOUNTED_EVIDENCE_KINDS
        and bool(_JOB_MOUNT_NODE_ID.match(str(component.get("node_id") or "")))
    )


def _reject_protected(component: dict[str, Any]) -> None:
    if component["kind"] == "chapter":
        raise ValueError("报告章节不能由 Agent 删除")
    if _is_protected(component):
        raise ValueError("特殊小节不能由 Agent 删除")
