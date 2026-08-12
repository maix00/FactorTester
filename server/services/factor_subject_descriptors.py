"""Server validation for CLI-frozen factor-set subjects attached to a RunSpec."""

from __future__ import annotations

from base64 import urlsafe_b64decode
import hashlib
import json
from typing import Any

from tools.cli.factor_subject_refs import factor_subject_kind


def validate_factor_subject_descriptors(value: Any) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("factor_subject_descriptors must contain at most 32 items")
    result = [_validate_factor_set(item) for item in value]
    refs = [item["target_ref"] for item in result]
    if len(set(refs)) != len(refs):
        raise ValueError("factor subject descriptors must be unique")
    return result


def assert_factor_sets_match_run(
    descriptors: list[dict[str, Any]],
    *,
    factor_alias_hashes: set[str],
) -> None:
    if not descriptors:
        return
    declared_aliases = {
        alias
        for descriptor in descriptors
        for alias in descriptor["member_aliases"]
    }
    declared = {
        hashlib.sha256(alias.encode()).hexdigest()
        for alias in declared_aliases
    }
    if declared != factor_alias_hashes:
        missing = sorted(factor_alias_hashes - declared)
        extra = sorted(declared - factor_alias_hashes)
        raise ValueError(
            "factor-set members must exactly match the RunSpec factor revisions; "
            f"missing_alias_hashes={missing}, extra_alias_hashes={extra}"
        )


def compact_factor_subject_descriptors(
    descriptors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Discard submitted members after validation; retain frozen set identity."""
    allowed = (
        "target_ref", "set_ref", "member_hash", "member_count", "authority",
    )
    return [
        {key: descriptor[key] for key in allowed}
        for descriptor in descriptors
    ]


def factor_refs_by_alias(
    descriptors: list[dict[str, Any]],
) -> dict[str, str]:
    """Return the exact committed member ref for each submitted factor alias.

    The mapping is made from the already validated factor-set manifest.  It
    never parses or reconstructs an alias from selected parameters.  A factor
    set is only a transport/container object; each member remains the
    execution subject and keeps its own ``factor:v1`` identity.
    """
    bindings: dict[str, str] = {}
    for descriptor in descriptors:
        aliases = descriptor.get("member_aliases") or []
        refs = descriptor.get("member_refs") or []
        if len(aliases) != len(refs):
            raise ValueError("factor-set member alias/ref cardinality mismatch")
        for alias, target_ref in zip(aliases, refs, strict=True):
            alias_text = str(alias or "").strip()
            ref_text = str(target_ref or "").strip()
            if not alias_text or not ref_text.startswith("factor:v1:"):
                raise ValueError("factor-set member must bind one factor:v1 ref")
            previous = bindings.get(alias_text)
            if previous is not None and previous != ref_text:
                raise ValueError(
                    "one factor alias is bound to multiple committed factor refs"
                )
            bindings[alias_text] = ref_text
    return bindings


def _validate_factor_set(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"target_ref", "manifest"}:
        raise ValueError("factor subject descriptor fields are invalid")
    target_ref = str(value.get("target_ref") or "")
    if factor_subject_kind(target_ref) != "factor_set":
        raise ValueError("factor subject descriptor must identify factor-set:v1")
    manifest = value.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("factor-set descriptor manifest is invalid")
    members = manifest.get("member_refs")
    if (
        not isinstance(members, list)
        or not members
        or len(members) > 1024
        or len(set(members)) != len(members)
    ):
        raise ValueError("factor-set descriptor members are invalid")
    aliases = []
    for member in members:
        if factor_subject_kind(str(member)) != "factor":
            raise ValueError("factor-set descriptor members must be factor:v1")
        aliases.append(_decode(str(member).split(":")[4]))
    canonical_members = sorted(str(item) for item in members)
    if canonical_members != members:
        raise ValueError("factor-set descriptor members must be canonically sorted")
    member_hash = "sha256:" + hashlib.sha256(json.dumps(
        members, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    if manifest.get("member_hash") != member_hash:
        raise ValueError("factor-set descriptor member_hash is invalid")
    parts = target_ref.split(":")
    scope = parts[2]
    set_id = _decode(parts[4])
    if manifest.get("set_id") != set_id:
        raise ValueError("factor-set descriptor set_id is invalid")
    if manifest.get("set_ref") != f"factor-set:{scope}:{set_id}":
        raise ValueError("factor-set descriptor stable identity is invalid")
    payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    expected_blob = parts[-1]
    algorithm = "sha1" if len(expected_blob) == 40 else "sha256"
    observed_blob = hashlib.new(
        algorithm, f"blob {len(payload)}\0".encode() + payload,
    ).hexdigest()
    if observed_blob != expected_blob:
        raise ValueError("factor-set descriptor does not match its Git blob")
    return {
        "target_ref": target_ref,
        "set_ref": manifest["set_ref"],
        "member_hash": member_hash,
        "member_count": len(members),
        "member_refs": canonical_members,
        "member_aliases": aliases,
        "authority": "client_git_blob",
    }


def _decode(value: str) -> str:
    try:
        return urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("factor-set descriptor contains invalid encoded text") from error
