"""Publish substantive current-node report items through the normal journal."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from ...local_profile import LocalProfileStore
from ..journal import load_fragments
from .service import publish_research_checkpoint


def publish_current_node_report_checkpoint(
    *, client_root: Path, profile_id: str, agent_id: str,
    carrier: dict[str, Any], projection: dict[str, Any],
) -> dict[str, Any]:
    """Turn entry-validate content into a real local checkpoint publication."""
    submission = projection.get("report_submission")
    local_items = projection.get("local_report_items")
    if not isinstance(submission, dict) or not isinstance(local_items, list):
        raise ValueError(
            "entry projection needs report_submission and local_report_items"
        )
    by_hash = {
        str(item.get("item_hash") or ""): item
        for item in local_items if isinstance(item, dict)
    }
    projected = submission.get("items")
    if (
        not isinstance(projected, list) or not projected
        or len(by_hash) != len(projected)
    ):
        raise ValueError("entry projection report items are incomplete")
    ordered = []
    for item in projected:
        if not isinstance(item, dict):
            raise ValueError("entry projection report item is invalid")
        full = by_hash.get(str(item.get("item_hash") or ""))
        if full is None or any(
            str(full.get(field) or "") != str(item.get(field) or "")
            for field in (
                "report_requirement_id", "subject_ref",
                "content_kind", "item_hash",
            )
        ):
            raise ValueError("local report content does not match projection")
        ordered.append(full)

    identity = {
        "base_checkpoint_ref": carrier.get("checkpoint_ref"),
        "fragment_hash": submission.get("fragment_hash"),
        "items": projected,
    }
    digest = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    checkpoint_ref = f"report-checkpoint:sha256:{digest}"
    previous_ref, recorded_at = _publication_clock(
        client_root=client_root,
        profile_id=profile_id,
        agent_id=agent_id,
        work_package_ref=str(carrier.get("work_package_ref") or ""),
        branch_ref=str(carrier.get("branch_ref") or ""),
        checkpoint_ref=checkpoint_ref,
        minimum=float(
            (carrier.get("latest_transition") or {}).get("created_at") or 0
        ),
    )
    synthetic = _current_node_carrier(
        carrier,
        checkpoint_ref=checkpoint_ref,
        predecessor_ref=previous_ref,
        recorded_at=recorded_at,
        submission=submission,
        item_refs=list(dict.fromkeys(
            str(link["target_ref"])
            for item in ordered
            for link in item.get("links") or []
        )),
    )
    result = publish_research_checkpoint(
        client_root=client_root,
        profile_id=profile_id,
        agent_id=agent_id,
        carrier=synthetic,
        narrative=_narrative(ordered, recorded_at=recorded_at),
    )
    return {
        **result,
        "report_submission": submission,
        "journal_artifact_ref": (
            "journal-artifact:sha256:" + result["artifact"]["journal_hash"]
        ),
    }


def _publication_clock(
    *, client_root: Path, profile_id: str, agent_id: str,
    work_package_ref: str, branch_ref: str, checkpoint_ref: str,
    minimum: float,
) -> tuple[str, float]:
    profile = LocalProfileStore(client_root).load(profile_id)
    matches = [
        item for item in profile["research_records"]
        if item["graph_instance_ref"] == work_package_ref
        and item["graph_branch_ref"] == branch_ref
        and item["agent_id"] == agent_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "checkpoint requires exactly one matching local research record"
        )
    record = matches[0]
    previous_ref = str(record.get("checkpoint_ref") or "")
    previous_time = float(record.get("updated_at") or 0)
    if previous_ref == checkpoint_ref:
        branch_id = branch_ref.split(":")[-1]
        work_package_id = work_package_ref.removeprefix("work-package:")
        fragments = load_fragments(
            Path(profile["workspace_root"]) / "research" / work_package_id
            / "branches" / branch_id / "sections"
        )
        matches = [
            item for item in fragments
            if item["checkpoint_ref"] == checkpoint_ref
        ]
        if len(matches) != 1:
            raise ValueError(
                "local report checkpoint head has no immutable fragment"
            )
        return matches[0]["predecessor_checkpoint_ref"], previous_time
    return previous_ref, max(time.time(), minimum, previous_time + 0.000001)


def _current_node_carrier(
    carrier: dict[str, Any], *, checkpoint_ref: str,
    predecessor_ref: str, recorded_at: float, submission: dict[str, Any],
    item_refs: list[str],
) -> dict[str, Any]:
    value = deepcopy(carrier)
    value["checkpoint_ref"] = checkpoint_ref
    value["report_lineage"] = {
        "status": "linked",
        "predecessor_checkpoint_ref": predecessor_ref or str(
            carrier["checkpoint_ref"]
        ),
    }
    base = value["latest_transition"]
    value["latest_transition"] = {
        "step_ref": checkpoint_ref,
        "edge_ref": "graph-edge:__current_node_report__",
        "from_node": value["current_node"],
        "to_node": value["current_node"],
        "created_at": recorded_at,
        "evidence_refs": item_refs,
        "trial_plan_refs": [],
        "obligation_refs": [],
        "claim_refs": [],
        "job_refs": [],
        "run_refs": [],
        "delta_refs": [],
        "obligation_changes": [],
        "claim_changes": [],
        "report_fragment_ref": (
            "report-fragment:sha256:" + submission["fragment_hash"]
        ),
        "report_items": [
            {
                "report_item_ref": (
                    "report-item:sha256:" + item["item_hash"]
                ),
                "report_requirement_id": item["report_requirement_id"],
                "subject_ref": item["subject_ref"],
                "content_kind": item["content_kind"],
            }
            for item in submission["items"]
        ],
    }
    value["job_refs"] = list(base.get("job_refs") or value["job_refs"])
    value["run_refs"] = list(base.get("run_refs") or value["run_refs"])
    return value


def _narrative(
    items: list[dict[str, Any]], *, recorded_at: float,
) -> dict[str, Any]:
    sections = []
    for item_index, item in enumerate(items):
        content = deepcopy(item["content"])
        content["report_binding"] = deepcopy(item["report_binding"])
        stable_key = hashlib.sha256(
            json.dumps(
                {
                    "report_requirement_id": item["report_requirement_id"],
                    "subject_ref": item["subject_ref"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        sections.append({
            "section_id": f"current-node-{stable_key}",
            "title": _report_title(item, item_index=item_index),
            "blocks": [content],
            "links": deepcopy(item.get("links") or []),
        })
    return {
        "schema_version": 3,
        "language": "zh-Hans",
        "title": "当前节点研究记录",
        "research_occurred_at": recorded_at,
        "time_basis": "transition",
        "time_source_refs": [],
        "sections": sections,
    }


def _report_title(item: dict[str, Any], *, item_index: int) -> str:
    """Use local Graph presentation text without changing report identity."""
    title = str(item.get("title_zh") or "").strip()
    if title:
        return title
    content = item.get("content")
    rows = content.get("rows") if isinstance(content, dict) else None
    first = str((rows or [{}])[0].get("text") or "").strip()
    if first:
        for separator in ("。", "；", "："):
            first = first.split(separator, 1)[0]
        if len(first) > 44:
            first = first[:43].rstrip() + "…"
        if first:
            return first
    return f"当前节点研究记录 {item_index + 1}"
