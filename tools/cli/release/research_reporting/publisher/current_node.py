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
from ..report_items import report_fragment_hash
from .carrier import MAX_ITEMS as MAX_CARRIER_ITEMS
from .result_revision import revise_result_items
from .section_binding import item_chapter_ref, section_role
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

    (
        history, record, artifact, package_root, branch_id, fragments,
    ) = _branch_history(
        client_root=client_root, profile_id=profile_id, agent_id=agent_id,
        carrier=carrier,
    )
    revised, revision_receipt = revise_result_items(fragments, ordered)
    revision_applied = bool(revision_receipt["changed"])
    if revision_applied:
        from ..placeholder_apply import apply_migrated_package

        revision_receipt.update({
            "package_root": str(package_root),
            "branch_id": branch_id,
        })
        apply_migrated_package(
            package_root=package_root, branch_id=branch_id,
            fragments=revised, receipt=revision_receipt,
            migration_slug=(
                "result-item-revision-"
                + str(submission["fragment_hash"])[:16]
            ),
            product_group=str(carrier["product_group"]),
            current_node=str(carrier["current_node"]),
            client_root=client_root, profile_id=profile_id,
            agent_id=agent_id, retain_superseded_inputs=False,
        )
        (
            history, record, artifact, package_root, branch_id, fragments,
        ) = _branch_history(
            client_root=client_root, profile_id=profile_id,
            agent_id=agent_id, carrier=carrier,
        )
    local_ordered = [
        item for item in ordered if _item_identity(item) not in history
    ]
    if not local_ordered:
        if artifact is None:
            raise ValueError("local research record has no report artifact")
        return {
            "changed": revision_applied,
            "report_changed": revision_applied,
            "profile_changed": revision_applied,
            "checkpoint_ref": record["checkpoint_ref"],
            "artifact": artifact,
            "local_revision_receipt": (
                revision_receipt if revision_applied else None
            ),
            "report_submission": submission,
            "journal_artifact_ref": (
                "journal-artifact:sha256:" + artifact["journal_hash"]
            ),
        }
    local_projected = [
        {
            key: item[key] for key in (
                "report_requirement_id", "subject_ref",
                "content_kind", "item_hash",
            )
        }
        for item in local_ordered
    ]
    local_submission = {
        "schema_version": submission["schema_version"],
        "fragment_hash": report_fragment_hash(local_projected),
        "items": local_projected,
    }
    identity = {
        "base_checkpoint_ref": carrier.get("checkpoint_ref"),
        "fragment_hash": local_submission["fragment_hash"],
        "items": local_projected,
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
    item_refs = list(dict.fromkeys(
        str(link["target_ref"])
        for item in local_ordered
        for link in item.get("links") or []
    ))
    synthetic = _current_node_carrier(
        carrier,
        checkpoint_ref=checkpoint_ref,
        predecessor_ref=previous_ref,
        recorded_at=recorded_at,
        submission=local_submission,
        item_refs=item_refs,
    )
    result = publish_research_checkpoint(
        client_root=client_root,
        profile_id=profile_id,
        agent_id=agent_id,
        carrier=synthetic,
        narrative=_narrative(
            local_ordered,
            recorded_at=recorded_at,
            current_node=str(carrier.get("current_node") or ""),
        ),
        local_reference_allowlist=tuple(item_refs[MAX_CARRIER_ITEMS:]),
    )
    return {
        **result,
        "local_revision_receipt": (
            revision_receipt if revision_applied else None
        ),
        "report_submission": submission,
        "journal_artifact_ref": (
            "journal-artifact:sha256:" + result["artifact"]["journal_hash"]
        ),
    }


def _item_identity(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("report_requirement_id") or ""),
        str(item.get("subject_ref") or ""),
        str(item.get("item_hash") or "").removeprefix(
            "report-item:sha256:"
        ),
    )


def _branch_history(
    *, client_root: Path, profile_id: str, agent_id: str,
    carrier: dict[str, Any],
) -> tuple[
    set[tuple[str, str, str]], dict[str, Any], dict[str, Any] | None,
    Path, str, list[dict[str, Any]],
]:
    profile = LocalProfileStore(client_root).load(profile_id)
    work_package_ref = str(carrier.get("work_package_ref") or "")
    branch_ref = str(carrier.get("branch_ref") or "")
    records = [
        item for item in profile["research_records"]
        if item["graph_instance_ref"] == work_package_ref
        and item["graph_branch_ref"] == branch_ref
        and item["agent_id"] == agent_id
    ]
    if len(records) != 1:
        raise ValueError(
            "checkpoint requires exactly one matching local research record"
        )
    record = records[0]
    work_package_id = work_package_ref.removeprefix("work-package:")
    branch_id = branch_ref.split(":")[-1]
    package_root = (
        Path(profile["workspace_root"]) / "research" / work_package_id
    )
    fragments = load_fragments(
        package_root / "branches" / branch_id / "sections"
    )
    identities = {
        (
            str(binding.get("report_requirement_id") or ""),
            str(binding.get("subject_ref") or ""),
            str(binding.get("report_item_ref") or "").removeprefix(
                "report-item:sha256:"
            ),
        )
        for fragment in fragments
        for section in fragment.get("sections") or []
        for block in section.get("blocks") or []
        if isinstance((binding := block.get("report_binding")), dict)
    }
    expected_ref = (
        f"artifact:research/{work_package_id}/branches/{branch_id}/REPORT.md"
    )
    artifacts = [
        deepcopy(item) for item in record["artifacts"]
        if item.get("artifact_ref") == expected_ref
        and item.get("journal_hash")
    ]
    return (
        identities, record,
        artifacts[0] if len(artifacts) == 1 else None,
        package_root, branch_id, fragments,
    )


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
    bounded_item_refs = item_refs[:MAX_CARRIER_ITEMS]
    newly_omitted = len(item_refs) - len(bounded_item_refs)
    value["omitted_evidence_count"] += newly_omitted
    value["latest_transition"] = {
        "step_ref": checkpoint_ref,
        "edge_ref": "graph-edge:__current_node_report__",
        "from_node": value["current_node"],
        "to_node": value["current_node"],
        "created_at": recorded_at,
        "evidence_refs": bounded_item_refs,
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
    items: list[dict[str, Any]], *, recorded_at: float, current_node: str,
) -> dict[str, Any]:
    grouped: dict[str, list[list[dict[str, Any]]]] = {}
    for item in items:
        chapter_ref = item_chapter_ref(item, current_node=current_node)
        chunks = grouped.setdefault(chapter_ref, [[]])
        candidate_link_ids = {
            str(link.get("link_id") or "")
            for link in item.get("links") or []
        }
        occupied = {
            str(link.get("link_id") or "")
            for existing in chunks[-1]
            for link in existing.get("links") or []
        }
        if (
            len(chunks[-1]) >= MAX_CARRIER_ITEMS
            or occupied.intersection(candidate_link_ids)
        ):
            chunks.append([])
        chunks[-1].append(item)
    sections = []
    for chapter_index, (chapter_ref, chunks) in enumerate(grouped.items()):
        for chunk_index, chapter_items in enumerate(chunks):
            blocks = []
            links = []
            for item in chapter_items:
                content = deepcopy(item["content"])
                content["report_binding"] = deepcopy(item["report_binding"])
                blocks.append(content)
                links.extend(deepcopy(item.get("links") or []))
            stable_key = hashlib.sha256(
                json.dumps(
                    {
                        "chapter_ref": chapter_ref,
                        "items": [
                            {
                                "report_requirement_id": item[
                                    "report_requirement_id"
                                ],
                                "subject_ref": item["subject_ref"],
                            }
                            for item in chapter_items
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:16]
            sections.append({
                "section_id": f"current-node-{stable_key}",
                "title": _chapter_title(
                    chapter_items,
                    chapter_index=chapter_index,
                ),
                "chapter_ref": chapter_ref,
                "section_role": (
                    section_role(chapter_items)
                    if chunk_index == 0 else "node_report_items"
                ),
                "blocks": blocks,
                "links": links,
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


def _chapter_title(
    items: list[dict[str, Any]], *, chapter_index: int,
) -> str:
    node_actions = [
        item for item in items
        if str(item.get("report_requirement_id") or "").startswith(
            "report.node."
        )
        and str(item.get("report_requirement_id") or "").endswith(".action")
    ]
    return _report_title(
        (node_actions or items)[0],
        item_index=chapter_index,
    )
