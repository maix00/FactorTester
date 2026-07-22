"""Canonical report methods and per-anchor requirements."""

from __future__ import annotations

import hashlib
from typing import Any

from .catalog import CATEGORY_SPECS
from .topology import EDGE_SPECS, NODE_REQUIREMENTS, NODE_SPECS


METHOD_SPECS = {
    "explain": ("解释机制、选择和限制。", ["sentence", "list"]),
    "inventory": ("逐项列出事实、状态和引用。", ["list", "table"]),
    "compare": ("以共同口径比较目标、基线和差异。", ["sentence", "table", "figure"]),
    "adjudicate": ("逐项裁决义务或 Claim 的变化与边界。", ["sentence", "list", "table"]),
    "present_result": ("展示统计表、指标和图表并说明范围。", ["sentence", "table", "figure"]),
    "explain_gap": ("说明缺口、影响、已尝试路径和恢复条件。", ["sentence", "list", "table"]),
    "explain_transition": ("说明为何选择该边及未选路径。", ["sentence", "list", "table"]),
}


def build_report_method_descriptors() -> dict[str, dict[str, Any]]:
    return {
        method_id: {
            "description_zh": description,
            "allowed_content": allowed,
            "descriptor_hash": hashlib.sha256(
                f"{method_id}|{description}|{','.join(allowed)}".encode()
            ).hexdigest(),
        }
        for method_id, (description, allowed) in METHOD_SPECS.items()
    }


def build_report_requirements(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    requirements = {
        str(item["requirement_id"]): item
        for item in catalog["requirements"]
    }
    reports: list[dict[str, Any]] = []
    for requirement_id, requirement in requirements.items():
        category_id = str(requirement["category_id"])
        home_node = CATEGORY_SPECS[category_id][2]
        reports.append(_report(
            f"report.requirement.{requirement_id}",
            "node_action",
            home_node,
            "adjudicate",
            str(requirement["title_zh"]),
            requirement_ref=requirement_id,
            subject_kind="verification_obligation",
        ))
    for node_id in NODE_SPECS:
        binding = NODE_REQUIREMENTS[node_id][0]
        reports.extend([
            _report(
                f"report.node.{node_id}.entry",
                "node_entry",
                node_id,
                "inventory",
                f"进入「{node_id}」时逐项检查适用义务与复用证据",
                requirement_ref=binding,
                subject_kind="entry_resolution_frame",
            ),
            _report(
                f"report.node.{node_id}.action",
                "node_action",
                node_id,
                _node_method(node_id),
                f"报告「{node_id}」本阶段实际完成的研究事项",
                requirement_ref=binding,
                subject_kind="current_research_scope",
            ),
        ])
    for edge_id, _, _, requirement_ref in EDGE_SPECS:
        reports.append(_report(
            f"report.edge.{edge_id}",
            "edge",
            edge_id,
            "explain_transition",
            f"说明转移「{edge_id}」的依据、影响和恢复位置",
            requirement_ref=requirement_ref,
            subject_kind="transition_delta",
        ))
    reports.extend([
        _report(
            "report.system.continuation_reentry",
            "system_gate",
            "continuation_reentry",
            "compare",
            "逐项报告图版本差异、沿用证据和重新开启事项",
            coordination_ref="graph_continuation",
            subject_kind="graph_version_delta",
        ),
        _report(
            "report.system.node_reentry",
            "system_gate",
            "node_reentry",
            "inventory",
            "逐项报告目标节点、待解决义务、处置路径和恢复状态",
            coordination_ref="entry_resolution_frame",
            subject_kind="entry_resolution_frame",
        ),
        _report(
            "report.system.evidence_admission",
            "system_gate",
            "evidence_admission",
            "adjudicate",
            "逐份报告 Evidence 身份、完整性、适用范围和资格",
            coordination_ref="evidence_qualification",
            subject_kind="evidence_envelope",
        ),
    ])
    return reports


def system_transition_policies() -> list[dict[str, Any]]:
    return [
        {
            "policy_id": "policy.continuation_reentry",
            "policy_kind": "continuation_reentry",
            "report_requirement_refs": ["report.system.continuation_reentry"],
        },
        {
            "policy_id": "policy.node_reentry",
            "policy_kind": "node_reentry",
            "report_requirement_refs": ["report.system.node_reentry"],
        },
        {
            "policy_id": "policy.evidence_admission",
            "policy_kind": "evidence_admission",
            "report_requirement_refs": ["report.system.evidence_admission"],
        },
    ]


def _report(
    report_id: str,
    anchor_kind: str,
    anchor_ref: str,
    method_ref: str,
    title_zh: str,
    *,
    requirement_ref: str = "",
    coordination_ref: str = "",
    subject_kind: str,
) -> dict[str, Any]:
    value = {
        "report_requirement_id": report_id,
        "anchor_kind": anchor_kind,
        "anchor_ref": anchor_ref,
        "method_ref": method_ref,
        "title_zh": title_zh,
        "subject_selector": {"kind": subject_kind},
    }
    value[
        "requirement_ref" if requirement_ref else "coordination_ref"
    ] = requirement_ref or coordination_ref
    return value


def _node_method(node_id: str) -> str:
    if node_id in {"result_audit", "research_decision"}:
        return "adjudicate"
    if "gap" in node_id or "improvement" in node_id:
        return "explain_gap"
    if node_id == "trial_execution":
        return "present_result"
    return "explain"
