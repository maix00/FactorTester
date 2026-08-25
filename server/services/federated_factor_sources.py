"""Hash-bound factor sources carried only in Manager-authored Run contexts."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from server.services.factor_source_objects import (
    hydrate_source_free_entries,
    portable_source_path,
    source_free_context,
    source_free_manifest,
    source_transfer_manifest,
)
from tools.cli.factor_subject_refs import split_owner_qualified_factor_family
from tools.factors.formula_identity import require_frozen_factor

MAX_FILES = 200
MAX_SOURCE_BYTES = 20 * 1024 * 1024
_FACTOR_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _revision_contracts(
    run_spec: dict[str, Any],
) -> dict[str, dict[str, str]]:
    configuration = run_spec.get("configuration")
    shared = configuration.get("shared") if isinstance(configuration, dict) else None
    factors = shared.get("factors") if isinstance(shared, dict) else None
    if not isinstance(factors, list):
        raise ValueError("RunSpec has no frozen factors")
    contracts: dict[str, dict[str, str]] = {}
    for raw in factors:
        item = require_frozen_factor(raw)
        identity = item["identity"]
        canonical_ref = f"{item['owner_ref']}:{identity['family_alias']}"
        contract = {
            "family_formula_fingerprint": identity[
                "family_formula_fingerprint"
            ],
        }
        prior = contracts.setdefault(canonical_ref, contract)
        if prior != contract:
            raise ValueError(
                f"frozen factors disagree for {canonical_ref!r}"
            )
    return contracts


_portable_path = portable_source_path


def validate_entries(raw: Any) -> list[dict[str, Any]]:
    """Validate a bounded portable bundle without trusting declared hashes."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ValueError("portable_factor_sources must be an array")
    if len(raw) > MAX_FILES:
        raise ValueError("too many portable factor source files")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each portable factor source must be an object")
        canonical_ref = str(item.get("canonical_family_ref") or "").strip()
        source_owner, factor_id = split_owner_qualified_factor_family(
            canonical_ref,
        )
        if source_owner is None or not _FACTOR_ID.fullmatch(factor_id):
            raise ValueError("portable factor source identity is invalid")
        source_kind = "public" if source_owner == "public" else "custom"
        source_policy = str(item.get("source_access_policy") or "").strip()
        if not source_policy:
            raise ValueError("portable factor source access policy is required")
        if str(item.get("source_kind") or "") != source_kind:
            raise ValueError("portable factor source kind does not match its identity")
        if str(item.get("source_owner") or "") != source_owner:
            raise ValueError("portable factor source owner does not match its identity")
        if str(item.get("factor_id") or "") != factor_id:
            raise ValueError("portable factor id does not match its identity")
        if canonical_ref in seen:
            raise ValueError(f"duplicate portable factor source: {canonical_ref}")
        source_code = item.get("source_code")
        if not isinstance(source_code, str) or not source_code.strip():
            raise ValueError(f"portable factor source is empty: {canonical_ref}")
        encoded = source_code.encode("utf-8")
        total += len(encoded)
        if total > MAX_SOURCE_BYTES:
            raise ValueError("portable factor source bundle exceeds size limit")
        source_hash = hashlib.sha256(encoded).hexdigest()
        if str(item.get("source_sha256") or "") != source_hash:
            raise ValueError(
                f"portable factor source hash changed: {canonical_ref}"
            )
        if int(item.get("source_bytes") or -1) != len(encoded):
            raise ValueError(
                f"portable factor source size changed: {canonical_ref}"
            )
        expected_path = _portable_path(canonical_ref)
        if str(item.get("path") or "") != expected_path:
            raise ValueError(
                f"portable factor source path is invalid: {canonical_ref}"
            )
        seen.add(canonical_ref)
        entries.append({
            "canonical_family_ref": canonical_ref,
            "source_kind": source_kind,
            "source_owner": source_owner,
            "source_access_policy": source_policy,
            "factor_id": factor_id,
            "path": expected_path,
            "source_code": source_code,
            "source_sha256": source_hash,
            "source_bytes": len(encoded),
        })
    return sorted(entries, key=lambda item: item["canonical_family_ref"])


def freeze_sources(prepared: dict[str, Any], *, owner: str) -> list[dict[str, Any]]:
    """Read every referenced canonical source once at the origin Manager."""
    from server.services.factor_registry import (
        resolve_factor_family_source,
        transient_factor_source_scope,
    )

    run_spec = prepared.get("run_spec")
    if not isinstance(run_spec, dict):
        raise ValueError("portable factor sources require a RunSpec")
    expected = _revision_contracts(run_spec)
    transient_sources = list(prepared.get("transient_sources") or [])
    transient_overrides = {
        str(item.get("factor_id") or ""): str(item.get("source_code") or "")
        for item in transient_sources
        if isinstance(item, dict) and item.get("factor_id")
    }
    already_carried: set[str] = set()
    for item in transient_sources:
        if not isinstance(item, dict):
            continue
        canonical_ref = f"{owner}:{item.get('factor_id')}"
        if canonical_ref in expected:
            already_carried.add(canonical_ref)

    entries: list[dict[str, Any]] = []
    with transient_factor_source_scope(
        owner=owner,
        overrides=transient_overrides,
    ):
        for canonical_ref in sorted(expected):
            if canonical_ref in already_carried:
                continue
            source = resolve_factor_family_source(
                canonical_ref,
                username=owner,
            )
            if str(source.get("canonical_family_ref") or "") != canonical_ref:
                raise ValueError(
                    f"factor source identity changed while freezing {canonical_ref!r}"
                )
            source_code = str(source.get("source_code") or "")
            encoded = source_code.encode("utf-8")
            source_hash = hashlib.sha256(encoded).hexdigest()
            entries.append({
                "canonical_family_ref": canonical_ref,
                "source_kind": str(source["source_kind"]),
                "source_owner": str(source["source_owner"]),
                "source_access_policy": str(
                    source.get("source_access_policy")
                    or source.get("source_mode")
                    or "transient_run_source"
                ),
                "factor_id": str(source["factor_id"]),
                "path": _portable_path(canonical_ref),
                "source_code": source_code,
                "source_sha256": source_hash,
                "source_bytes": len(encoded),
            })
    return validate_entries(entries)


def validate_context_sources(prepared: dict[str, Any], *, owner: str) -> None:
    """Require exact source coverage for every frozen factor family."""
    from server.services.transient_factor_sources import (
        validate_entries as validate_transient_entries,
    )

    run_spec = prepared.get("run_spec")
    if not isinstance(run_spec, dict):
        raise ValueError("portable factor sources require a RunSpec")
    contracts = _revision_contracts(run_spec)
    expected = set(contracts)
    transient = validate_transient_entries(prepared.get("transient_sources"))
    portable = validate_entries(hydrate_source_free_entries(
        prepared.get("portable_factor_sources") or [],
        owner=owner,
        allowed_object_ids=expected,
    ))
    if len(transient) + len(portable) > MAX_FILES:
        raise ValueError("combined factor source bundle has too many files")
    if sum(
        int(item["source_bytes"]) for item in [*transient, *portable]
    ) > MAX_SOURCE_BYTES:
        raise ValueError("combined factor source bundle exceeds size limit")
    prepared["transient_sources"] = transient
    prepared["portable_factor_sources"] = portable

    covered: set[str] = set()
    for item in transient:
        factor_id = str(item.get("factor_id") or "")
        canonical_ref = f"{owner}:{factor_id}"
        if canonical_ref in expected:
            covered.add(canonical_ref)
    for item in portable:
        canonical_ref = str(item["canonical_family_ref"])
        if canonical_ref not in expected:
            raise ValueError(
                f"portable factor source is not referenced: {canonical_ref}"
            )
        covered.add(canonical_ref)
    if covered != expected:
        missing = sorted(expected - covered)
        detail = ", ".join(f"missing {ref}" for ref in missing)
        raise ValueError(
            "portable factor sources do not match the RunSpec"
            + (f": {detail}" if detail else "")
        )


__all__ = [
    "freeze_sources",
    "hydrate_source_free_entries",
    "portable_source_path",
    "source_free_context",
    "source_free_manifest",
    "source_transfer_manifest",
    "validate_context_sources",
    "validate_entries",
]
