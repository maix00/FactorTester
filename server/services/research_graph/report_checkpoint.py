"""Bounded, source-free checkpoint carriers for local report publishing."""

from __future__ import annotations

import math
import ntpath
import posixpath
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

import orjson


MAX_REPORT_CHECKPOINT_BYTES = 64 * 1024
MAX_REF_BYTES = 256
MAX_CARRIER_ITEMS = 16
_REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\\\s]{1,255}$")


def report_checkpoint_projection(
    *,
    instance_id: str,
    work_package_id: str,
    branch_id: str,
    workspace_id: str,
    graph_id: str,
    graph_version: int,
    title: str,
    product_group: str,
    current_node: str,
    status: str,
    trace_id: str,
    edge_id: str,
    from_node: str,
    created_at: float,
    checkpoint: Any,
    trace_evidence: dict[str, Any],
    evidence_refs: Any,
    omitted_evidence_count: int = 0,
) -> dict[str, Any] | None:
    """Build the report carrier from values already held by one operation."""
    raw_checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
    cycle = cycle_projection(raw_checkpoint)
    contract_hash = safe_hash(raw_checkpoint.get("contract_hash"))
    methodology_hash = safe_hash(raw_checkpoint.get("methodology_hash"))
    if not cycle["projection_ref"] or not contract_hash or not methodology_hash:
        return None
    if (
        type(omitted_evidence_count) is not int
        or omitted_evidence_count < 0
        or omitted_evidence_count > 2_147_483_647
    ):
        raise ValueError("omitted_evidence_count must be a non-negative integer")
    if (
        not isinstance(created_at, (int, float))
        or not math.isfinite(created_at)
        or created_at < 0
    ):
        raise ValueError(
            "report checkpoint created_at must be finite and non-negative"
        )
    bounded_evidence_refs, newly_omitted = safe_refs_with_omissions(
        evidence_refs
    )
    total_omitted = omitted_evidence_count + newly_omitted
    if total_omitted > 2_147_483_647:
        raise ValueError("omitted_evidence_count exceeds supported range")
    identities = {
        "instance_id": instance_id,
        "work_package_id": work_package_id,
        "branch_id": branch_id,
        "workspace_id": workspace_id,
        "graph_id": graph_id,
        "trace_id": trace_id,
        "edge_id": edge_id,
    }
    invalid = [key for key, value in identities.items() if not safe_identifier(value)]
    if invalid:
        raise ValueError("report checkpoint identity is invalid: " + ", ".join(invalid))
    step = transition_step_projection(
        trace_id=trace_id,
        edge_id=edge_id,
        from_node=from_node,
        to_node=current_node,
        created_at=created_at,
        evidence=trace_evidence,
    )
    value = {
        "schema_version": 2,
        "workspace_ref": f"workspace:{workspace_id}",
        "work_package_ref": f"work-package:{work_package_id}",
        "branch_ref": f"graph-branch:{instance_id}:{branch_id}",
        "graph_ref": f"{graph_id}@v{int(graph_version)}",
        "checkpoint_ref": f"trace:{trace_id}",
        "research_cycle_ref": cycle["projection_ref"],
        "title": bounded_text(title, 256),
        "product_group": bounded_text(product_group, 128),
        "current_node": bounded_text(current_node, 128),
        "status": bounded_text(status, 48),
        "decision_contract_hash": contract_hash,
        "methodology_hash": methodology_hash,
        "trial_plan_hash": safe_hash(raw_checkpoint.get("trial_plan_hash")),
        "evidence_refs": bounded_evidence_refs,
        "omitted_evidence_count": total_omitted,
        "job_refs": step["job_refs"],
        "run_refs": step["run_refs"],
        "claims": cycle["claims"][:MAX_CARRIER_ITEMS],
        "open_obligations": [
            item for item in cycle["obligations"]
            if item["status"] in {"open", "reopened"}
        ][:MAX_CARRIER_ITEMS],
        "closure": cycle["closure"],
        "report_lineage": report_lineage_from_trace(
            trace_evidence=trace_evidence,
            edge_id=edge_id,
        ),
        "latest_transition": step,
    }
    encoded = orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    if len(encoded) > MAX_REPORT_CHECKPOINT_BYTES:
        raise ValueError("report checkpoint exceeds bounded carrier size")
    return value


def report_lineage_from_trace(
    *, trace_evidence: dict[str, Any], edge_id: str,
) -> dict[str, str]:
    explicit = trace_evidence.get("report_lineage")
    if isinstance(explicit, dict):
        return report_lineage_projection(explicit)
    if edge_id == "__graph_continuation__":
        continuation = trace_evidence.get("graph_continuation")
        if isinstance(continuation, dict):
            source_trace_id = str(continuation.get("source_trace_id") or "")
            source_instance_id = str(
                continuation.get("source_instance_id") or ""
            )
            source_branch_id = str(
                continuation.get("source_branch_id") or ""
            )
            if all(safe_identifier(item) for item in (
                source_trace_id, source_instance_id, source_branch_id,
            )):
                return {
                    "status": "linked",
                    "predecessor_checkpoint_ref": f"trace:{source_trace_id}",
                    "source_branch_ref": (
                        "graph-branch:"
                        f"{source_instance_id}:{source_branch_id}"
                    ),
                }
    return report_lineage_projection(explicit)


def report_lineage_projection(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {
            "status": "history_incomplete",
            "predecessor_checkpoint_ref": "",
        }
    status = str(value.get("status") or "")
    predecessor = str(value.get("predecessor_checkpoint_ref") or "")
    source_branch_ref = str(value.get("source_branch_ref") or "")
    if status == "root" and not predecessor:
        return {"status": status, "predecessor_checkpoint_ref": ""}
    if (
        status == "linked"
        and predecessor.startswith("trace:")
        and safe_identifier(predecessor.removeprefix("trace:"))
    ):
        result = {
            "status": status,
            "predecessor_checkpoint_ref": predecessor,
        }
        if source_branch_ref.startswith("graph-branch:"):
            result["source_branch_ref"] = source_branch_ref
        return result
    return {
        "status": "history_incomplete",
        "predecessor_checkpoint_ref": "",
    }


def transition_step_projection(
    *,
    trace_id: str,
    edge_id: str,
    from_node: str,
    to_node: str,
    created_at: float,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    from .report_object_presentations import (
        evidence_presentations,
        obligation_presentations,
    )
    from .branch.trace_compaction import entry_resolution_indexes
    from .branch.entry_resolution.event_validation import (
        canonical_entry_resolution_event,
    )

    obligation_changes, claim_changes = research_cycle_deltas(evidence)
    obligation_refs = unique_refs([
        *(f"obligation:{item['obligation_id']}" for item in obligation_changes),
        *named_refs(evidence, "obligation_id", prefix="obligation:"),
    ])[:MAX_CARRIER_ITEMS]
    claim_refs = unique_refs([
        *(f"claim:{item['claim_id']}" for item in claim_changes),
        *named_refs(evidence, "claim_id", prefix="claim:"),
    ])[:MAX_CARRIER_ITEMS]
    delta_refs = [
        f"delta:{trace_id}:obligation:{item['obligation_id']}"
        for item in obligation_changes
    ] + [
        f"delta:{trace_id}:claim:{item['claim_id']}"
        for item in claim_changes
    ]
    entry_resolution = evidence.get("entry_resolution_delta")
    entry_event = evidence.get("entry_resolution_event")
    report_submission = evidence.get("report_submission")
    value = {
        "step_ref": f"trace:{trace_id}",
        "edge_ref": f"graph-edge:{edge_id}",
        "from_node": bounded_text(from_node, 128),
        "to_node": bounded_text(to_node, 128),
        "created_at": float(created_at),
        "evidence_refs": safe_refs(evidence.get("evidence_refs") or []),
        "trial_plan_refs": trial_plan_refs(evidence),
        "obligation_refs": obligation_refs,
        "claim_refs": claim_refs,
        "job_refs": named_refs(evidence, "job_id", prefix="job:"),
        "run_refs": named_refs(evidence, "run_id", prefix="run:"),
        "delta_refs": delta_refs[:MAX_CARRIER_ITEMS],
        "obligation_changes": obligation_changes,
        "claim_changes": claim_changes,
        "obligation_presentations": obligation_presentations(evidence),
        "evidence_presentations": evidence_presentations(evidence),
    }
    report_fragment_hash = (
        safe_hash(report_submission.get("fragment_hash"))
        if isinstance(report_submission, dict) else ""
    )
    if report_fragment_hash:
        value["report_fragment_ref"] = (
            f"report-fragment:sha256:{report_fragment_hash}"
        )
        value["report_items"] = [
            {
                "report_item_ref": (
                    "report-item:sha256:"
                    f"{safe_hash(item.get('item_hash'))}"
                ),
                "report_requirement_id": bounded_text(
                    item.get("report_requirement_id"), 256,
                ),
                "subject_ref": bounded_text(item.get("subject_ref"), 256),
                "content_kind": bounded_text(item.get("content_kind"), 32),
            }
            for item in report_submission.get("items") or []
            if isinstance(item, dict)
            and safe_hash(item.get("item_hash"))
        ][:MAX_CARRIER_ITEMS]
    if isinstance(entry_resolution, dict):
        indexes = entry_resolution_indexes(entry_resolution)
        value["entry_resolution"] = {
            key: (
                indexes[key]
                if key in indexes
                else entry_resolution.get(key)
            )
            for key in (
                "reason",
                "assessed_requirement_ids",
                "reused_requirement_ids",
                "reference_only_requirement_ids",
                "unresolved_requirement_ids",
                "items",
                "resume_node",
            )
        }
    if isinstance(entry_event, dict):
        value["entry_resolution_event"] = (
            canonical_entry_resolution_event(entry_event)
        )
    return value


def cycle_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "protocol_status": "uninitialized",
            "projection_ref": None,
            "claims": [],
            "obligations": [],
            "closure": None,
        }
    claims = []
    for item in value.get("claims") or []:
        if not isinstance(item, dict):
            continue
        claim_id = safe_identifier(item.get("claim_id"))
        if claim_id:
            claims.append({
                "claim_ref": f"claim:{claim_id}",
                "claim_type": bounded_text(item.get("claim_type"), 80),
                "evidence_state": bounded_text(item.get("evidence_state"), 48),
            })
    obligations = []
    for item in value.get("obligations") or []:
        if not isinstance(item, dict):
            continue
        obligation_id = safe_identifier(item.get("obligation_id"))
        if obligation_id:
            obligations.append({
                "obligation_ref": f"obligation:{obligation_id}",
                "status": bounded_text(item.get("status"), 48),
                "materiality": bounded_text(item.get("materiality"), 80),
                "question_summary": bounded_text(item.get("epistemic_question"), 240),
            })
    projection_hash = safe_hash(value.get("projection_hash"))
    closure = value.get("closure")
    closure_projection = None
    if isinstance(closure, dict):
        proposal_id = safe_identifier(closure.get("proposal_id"))
        disposition = bounded_text(closure.get("disposition"), 80)
        if proposal_id and disposition:
            closure_projection = {
                "proposal_ref": f"proposal:{proposal_id}",
                "disposition": disposition,
            }
    return {
        "protocol_status": "current",
        "projection_ref": (
            f"research-cycle:sha256:{projection_hash}" if projection_hash else None
        ),
        "claims": claims,
        "obligations": obligations,
        "closure": closure_projection,
    }


def research_cycle_deltas(
    evidence: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    cycle = evidence.get("research_cycle")
    events = cycle.get("events") if isinstance(cycle, dict) else []
    receipts = (
        cycle.get("event_receipts")
        if isinstance(cycle, dict)
        else []
    )
    obligation_changes: list[dict[str, Any]] = []
    claim_changes: list[dict[str, str]] = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        proposal = event.get("proposal")
        if not isinstance(proposal, dict):
            continue
        for item in proposal.get("obligation_delta") or []:
            if not isinstance(item, dict):
                continue
            identifier = safe_identifier(item.get("obligation_id"))
            if identifier:
                change: dict[str, Any] = {
                    "obligation_id": identifier,
                    "from_state": bounded_text(item.get("from_state"), 48),
                    "to_state": bounded_text(item.get("to_state"), 48),
                }
                _project_requirement_ref_delta(item, change)
                obligation_changes.append(change)
        for item in proposal.get("claim_evidence_delta") or []:
            if not isinstance(item, dict):
                continue
            identifier = safe_identifier(item.get("claim_id"))
            if identifier:
                claim_changes.append({
                    "claim_id": identifier,
                    "from_state": bounded_text(item.get("from_state"), 48),
                    "to_state": bounded_text(item.get("to_state"), 48),
                })
    for receipt in receipts if isinstance(receipts, list) else []:
        if not isinstance(receipt, dict):
            continue
        obligation_changes.extend(
            _compact_cycle_deltas(
                receipt.get("obligation_deltas"),
                identifier="obligation_id",
            )
        )
        claim_changes.extend(
            _compact_cycle_deltas(
                receipt.get("claim_deltas"),
                identifier="claim_id",
            )
        )
    return (
        obligation_changes[:MAX_CARRIER_ITEMS],
        claim_changes[:MAX_CARRIER_ITEMS],
    )


def _compact_cycle_deltas(
    value: Any,
    *,
    identifier: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        object_id = safe_identifier(item.get(identifier))
        if object_id:
            change: dict[str, Any] = {
                identifier: object_id,
                "from_state": bounded_text(item.get("from_state"), 48),
                "to_state": bounded_text(item.get("to_state"), 48),
            }
            if identifier == "obligation_id":
                _project_requirement_ref_delta(item, change)
            result.append(change)
    return result


def _project_requirement_ref_delta(
    source: dict[str, Any],
    target: dict[str, Any],
) -> None:
    for key in ("from_requirement_refs", "to_requirement_refs"):
        refs = source.get(key)
        if isinstance(refs, list):
            target[key] = [
                bounded_text(item, 160)
                for item in refs
                if isinstance(item, str) and item
            ]


def trial_plan_refs(evidence: dict[str, Any]) -> list[str]:
    values: list[str] = []
    plan = evidence.get("trial_plan")
    if isinstance(plan, dict):
        plan_id = safe_identifier(plan.get("trial_plan_id"))
        if plan_id:
            values.append(f"trial-plan:{plan_id}")
    for hash_value in named_texts(evidence, "trial_plan_hash"):
        normalized = safe_hash(hash_value)
        if normalized:
            values.append(f"trial-plan:sha256:{normalized}")
    return unique_refs(values)[:MAX_CARRIER_ITEMS]


def named_refs(value: Any, key: str, *, prefix: str) -> list[str]:
    return unique_refs(
        f"{prefix}{item}"
        for item in named_texts(value, key)
        if safe_identifier(item)
    )[:MAX_CARRIER_ITEMS]


def named_texts(value: Any, key: str) -> list[str]:
    found: list[str] = []

    def visit(item: Any) -> None:
        if len(found) >= 50:
            return
        if isinstance(item, dict):
            for child_key, child in item.items():
                if child_key == key and isinstance(child, str):
                    safe = safe_identifier(child)
                    if safe:
                        found.append(safe)
                elif isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def safe_refs(values: Any) -> list[str]:
    return safe_refs_with_omissions(values)[0]


def safe_refs_with_omissions(values: Any) -> tuple[list[str], int]:
    if not isinstance(values, list):
        return [], 0
    result: list[str] = []
    omitted = 0
    for value in values:
        reference = stable_reference(value)
        if not reference:
            omitted += 1
            continue
        if reference in result:
            continue
        if len(result) >= MAX_CARRIER_ITEMS:
            omitted += 1
            continue
        result.append(reference)
    return result, omitted


def stable_reference(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value.encode()) > MAX_REF_BYTES
        or not _REFERENCE.fullmatch(value)
    ):
        return ""
    parsed = urlsplit(value)
    network_reference = parsed.scheme.lower() in {"http", "https"}
    logical_absolute_path = (
        not parsed.netloc
        and (
            parsed.path.startswith(("/", "~"))
            or ntpath.isabs(parsed.path)
            or bool(ntpath.splitdrive(parsed.path)[0])
        )
    )
    if (
        parsed.scheme.lower() == "file"
        or (bool(parsed.netloc) and not network_reference)
        or (network_reference and not parsed.netloc)
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or logical_absolute_path
        or posixpath.isabs(value)
        or ntpath.isabs(value)
        or "\\" in value
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        return ""
    return value


def unique_refs(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def safe_identifier(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    if (
        not normalized
        or len(normalized.encode()) > 160
        or any(character not in (
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
        ) for character in normalized)
    ):
        return ""
    return normalized


def safe_hash(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        return ""
    return normalized


def bounded_text(value: Any, max_bytes: int) -> str:
    text = str(value or "")
    raw = text.encode()
    if len(raw) <= max_bytes:
        return text
    return raw[: max_bytes - 3].decode(errors="ignore") + "..."
