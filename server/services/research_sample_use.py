"""Small, execution-facing sample-use contracts for ResearchRuns."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from server.services.research_sample_exposure import require_exact_product_membership


_PURPOSES = frozenset({
    "exploration", "selection", "validation", "confirmation", "holdout",
})
_PROTECTIONS = frozenset({"open", "sealed"})
_CONTRACT_FIELDS = {
    "schema_version", "purpose", "protection", "comparison_id",
    "member_run_spec_hashes",
}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_COMPARISON_ID = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_MAX_COMPARISON_MEMBERS = 256


def normalize_sample_use(
    value: dict[str, Any] | None,
    *,
    run_spec_hash: str,
    sample_identity: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Freeze intended data use separately from sealed-sample protection."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("sample_use must be an object")
    unknown = sorted(set(value) - _CONTRACT_FIELDS)
    if unknown:
        raise ValueError("sample_use has unsupported fields: " + ", ".join(unknown))
    version = value.get("schema_version")
    if isinstance(version, bool) or version != 1:
        raise ValueError("sample_use.schema_version must be 1")
    purpose = str(value.get("purpose") or "").strip()
    if purpose not in _PURPOSES:
        raise ValueError("sample_use.purpose is unsupported")
    protection = str(value.get("protection") or "open").strip()
    if protection not in _PROTECTIONS:
        raise ValueError("sample_use.protection must be open or sealed")
    identity = sample_identity or {}
    sample_hash = str(identity.get("sample_hash") or "")
    if not sample_hash:
        raise ValueError("sample_use requires a server-derived sample identity")

    comparison_id = str(value.get("comparison_id") or "").strip()
    raw_members = value.get("member_run_spec_hashes", [])
    if protection == "sealed":
        if not _COMPARISON_ID.fullmatch(comparison_id):
            raise ValueError(
                "sealed sample_use requires a valid comparison_id"
            )
        if not isinstance(raw_members, list) or not raw_members:
            raise ValueError(
                "sealed sample_use requires member_run_spec_hashes"
            )
        if len(raw_members) > _MAX_COMPARISON_MEMBERS:
            raise ValueError("sealed comparison exceeds 256 RunSpec members")
        members = []
        for index, raw in enumerate(raw_members):
            digest = str(raw or "").removeprefix("sha256:")
            if not _HASH.fullmatch(digest):
                raise ValueError(
                    f"sample_use.member_run_spec_hashes[{index}] must be sha256"
                )
            members.append(digest)
        if len(members) != len(set(members)):
            raise ValueError("sealed comparison members must be unique")
        members.sort()
        current = str(run_spec_hash).removeprefix("sha256:")
        if current not in members:
            raise ValueError(
                "sealed comparison must include the current RunSpec"
            )
        require_exact_product_membership(identity)
    else:
        if comparison_id or raw_members not in (None, []):
            raise ValueError(
                "open sample_use cannot declare a sealed comparison set"
            )
        members = []

    contract = {
        "schema_version": 1,
        "purpose": purpose,
        "protection": protection,
        "comparison_id": comparison_id,
        "member_run_spec_hashes": members,
        "sample_hash": sample_hash,
    }
    encoded = json.dumps(
        contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    contract["sample_use_hash"] = hashlib.sha256(encoded).hexdigest()
    return contract
