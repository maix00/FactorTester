"""Immutable local checkpoint fragments and deterministic journal assembly."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


MAX_FRAGMENT_BYTES = 128 * 1024
MAX_JOURNAL_BYTES = 4 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FRAGMENT_FIELDS = {
    "schema_version", "language", "checkpoint_ref", "created_at", "carrier_hash",
    "narrative_hash", "section_hash", "sections", "evidence_refs", "gaps",
    "graph_ref", "instance_ref", "branch_ref", "lineage_status",
    "lineage_relation", "predecessor_checkpoint_ref", "source_branch_ref",
}


def content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def build_fragment(
    *, checkpoint_ref: str, created_at: float, carrier_hash: str,
    narrative_hash: str, sections: list[dict[str, Any]],
    evidence_refs: list[str], gaps: list[dict[str, str]],
    lineage: dict[str, str], graph_ref: str, branch_ref: str,
    edge_ref: str,
) -> dict[str, Any]:
    branch_parts = branch_ref.split(":")
    if len(branch_parts) != 3 or branch_parts[0] != "graph-branch":
        raise ValueError("research journal branch identity is invalid")
    source_branch_ref = str(lineage.get("source_branch_ref") or "")
    relation = (
        "graph_continuation"
        if edge_ref == "graph-edge:__graph_continuation__"
        else "branch_fork"
        if source_branch_ref
        else "root"
        if lineage["status"] == "root"
        else "transition"
    )
    value = {
        "schema_version": 3,
        "language": "zh-Hans",
        "checkpoint_ref": checkpoint_ref,
        "created_at": float(created_at),
        "carrier_hash": carrier_hash,
        "narrative_hash": narrative_hash,
        "graph_ref": graph_ref,
        "instance_ref": f"graph-instance:{branch_parts[1]}",
        "branch_ref": branch_ref,
        "sections": deepcopy(sections),
        "evidence_refs": list(evidence_refs),
        "gaps": deepcopy(gaps),
        "lineage_status": lineage["status"],
        "lineage_relation": relation,
        "predecessor_checkpoint_ref": lineage[
            "predecessor_checkpoint_ref"
        ],
        "source_branch_ref": source_branch_ref,
    }
    value["section_hash"] = content_hash(value)
    return validate_fragment(value)


def load_fragments(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    checkpoints = set()
    for fragment_path in sorted(path.glob("*.json")):
        if fragment_path.stat().st_size > MAX_FRAGMENT_BYTES:
            raise ValueError("research journal fragment exceeds size limit")
        try:
            value = json.loads(fragment_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("research journal fragment is unreadable") from exc
        fragment = validate_fragment(value)
        if fragment_path.stem != fragment["section_hash"]:
            raise ValueError("research journal fragment filename is invalid")
        if fragment["checkpoint_ref"] in checkpoints:
            raise ValueError("research journal contains duplicate checkpoint")
        checkpoints.add(fragment["checkpoint_ref"])
        entries.append(fragment)
    ordered = sorted(
        entries,
        key=lambda item: (item["created_at"], item["checkpoint_ref"]),
    )
    validate_fragment_sequence(ordered)
    return ordered


def merge_fragment(
    fragments: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    for item in fragments:
        if item["checkpoint_ref"] != candidate["checkpoint_ref"]:
            continue
        if item["section_hash"] != candidate["section_hash"]:
            raise ValueError("checkpoint has a conflicting narrative fragment")
        return fragments, False
    merged = sorted(
        [*fragments, candidate],
        key=lambda item: (item["created_at"], item["checkpoint_ref"]),
    )
    validate_fragment_sequence(merged)
    return merged, True


def assemble_snapshot(
    base: dict[str, Any],
    fragments: list[dict[str, Any]],
) -> dict[str, Any]:
    value = deepcopy(base)
    value["sections"] = []
    assets: dict[str, dict[str, Any]] = {}
    for fragment in fragments:
        for section in fragment["sections"]:
            projected = deepcopy(section)
            # Keep immutable prose in its physical fragment. The logical
            # projection receives explicit physical identity solely for the
            # checkpoint-to-chapter navigation join.
            projected["checkpoint_ref"] = fragment["checkpoint_ref"]
            projected["branch_ref"] = fragment["branch_ref"]
            value["sections"].append(projected)
            for block in projected.get("blocks", []):
                if block.get("kind") != "figure":
                    continue
                asset = deepcopy(block["asset"])
                asset_ref = asset["asset_ref"]
                existing = assets.get(asset_ref)
                if existing is not None and existing != asset:
                    raise ValueError("research journal figure conflicts")
                assets[asset_ref] = asset
    value["assets"] = list(assets.values())
    value["evidence_refs"] = list(dict.fromkeys(
        ref for fragment in fragments for ref in fragment["evidence_refs"]
    ))[:64]
    value["gaps"] = [
        deepcopy(gap) for fragment in fragments for gap in fragment["gaps"]
    ][-32:]
    return value


def journal_payload(
    *, work_package_id: str, journal_kind: str,
    fragments: list[dict[str, Any]],
) -> bytes:
    if journal_kind not in {"physical_branch", "work_package"}:
        raise ValueError("research journal kind is invalid")
    branch_refs = list(dict.fromkeys(
        fragment["branch_ref"] for fragment in fragments
    ))
    value = {
        "schema_version": 4,
        "language": "zh-Hans",
        "journal_kind": journal_kind,
        "work_package_id": work_package_id,
        "branch_refs": branch_refs,
        "history_status": (
            "complete" if journal_kind == "work_package" else "segment"
        ),
        "root_checkpoint_ref": fragments[0]["checkpoint_ref"],
        "checkpoints": [
            {
                "checkpoint_ref": fragment["checkpoint_ref"],
                "created_at": fragment["created_at"],
                "carrier_hash": fragment["carrier_hash"],
                "narrative_hash": fragment["narrative_hash"],
                "section_hash": fragment["section_hash"],
                "graph_ref": fragment["graph_ref"],
                "instance_ref": fragment["instance_ref"],
                "branch_ref": fragment["branch_ref"],
                "lineage_status": fragment["lineage_status"],
                "lineage_relation": fragment["lineage_relation"],
                "predecessor_checkpoint_ref": fragment[
                    "predecessor_checkpoint_ref"
                ],
                "source_branch_ref": fragment["source_branch_ref"],
                "sections": fragment["sections"],
            }
            for fragment in fragments
        ],
    }
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True,
    ).encode("utf-8") + b"\n"
    if len(payload) > MAX_JOURNAL_BYTES:
        raise ValueError("research journal exceeds size limit")
    return payload


def fragment_payload(fragment: dict[str, Any]) -> bytes:
    payload = json.dumps(
        fragment, ensure_ascii=False, indent=2, sort_keys=True,
    ).encode("utf-8") + b"\n"
    if len(payload) > MAX_FRAGMENT_BYTES:
        raise ValueError("research journal fragment exceeds size limit")
    return payload


def validate_fragment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _FRAGMENT_FIELDS:
        raise ValueError("research journal fragment fields are invalid")
    candidate = deepcopy(value)
    if candidate.get("schema_version") != 3:
        raise ValueError("research journal fragment schema is invalid")
    if candidate.get("language") != "zh-Hans":
        raise ValueError("research journal fragment language is invalid")
    if (
        not isinstance(candidate.get("checkpoint_ref"), str)
        or not candidate["checkpoint_ref"]
        or not isinstance(candidate.get("created_at"), (int, float))
        or not math.isfinite(candidate["created_at"])
        or candidate["created_at"] < 0
    ):
        raise ValueError("research journal fragment identity is invalid")
    for field in ("carrier_hash", "narrative_hash"):
        if not isinstance(candidate.get(field), str) or not _SHA256.fullmatch(
            candidate[field]
        ):
            raise ValueError("research journal fragment hash is invalid")
    graph_ref = candidate.get("graph_ref")
    instance_ref = candidate.get("instance_ref")
    branch_ref = candidate.get("branch_ref")
    if (
        not isinstance(graph_ref, str)
        or "@v" not in graph_ref
        or not isinstance(instance_ref, str)
        or not instance_ref.startswith("graph-instance:")
        or not isinstance(branch_ref, str)
        or not branch_ref.startswith(
            instance_ref.replace("graph-instance:", "graph-branch:") + ":"
        )
    ):
        raise ValueError("research journal checkpoint identity is invalid")
    if (
        not isinstance(candidate.get("sections"), list)
        or not candidate["sections"]
        or len(candidate["sections"]) > 8
        or not isinstance(candidate.get("evidence_refs"), list)
        or len(candidate["evidence_refs"]) > 64
        or not isinstance(candidate.get("gaps"), list)
        or len(candidate["gaps"]) > 32
    ):
        raise ValueError("research journal fragment content is invalid")
    lineage_status = candidate.get("lineage_status")
    lineage_relation = candidate.get("lineage_relation")
    predecessor = candidate.get("predecessor_checkpoint_ref")
    source_branch_ref = candidate.get("source_branch_ref")
    if lineage_status not in {"root", "linked"}:
        raise ValueError("research journal fragment lineage is invalid")
    if not isinstance(predecessor, str):
        raise ValueError("research journal predecessor is invalid")
    if lineage_relation not in {
        "root", "transition", "branch_fork", "graph_continuation",
    } or not isinstance(source_branch_ref, str):
        raise ValueError("research journal lineage relation is invalid")
    if lineage_status == "root" and predecessor:
        raise ValueError("root research fragment cannot have a predecessor")
    if lineage_status == "root" and (
        lineage_relation != "root" or source_branch_ref
    ):
        raise ValueError("root research fragment lineage is invalid")
    if lineage_status == "linked" and not predecessor.startswith("trace:"):
        raise ValueError("linked research fragment requires a trace predecessor")
    if lineage_relation in {"branch_fork", "graph_continuation"}:
        if not source_branch_ref.startswith("graph-branch:"):
            raise ValueError("cross-branch fragment requires a source branch")
    elif source_branch_ref:
        raise ValueError("ordinary transition cannot name a source branch")
    section_hash = candidate.pop("section_hash")
    if not isinstance(section_hash, str) or content_hash(candidate) != section_hash:
        raise ValueError("research journal fragment hash is invalid")
    candidate["section_hash"] = section_hash
    return candidate


def validate_fragment_sequence(
    fragments: list[dict[str, Any]], *, allow_external_root: bool = True,
) -> None:
    if not fragments:
        raise ValueError("research journal requires a trusted root")
    for index, fragment in enumerate(fragments):
        status = fragment["lineage_status"]
        predecessor = fragment["predecessor_checkpoint_ref"]
        if index == 0:
            is_root = status == "root" and not predecessor
            is_external = (
                allow_external_root
                and status == "linked"
                and fragment["lineage_relation"] in {
                    "branch_fork", "graph_continuation",
                }
                and bool(fragment["source_branch_ref"])
                and bool(predecessor)
            )
            if not (is_root or is_external):
                raise ValueError(
                    "research journal segment has no trusted lineage anchor"
                )
            continue
        previous = fragments[index - 1]
        if (
            status != "linked"
            or predecessor != previous["checkpoint_ref"]
            or fragment["branch_ref"] != previous["branch_ref"]
            or fragment["lineage_relation"] != "transition"
        ):
            raise ValueError(
                "research journal checkpoint lineage is incomplete"
            )


def logical_lineage(
    fragments: list[dict[str, Any]], *, checkpoint_ref: str,
) -> list[dict[str, Any]]:
    """Select and validate one root-to-head path without changing ownership."""
    by_checkpoint: dict[str, dict[str, Any]] = {}
    for fragment in fragments:
        existing = by_checkpoint.get(fragment["checkpoint_ref"])
        if existing and existing["section_hash"] != fragment["section_hash"]:
            raise ValueError("checkpoint has conflicting physical fragments")
        by_checkpoint[fragment["checkpoint_ref"]] = fragment
    path: list[dict[str, Any]] = []
    seen: set[str] = set()
    current_ref = checkpoint_ref
    while current_ref:
        if current_ref in seen:
            raise ValueError("research journal lineage contains a cycle")
        seen.add(current_ref)
        current = by_checkpoint.get(current_ref)
        if current is None:
            raise ValueError("research journal logical predecessor is missing")
        path.append(current)
        current_ref = current["predecessor_checkpoint_ref"]
    path.reverse()
    validate_logical_sequence(path)
    return path


def validate_logical_sequence(fragments: list[dict[str, Any]]) -> None:
    if not fragments:
        raise ValueError("logical research journal requires checkpoints")
    for index, fragment in enumerate(fragments):
        if index == 0:
            if fragment["lineage_status"] != "root":
                raise ValueError("logical research journal has no trusted root")
            continue
        previous = fragments[index - 1]
        if fragment["predecessor_checkpoint_ref"] != previous["checkpoint_ref"]:
            raise ValueError("logical research journal lineage is incomplete")
        cross_branch = fragment["branch_ref"] != previous["branch_ref"]
        if cross_branch:
            if (
                fragment["lineage_relation"] not in {
                    "branch_fork", "graph_continuation",
                }
                or fragment["source_branch_ref"] != previous["branch_ref"]
            ):
                raise ValueError("cross-branch journal edge is not explicit")
        elif fragment["lineage_relation"] != "transition":
            raise ValueError("same-branch checkpoint is not a transition")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
