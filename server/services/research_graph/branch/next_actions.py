"""Small, ordered next-action instructions for one Agent packet."""

from __future__ import annotations

from typing import Any


def node_next_actions(
    *,
    instance_id: str,
    branch_id: str,
    context: dict[str, Any],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the smallest ordered action list for the current Node."""
    report = context.get("report_requirements") or {}
    current = report.get("current_node") or {}
    entry_requirements = [
        item for item in context.get("entry_requirements") or []
        if isinstance(item, dict)
    ]
    if entry_requirements:
        requirement_ids = sorted({
            str(item.get("requirement_id") or "")
            for item in entry_requirements
            if item.get("requirement_id")
        })
        command = (
            "factortester research-graph node advance "
            f"{instance_id} {branch_id} --edge-id <edge-id> "
            "--evidence-file <evidence-file> "
            "--entry-assessment-file <assessment-file> "
            "--factor-family <factor-family>"
        )
        return [{
            "action_id": "entry.assess",
            "kind": "entry_resolution",
            "blocking": True,
            "reason": "当前节点检查尚未完成，不能推进到下一节点",
            "requirement_ids": requirement_ids,
            "command": command,
            "instruction": (
                "首次执行只生成节点检查编辑文档且不会推进；"
                "完成文档中的全部 __EDIT__ 字段后复用同一命令"
            ),
            "then": command,
        }]
    missing_exit = [
        item for item in current.get("on_exit") or []
        if (
            isinstance(item, dict)
            and item.get("status") == "missing"
            and report.get("enforcement") == "required"
        )
    ]
    if missing_exit:
        return [{
            "action_id": "report.complete_on_exit",
            "kind": "report",
            "blocking": True,
            "reason": "当前节点离开前的报告要求尚未完成",
            "requirement_ids": [
                str(item.get("report_requirement_id") or "")
                for item in missing_exit
            ],
            "command": (
                "factortester report add --profile <profile> "
                "--work-package-id <work-package> --branch-id <branch> "
                "--component-id <component-id> --kind <kind> "
                "--title <title>"
            ),
            "report_requirement_options": (
                "--report-requirement-id <requirement-id> "
                "--report-subject-ref <subject-ref> "
                "--report-content-kind <allowed-kind>"
            ),
            "then": (
                "factortester research-graph node info "
                "<instance-id> <branch-id>"
            ),
        }]
    if not edges:
        return [{
            "action_id": "node.inspect",
            "kind": "inspect",
            "blocking": True,
            "reason": "当前节点没有可用的 Edge",
            "command": (
                "factortester research-graph node info "
                f"{instance_id} {branch_id}"
            ),
        }]
    return [{
        "action_id": "edge.choose",
        "kind": "edge",
        "blocking": False,
        "reason": "节点进入要求已满足；完成本节点计划研究后再选择下一条路径",
        "edge_ids": [str(item.get("edge_id") or "") for item in edges],
        "command": (
            "factortester research-graph edge info "
            f"{instance_id} {branch_id} <edge-id>"
        ),
        "then": (
            "factortester research-graph edge choose "
            f"{instance_id} {branch_id} <edge-id>"
        ),
        "instruction": (
            "候选 Edge 仅供预览；即使只有一个候选，也应在完成本节点研究后"
            "才执行 edge choose，除非 Graph 明确把该节点标为纯路由节点"
        ),
    }]


def compact_next_actions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {
            key: item[key]
            for key in (
                "action_id", "kind", "blocking", "reason", "command",
                "instruction", "report_requirement_options", "then", "edge_ids",
                "requirement_ids",
            )
            if key in item
        }
        for item in value
        if isinstance(item, dict)
    ]


def edge_next_actions(
    *,
    instance_id: str,
    branch_id: str,
    edge_id: str,
    requirements: list[dict[str, Any]],
    enforcement: str,
) -> list[dict[str, Any]]:
    missing = [
        item for item in requirements
        if isinstance(item, dict) and item.get("status") == "missing"
    ]
    if missing and enforcement == "required":
        return [{
            "action_id": "report.complete_on_edge",
            "kind": "report",
            "blocking": True,
            "reason": "选择该 Edge 后需要先完成边报告",
            "requirement_ids": [
                str(item.get("report_requirement_id") or "")
                for item in missing
            ],
            "command": (
                "factortester report add --profile <profile> "
                "--work-package-id <work-package> --branch-id <branch> "
                "--component-id <component-id> --kind <kind> "
                "--title <title>"
            ),
            "report_requirement_options": (
                "--report-requirement-id <requirement-id> "
                "--report-subject-ref <subject-ref> "
                "--report-content-kind <allowed-kind>"
            ),
            "then": (
                "factortester research-graph node advance "
                f"{instance_id} {branch_id} --edge-id {edge_id} "
                "--evidence-file <evidence-file>"
            ),
        }]
    return [{
        "action_id": "node.advance",
        "kind": "advance",
        "blocking": False,
        "reason": "该 Edge 的报告要求已满足，可以推进",
        "command": (
            "factortester research-graph node advance "
            f"{instance_id} {branch_id} --edge-id {edge_id} "
            "--evidence-file <evidence-file>"
        ),
    }]
