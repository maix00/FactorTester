"""One-shot repair of historical display metadata.

This module deliberately changes canonical historical objects.  It is not a
runtime compatibility layer: callers must retain the returned receipt and
replace every reference named by ``reference_map`` atomically.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_proposal,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from .journal import content_hash, fragment_payload, load_fragments


SGCCS_OBLIGATION_QUESTIONS = {
    "sgccs-semantic-causal-role":
        "SgCCS 的经济语义与因果时序是否成立，并适合作为辅助或条件信号？",
    "sgccs-data-coverage-feasibility":
        "现有点时数据是否覆盖拟议试验的标的、频率、字段、时间范围与最终留出期？",
    "sgccs-incremental-value":
        "相对冻结的主因子，SgCCS 是否提供有边界且可复现的增量价值？",
    "sgccs-performance-transportability":
        "该效果能否跨时间、市场环境与标的迁移，并在最终留出期保持方向一致？",
    "sgccs-cost-execution-survival":
        "扣除手续费、滑点并考虑执行约束后，该信号是否仍然有效？",
}


def migrate_trace_evidence_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Repair exact historical rows and return an auditable hash receipt."""
    values = [deepcopy(item) for item in rows]
    reference_map: dict[str, str] = {}
    object_changes: list[dict[str, str]] = []

    for row in values:
        for envelope in _envelopes(row["evidence"]):
            old_hash = str(envelope["envelope_hash"])
            candidate = deepcopy(envelope)
            candidate.pop("envelope_hash", None)
            title, claim = _evidence_presentation(candidate)
            candidate["title"] = title
            candidate["claim_summary"] = claim
            migrated = validate_agent_evidence_envelope(candidate)
            envelope.clear()
            envelope.update(migrated)
            new_hash = migrated["envelope_hash"]
            reference_map[old_hash] = new_hash
            reference_map[f"evidence:{old_hash}"] = f"evidence:{new_hash}"
            object_changes.append({
                "kind": "evidence_envelope",
                "stable_id": str(migrated["envelope_id"]),
                "before_hash": old_hash,
                "after_hash": new_hash,
            })

    values = [_replace_refs(item, reference_map) for item in values]
    projection_hashes: dict[str, str] = {}
    for row in values:
        evidence = row["evidence"]
        _repair_obligation_questions(evidence)
        cycle = evidence.get("research_cycle")
        checkpoint = evidence.get("research_cycle_checkpoint")
        if not isinstance(cycle, dict) or not isinstance(checkpoint, dict):
            continue
        _rehash_cycle_events(cycle)
        old_projection = str(checkpoint.get("projection_hash") or "")
        checkpoint.pop("projection_hash", None)
        migrated_checkpoint = validate_research_cycle_checkpoint(checkpoint)
        evidence["research_cycle_checkpoint"] = migrated_checkpoint
        trace_ref = f"trace:{row['trace_id']}"
        projection_hashes[trace_ref] = migrated_checkpoint["projection_hash"]
        parent = str(cycle.get("parent_trace_ref") or "")
        cycle["checkpoint_before_hash"] = (
            projection_hashes[parent] if parent
            else migrated_checkpoint["projection_hash"]
        )
        object_changes.append({
            "kind": "research_cycle_checkpoint",
            "stable_id": trace_ref,
            "before_hash": old_projection,
            "after_hash": migrated_checkpoint["projection_hash"],
        })

    receipt = {
        "schema_version": 1,
        "migration": "historical-presentation-metadata-v1",
        "reference_map": dict(sorted(reference_map.items())),
        "objects": object_changes,
        "input_hash": json_hash(rows),
        "output_hash": json_hash(values),
    }
    return values, receipt


def _rehash_cycle_events(cycle: dict[str, Any]) -> None:
    proposal_map: dict[str, str] = {}
    for event in cycle.get("events") or []:
        if not isinstance(event, dict):
            continue
        proposal = event.get("proposal")
        if isinstance(proposal, dict):
            old = str(proposal.get("proposal_hash") or "")
            candidate = deepcopy(proposal)
            candidate.pop("proposal_hash", None)
            migrated = validate_adjudication_proposal(candidate)
            event["proposal"] = migrated
            proposal_map[old] = migrated["proposal_hash"]
        decision = event.get("decision")
        if isinstance(decision, dict):
            old = str(decision.get("proposal_hash") or "")
            if old in proposal_map:
                decision["proposal_hash"] = proposal_map[old]


def migrate_work_package_database(
    *, database_path: Path, work_package_id: str, receipt_path: Path,
) -> dict[str, Any]:
    """Atomically migrate one Work Package and persist its receipt."""
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT t.trace_id, t.evidence_json
            FROM research_graph_trace t
            JOIN research_graph_instances i ON i.instance_id=t.instance_id
            WHERE i.work_package_id=?
            ORDER BY t.created_at, t.trace_id
            """,
            (work_package_id,),
        ).fetchall()
        source = [{
            "trace_id": str(row["trace_id"]),
            "evidence": json.loads(str(row["evidence_json"])),
        } for row in rows]
        migrated, receipt = migrate_trace_evidence_rows(source)
        for item in migrated:
            conn.execute(
                "UPDATE research_graph_trace SET evidence_json=? "
                "WHERE trace_id=?",
                (
                    json.dumps(
                        item["evidence"], ensure_ascii=False,
                        sort_keys=True, separators=(",", ":"),
                    ),
                    item["trace_id"],
                ),
            )
        mapping = receipt["reference_map"]
        branch_rows = conn.execute(
            """
            SELECT b.branch_id, b.evidence_refs_json
            FROM research_graph_branches b
            JOIN research_graph_instances i ON i.instance_id=b.instance_id
            WHERE i.work_package_id=?
            """,
            (work_package_id,),
        ).fetchall()
        for row in branch_rows:
            refs = _replace_refs(
                json.loads(str(row["evidence_refs_json"])), mapping,
            )
            conn.execute(
                "UPDATE research_graph_branches SET evidence_refs_json=? "
                "WHERE branch_id=?",
                (
                    json.dumps(refs, ensure_ascii=False, separators=(",", ":")),
                    str(row["branch_id"]),
                ),
            )
        conn.commit()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return receipt


def migrate_report_fragments(
    *, package_root: Path, receipt: dict[str, Any],
    evidence_titles: dict[str, str],
) -> list[dict[str, str]]:
    """Rewrite immutable source fragments with migrated refs and new hashes."""
    mapping = receipt["reference_map"]
    changes: list[dict[str, str]] = []
    for sections_root in sorted(package_root.glob("branches/*/sections")):
        for fragment in load_fragments(sections_root):
            before = fragment["section_hash"]
            candidate = _replace_refs(fragment, mapping)
            for section in candidate["sections"]:
                for link in section.get("links", []):
                    target = str(link.get("target_ref") or "")
                    if target in evidence_titles:
                        link["label"] = evidence_titles[target]
                    elif target.startswith("obligation:"):
                        identifier = target.removeprefix("obligation:")
                        if identifier in SGCCS_OBLIGATION_QUESTIONS:
                            link["label"] = SGCCS_OBLIGATION_QUESTIONS[
                                identifier
                            ]
            candidate.pop("section_hash", None)
            candidate["section_hash"] = content_hash(candidate)
            after = candidate["section_hash"]
            if after == before:
                continue
            target = sections_root / f"{after}.json"
            target.write_bytes(fragment_payload(candidate))
            (sections_root / f"{before}.json").unlink()
            changes.append({
                "branch_id": sections_root.parent.name,
                "checkpoint_ref": candidate["checkpoint_ref"],
                "before_hash": before,
                "after_hash": after,
            })
    return changes


_FACTOR_META_PARAMETER = re.compile(r"(?<!`)\$(Rev|F)(?!`)")


def migrate_factor_meta_parameter_markup(
    *, package_root: Path,
) -> tuple[list[dict[str, Any]], int]:
    """Render FactorTester meta-parameters as Markdown code, idempotently."""
    changes: list[dict[str, Any]] = []
    replacement_count = 0
    for sections_root in sorted(package_root.glob("branches/*/sections")):
        for fragment in load_fragments(sections_root):
            candidate = deepcopy(fragment)
            migrated_sections, count = _markup_value(candidate["sections"])
            if not count:
                continue
            candidate["sections"] = migrated_sections
            old_section_hash = candidate.pop("section_hash")
            old_narrative_hash = candidate["narrative_hash"]
            candidate["narrative_hash"] = content_hash({
                "migration": "factor-meta-parameter-markup-v1",
                "prior_narrative_hash": old_narrative_hash,
                "sections": migrated_sections,
            })
            candidate["section_hash"] = content_hash(candidate)
            target = sections_root / f"{candidate['section_hash']}.json"
            target.write_bytes(fragment_payload(candidate))
            (sections_root / f"{old_section_hash}.json").unlink()
            changes.append({
                "branch_id": sections_root.parent.name,
                "checkpoint_ref": candidate["checkpoint_ref"],
                "replacement_count": count,
                "before_narrative_hash": old_narrative_hash,
                "after_narrative_hash": candidate["narrative_hash"],
                "before_section_hash": old_section_hash,
                "after_section_hash": candidate["section_hash"],
            })
            replacement_count += count
    return changes, replacement_count


def migrate_run_spec_preview_links(
    *, package_root: Path,
) -> list[dict[str, str]]:
    """Give unsubmitted RunSpec previews their truthful local object kind.

    A preview hash is not a persisted ResearchRun and must not be presented as
    Evidence.  Submitted runs are reported separately as ``run:<run_id>`` and
    lazily expose their canonical ``run_spec_json``.
    """
    changes: list[dict[str, str]] = []
    for sections_root in sorted(package_root.glob("branches/*/sections")):
        for fragment in load_fragments(sections_root):
            candidate = deepcopy(fragment)
            replacements = 0
            for section in candidate["sections"]:
                for link in section.get("links", []):
                    target = str(link.get("target_ref") or "")
                    if (
                        target.startswith("runspec:")
                        and link.get("kind") == "evidence"
                    ):
                        link["kind"] = "run_spec"
                        label = str(link.get("label") or "").strip()
                        if label and "预览" not in label:
                            link["label"] = f"{label} 预览"
                        replacements += 1
            if not replacements:
                continue
            before = str(candidate.pop("section_hash"))
            candidate["section_hash"] = content_hash(candidate)
            after = candidate["section_hash"]
            target = sections_root / f"{after}.json"
            target.write_bytes(fragment_payload(candidate))
            (sections_root / f"{before}.json").unlink()
            changes.append({
                "branch_id": sections_root.parent.name,
                "checkpoint_ref": candidate["checkpoint_ref"],
                "before_hash": before,
                "after_hash": after,
                "replacement_count": str(replacements),
            })
    return changes


def _markup_value(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        return _FACTOR_META_PARAMETER.sub(r"`$\1`", value), len(
            _FACTOR_META_PARAMETER.findall(value)
        )
    if isinstance(value, list):
        result, count = [], 0
        for item in value:
            migrated, item_count = _markup_value(item)
            result.append(migrated)
            count += item_count
        return result, count
    if isinstance(value, dict):
        result, count = {}, 0
        for key, item in value.items():
            migrated, item_count = _markup_value(item)
            result[key] = migrated
            count += item_count
        return result, count
    return value, 0


def _repair_obligation_questions(value: Any) -> None:
    if isinstance(value, dict):
        obligation_id = value.get("obligation_id")
        if obligation_id in SGCCS_OBLIGATION_QUESTIONS:
            value["epistemic_question"] = SGCCS_OBLIGATION_QUESTIONS[
                obligation_id
            ]
        for child in value.values():
            _repair_obligation_questions(child)
    elif isinstance(value, list):
        for child in value:
            _repair_obligation_questions(child)


def _envelopes(value: Any):
    if isinstance(value, dict):
        if (
            value.get("schema_version") == 2
            and isinstance(value.get("envelope_hash"), str)
            and isinstance(value.get("evidence_kind"), str)
        ):
            yield value
            return
        for child in value.values():
            yield from _envelopes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _envelopes(child)


def _replace_refs(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_replace_refs(item, mapping) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_refs(item, mapping)
            for key, item in value.items()
        }
    return value


def _evidence_presentation(envelope: dict[str, Any]) -> tuple[str, str]:
    kind = envelope["evidence_kind"]
    facts = envelope.get("facts") or {}
    if kind == "hypothesis_semantics":
        return (
            "SgCCS 初始研究假设与边界",
            "记录重新审查 SgCCS 辅助或条件信号价值时采用的初始假设、冲突与限制。",
        )
    if kind == "factor_semantics":
        return (
            "SgCCS 因子版本与语义冻结清单",
            "证明本次语义审查绑定了指定因子家族、配置版本和冻结的因子修订集合。",
        )
    if kind == "data_availability":
        products = [
            str(item.get("product")) for item in facts.get("product_status", [])
            if isinstance(item, dict) and item.get("product")
        ]
        scope = "、".join(products) if products else "授权产品"
        return (
            f"{scope} 的历史数据覆盖清单",
            "说明拟议试验所需产品在当时的数据快照中是否可用及其查询范围。",
        )
    if kind == "data_contract":
        status = str(facts.get("integrity_status") or "待核验")
        return (
            "本地数据来源与点时完整性证明",
            f"记录数据来源、可重放性及点时完整性边界；当时完整性状态为 {status}。",
        )
    return (
        "历史研究证据",
        "记录该历史检查点使用的事实、适用范围与限制。",
    )
