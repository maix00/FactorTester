"""Build the bounded ReportSnapshot defined by ADR-040."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any


def report_snapshot(
    carrier: dict[str, Any], *, narrative: dict[str, Any],
    report_title: str,
    workspace_id: str, work_package_id: str,
    branch_id: str, factor_family_versions: list[str],
    scope_identity: dict[str, Any],
) -> dict[str, Any]:
    transition = carrier["latest_transition"]
    checkpoint_refs = _unique([
        scope_identity["scope_ref"],
        carrier["research_cycle_ref"], carrier["checkpoint_ref"],
        *carrier["evidence_refs"], *carrier["job_refs"], *carrier["run_refs"],
        *transition["evidence_refs"], *transition["job_refs"],
        *transition["run_refs"],
    ])
    checkpoint_key = hashlib.sha256(
        carrier["checkpoint_ref"].encode("utf-8")
    ).hexdigest()[:16]
    sections = []
    assets: dict[str, dict[str, Any]] = {}
    for section in narrative["sections"]:
        links = list(section["links"])
        links.append({
            "link_id": f"checkpoint-{checkpoint_key}",
            "kind": "checkpoint",
            "target_ref": carrier["checkpoint_ref"],
        })
        projected = {
            "section_id": f"{checkpoint_key}-{section['section_id']}",
            "title": section["title"],
            "evidence_refs": [
                item["target_ref"] for item in links
                if item["kind"] == "evidence"
            ],
            "asset_refs": [],
            "links": links,
            "created_at": transition["created_at"],
        }
        if "chapter_ref" in section:
            projected["chapter_ref"] = section["chapter_ref"]
            projected["section_role"] = section["section_role"]
        if narrative["schema_version"] in {2, 3}:
            projected["body"] = section.get("body", "")
            projected["blocks"] = deepcopy(section["blocks"])
            for block in section["blocks"]:
                if block["kind"] != "figure":
                    continue
                asset = deepcopy(block["asset"])
                asset_ref = asset["asset_ref"]
                existing = assets.get(asset_ref)
                if existing is not None and existing != asset:
                    raise ValueError("report figure descriptor conflicts")
                assets[asset_ref] = asset
                projected["asset_refs"].append(asset_ref)
        else:
            projected["body"] = section["body"]
        if narrative["schema_version"] == 3:
            projected.update({
                "research_occurred_at": narrative["research_occurred_at"],
                "time_basis": narrative["time_basis"],
                "time_source_refs": list(narrative["time_source_refs"]),
            })
        sections.append(projected)
    return {
        "schema_version": 1,
        "workspace_id": workspace_id,
        "work_package_id": work_package_id,
        "branch_id": branch_id,
        "title": report_title,
        "status": carrier["status"],
        "product_group": carrier["product_group"],
        "current_node": carrier["current_node"],
        "graph_ref": carrier["graph_ref"],
        "methodology_hash": carrier["methodology_hash"],
        "decision_contract_hash": carrier["decision_contract_hash"],
        "trial_plan_hash": carrier["trial_plan_hash"],
        "factor_family_versions": list(factor_family_versions),
        "evidence_refs": checkpoint_refs,
        "sections": sections,
        "assets": list(assets.values()),
        "gaps": ([{
            "gap_ref": "report-gap:omitted-evidence",
            "reason": (
                "受 checkpoint 载荷上限约束，有 "
                f"{carrier['omitted_evidence_count']} 条证据引用未随本次载荷提供。"
            ),
        }] if carrier["omitted_evidence_count"] else []),
    }


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))[:64]
