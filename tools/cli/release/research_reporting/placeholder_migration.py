"""One-shot removal of explicitly superseded report placeholders.

This migration is intentionally manifest-driven.  It never discovers
successors by title similarity and never changes a section unless the caller
names both physical identities and their shared semantic identity.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .journal import content_hash, validate_fragment_sequence

_OBLIGATION_LABELS = {
    "obligation:sgccs-semantic-causal-role":
        "SgCCS 的经济语义与因果时序义务",
    "obligation:sgccs-performance-transportability":
        "跨时间、环境与标的迁移义务",
    "obligation:sgccs-incremental-value":
        "SgCCS 相对主因子的增量价值义务",
    "obligation:sgccs-signal-schedule-strategy-policy":
        "信号调度与交易策略义务",
}


def migrate_placeholders(
    fragments: list[dict[str, Any]],
    replacements: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    values = deepcopy(fragments)
    obligations_before = _reference_set(values, "obligation")
    evidence_before = _reference_set(values, "evidence")
    sections = {
        (fragment["checkpoint_ref"], section["section_id"]):
        (fragment, section)
        for fragment in values
        for section in fragment["sections"]
    }
    removals: set[tuple[str, str]] = set()
    changes = []
    for replacement in replacements:
        before_id = (
            replacement["before_checkpoint_ref"],
            replacement["before_section_id"],
        )
        after_id = (
            replacement["successor_checkpoint_ref"],
            replacement["successor_section_id"],
        )
        if before_id in removals:
            raise ValueError("placeholder replacement source is not unique")
        if after_id not in sections or before_id == after_id:
            raise ValueError("placeholder successor does not exist")
        if before_id not in sections:
            after_fragment, after = sections[after_id]
            if (
                after_fragment["graph_ref"] != replacement["graph_ref"]
                or _binding(after) != {
                    "report_requirement_id":
                        replacement["report_requirement_id"],
                    "subject_ref": replacement["subject_ref"],
                }
                or after["title"].startswith("当前节点报告项 ")
            ):
                raise ValueError("applied placeholder receipt is inconsistent")
            changes.append({**replacement, "status": "already_applied"})
            continue
        before_fragment, before = sections[before_id]
        after_fragment, after = sections[after_id]
        before_binding = _binding(before)
        after_binding = _binding(after)
        identity = {
            "graph_ref": replacement["graph_ref"],
            "node_or_edge_ref": replacement["node_or_edge_ref"],
            "report_requirement_id": replacement["report_requirement_id"],
            "subject_ref": replacement["subject_ref"],
        }
        if (
            before_fragment["graph_ref"] != identity["graph_ref"]
            or after_fragment["graph_ref"] != identity["graph_ref"]
            or before_binding != after_binding
            or before_binding != {
                "report_requirement_id":
                    identity["report_requirement_id"],
                "subject_ref": identity["subject_ref"],
            }
            or not before["title"].startswith("当前节点报告项 ")
            or after["title"].startswith("当前节点报告项 ")
            or before_fragment["created_at"] >= after_fragment["created_at"]
        ):
            raise ValueError("placeholder replacement identity mismatch")
        removals.add(before_id)
        _preserve_references(before, after)
        changes.append({**identity, **replacement, "status": "removed"})

    old_predecessors = {
        item["checkpoint_ref"]: item["predecessor_checkpoint_ref"]
        for item in values
    }
    retained = []
    for fragment in values:
        fragment["sections"] = [
            section for section in fragment["sections"]
            if (fragment["checkpoint_ref"], section["section_id"])
            not in removals
        ]
        if fragment["sections"]:
            retained.append(fragment)
    removed_checkpoint_refs = {
        item["checkpoint_ref"] for item in values if not item["sections"]
    }
    for fragment in retained:
        for section in fragment["sections"]:
            for link in section.get("links") or []:
                if link.get("label") == "研究事实":
                    link["label"] = _reference_label(
                        str(link.get("target_ref") or ""), ""
                    )
        predecessor = fragment["predecessor_checkpoint_ref"]
        while predecessor in removed_checkpoint_refs:
            predecessor = old_predecessors.get(predecessor, "")
        fragment["predecessor_checkpoint_ref"] = predecessor
        fragment.pop("section_hash", None)
        fragment["section_hash"] = content_hash(fragment)
    validate_fragment_sequence(retained)
    receipt = {
        "schema_version": 1,
        "migration": "superseded-report-placeholders-v1",
        "removed_section_count": len(removals),
        "removed_checkpoint_count": len(values) - len(retained),
        "replacements": changes,
        "changed": bool(removals),
        "obligation_mappings": _conservation_rows(
            obligations_before, _reference_set(retained, "obligation")
        ),
        "evidence_mappings": _conservation_rows(
            evidence_before, _reference_set(retained, "evidence")
        ),
    }
    return retained, receipt


def _reference_set(
    fragments: list[dict[str, Any]], kind: str,
) -> set[str]:
    return {
        str(link["target_ref"])
        for fragment in fragments
        for section in fragment["sections"]
        for link in section.get("links") or []
        if link.get("kind") == kind and link.get("target_ref")
    }


def _conservation_rows(
    before: set[str], after: set[str],
) -> list[dict[str, str]]:
    rows = [{
        "before_ref": ref,
        "v9_ref": ref if ref in after else "",
        "status": "preserved" if ref in after else "removed_without_receipt",
    } for ref in sorted(before)]
    if any(row["status"] != "preserved" for row in rows):
        raise ValueError("obligation or evidence reference would disappear")
    return rows


def _binding(section: dict[str, Any]) -> dict[str, str]:
    blocks = section.get("blocks") or []
    if len(blocks) != 1:
        raise ValueError("placeholder section must have exactly one block")
    binding = blocks[0].get("report_binding")
    if not isinstance(binding, dict):
        raise ValueError("placeholder section lacks report binding")
    return {
        "report_requirement_id": str(
            binding.get("report_requirement_id") or ""
        ),
        "subject_ref": str(binding.get("subject_ref") or ""),
    }


def _preserve_references(
    before: dict[str, Any], successor: dict[str, Any],
) -> None:
    existing = {
        str(link.get("target_ref") or "")
        for link in successor.get("links") or []
    }
    links = successor.setdefault("links", [])
    for link in before.get("links") or []:
        if link.get("kind") not in {"evidence", "obligation"}:
            continue
        target = str(link.get("target_ref") or "")
        if not target or target in existing:
            continue
        links.append({
            **link,
            "link_id": f"migrated-evidence-{len(links) + 1}",
            "label": _reference_label(target, str(link.get("label") or "")),
        })
        existing.add(target)
    successor["evidence_refs"] = list(dict.fromkeys([
        *(successor.get("evidence_refs") or []),
        *(before.get("evidence_refs") or []),
    ]))


def _reference_label(target: str, fallback: str) -> str:
    if target in _OBLIGATION_LABELS:
        return _OBLIGATION_LABELS[target]
    if target.startswith("data-profile:"):
        return "数据覆盖与来源画像"
    if target.startswith("candidate-registry:"):
        return "派生因子候选登记表"
    if target.startswith("validation:pyright:"):
        return "因子工作区静态检查结果"
    if target.startswith("rule:S-MECHANISM"):
        return "经济机制可证伪性研究规范"
    if target.startswith("rule:S-FIRST"):
        return "第一性原理研究规范"
    if target.startswith("unknown:sgccs-microstructure"):
        return "尚待验证的微观结构机制"
    if target.startswith("unknown:sgccs-participant"):
        return "尚待验证的市场参与者机制"
    if target.startswith("factor-worktree:"):
        factor = target.split(":")[-1]
        return f"{factor} 因子工作树版本"
    if target.startswith("proposal:sgcps-volume"):
        return "SgCPS 成交量派生研究提案"
    if target.startswith("proposal:sgccs-sgcps"):
        return "SgCCS 向 SgCPS 迁移义务提案"
    if target.startswith("proposal:sgcps-candidate"):
        return "SgCPS 派生因子候选义务提案"
    if not fallback or fallback in {"研究事实", "沿用研究证据"}:
        raise ValueError(f"research reference lacks a Chinese alias: {target}")
    return fallback
