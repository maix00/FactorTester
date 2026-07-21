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
}


def content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def build_fragment(
    *, checkpoint_ref: str, created_at: float, carrier_hash: str,
    narrative_hash: str, sections: list[dict[str, Any]],
    evidence_refs: list[str], gaps: list[dict[str, str]],
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "language": "zh-Hans",
        "checkpoint_ref": checkpoint_ref,
        "created_at": float(created_at),
        "carrier_hash": carrier_hash,
        "narrative_hash": narrative_hash,
        "sections": deepcopy(sections),
        "evidence_refs": list(evidence_refs),
        "gaps": deepcopy(gaps),
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
    return sorted(
        entries,
        key=lambda item: (item["created_at"], item["checkpoint_ref"]),
    )


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
    return sorted(
        [*fragments, candidate],
        key=lambda item: (item["created_at"], item["checkpoint_ref"]),
    ), True


def assemble_snapshot(
    base: dict[str, Any],
    fragments: list[dict[str, Any]],
) -> dict[str, Any]:
    value = deepcopy(base)
    value["sections"] = [
        deepcopy(section)
        for fragment in fragments
        for section in fragment["sections"]
    ]
    value["evidence_refs"] = list(dict.fromkeys(
        ref for fragment in fragments for ref in fragment["evidence_refs"]
    ))[:64]
    value["gaps"] = [
        deepcopy(gap) for fragment in fragments for gap in fragment["gaps"]
    ][-32:]
    return value


def journal_payload(
    *, branch_id: str, fragments: list[dict[str, Any]],
) -> bytes:
    value = {
        "schema_version": 1,
        "language": "zh-Hans",
        "branch_id": branch_id,
        "checkpoints": [
            {
                "checkpoint_ref": fragment["checkpoint_ref"],
                "created_at": fragment["created_at"],
                "carrier_hash": fragment["carrier_hash"],
                "narrative_hash": fragment["narrative_hash"],
                "section_hash": fragment["section_hash"],
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
    if candidate.get("schema_version") != 1:
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
    section_hash = candidate.pop("section_hash")
    if not isinstance(section_hash, str) or content_hash(candidate) != section_hash:
        raise ValueError("research journal fragment hash is invalid")
    candidate["section_hash"] = section_hash
    return candidate


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
