"""Load, validate, and identify capability contracts."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
import re
from typing import Any


_IMPLEMENTATION_KINDS = {"cli", "server", "skill", "library", "guidance"}
_APPROVAL_STATUSES = {
    "approved",
    "quarantined",
    "unavailable",
    "rejected",
    "superseded",
}
_EXECUTION_MODES = {"real_backend", "guidance_only", "external_service"}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def load_builtin_capability_registry() -> dict[str, Any]:
    """Load the packaged, reviewable capability catalog."""
    resources = files("cli_anything.factortester_research").joinpath("resources")
    registry = json.loads(
        resources.joinpath("capabilities.v1.json").read_text(encoding="utf-8")
    )
    registry["provider_lock"] = json.loads(
        resources.joinpath("provider-locks.v1.json").read_text(encoding="utf-8")
    )
    return validate_capability_registry(registry)


def validate_capability_registry(registry: dict[str, Any]) -> dict[str, Any]:
    """Validate the public capability-catalog protocol."""
    if not isinstance(registry, dict):
        raise ValueError("capability registry must be an object")
    if int(registry.get("schema_version") or 0) != 1:
        raise ValueError("unsupported capability registry schema_version")
    capabilities = registry.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, dict) for item in capabilities
    ):
        raise ValueError("capabilities must be an array of objects")
    ids = [str(item.get("capability_id") or "").strip() for item in capabilities]
    if any(not item for item in ids):
        raise ValueError("every capability requires capability_id")
    if len(set(ids)) != len(ids):
        raise ValueError("capability ids must be unique")
    _validate_provider_lock(registry.get("provider_lock"))
    for capability in capabilities:
        _validate_capability(capability)
    return deepcopy(registry)


def _validate_provider_lock(provider_lock: object) -> None:
    if provider_lock is None:
        return
    if not isinstance(provider_lock, dict):
        raise ValueError("provider_lock must be an object")
    if int(provider_lock.get("schema_version") or 0) != 1:
        raise ValueError("unsupported provider_lock schema_version")
    providers = provider_lock.get("providers")
    implementations = provider_lock.get("implementations")
    if not isinstance(providers, dict):
        raise ValueError("provider_lock.providers must be an object")
    if not isinstance(implementations, dict):
        raise ValueError("provider_lock.implementations must be an object")
    for implementation_id, source in implementations.items():
        if not isinstance(source, dict):
            raise ValueError(
                f"provider source lock must be an object: {implementation_id}"
            )
        sha256 = str(source.get("sha256") or "")
        if not _SHA256_PATTERN.fullmatch(sha256):
            raise ValueError(
                f"provider source lock requires sha256: {implementation_id}"
            )


def _validate_capability(capability: dict[str, Any]) -> None:
    capability_id = str(capability["capability_id"])
    if not str(capability.get("industry_semantics") or "").strip():
        raise ValueError(
            f"capability requires industry_semantics: {capability_id}"
        )
    for key in ("when_to_use", "preconditions", "prohibitions"):
        value = capability.get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ValueError(
                f"{key} must contain non-empty strings: {capability_id}"
            )
    implementations = capability.get("implementations")
    if not isinstance(implementations, list) or not all(
        isinstance(item, dict) for item in implementations
    ):
        raise ValueError(f"implementations must be an array: {capability_id}")
    implementation_ids = [
        str(item.get("implementation_id") or "").strip()
        for item in implementations
    ]
    if any(not item for item in implementation_ids):
        raise ValueError(
            f"every implementation requires implementation_id: {capability_id}"
        )
    if len(set(implementation_ids)) != len(implementation_ids):
        raise ValueError(
            f"implementation ids must be unique within {capability_id}"
        )
    for implementation in implementations:
        _validate_implementation(implementation)


def _validate_implementation(implementation: dict[str, Any]) -> None:
    implementation_id = str(implementation["implementation_id"])
    if str(implementation.get("kind") or "") not in _IMPLEMENTATION_KINDS:
        raise ValueError(f"invalid implementation kind: {implementation_id}")
    if str(implementation.get("approval_status") or "") not in _APPROVAL_STATUSES:
        raise ValueError(
            f"invalid implementation approval_status: {implementation_id}"
        )
    if str(implementation.get("execution_mode") or "") not in _EXECUTION_MODES:
        raise ValueError(
            f"invalid implementation execution_mode: {implementation_id}"
        )
    requires_approval = implementation.get("requires_execution_approval", False)
    if not isinstance(requires_approval, bool):
        raise ValueError(
            "requires_execution_approval must be boolean: "
            f"{implementation_id}"
        )
    product_scopes = implementation.get("product_scopes")
    if not isinstance(product_scopes, list) or not all(
        isinstance(item, str) and item.strip() for item in product_scopes
    ):
        raise ValueError(
            "implementation product_scopes must be non-empty strings: "
            f"{implementation_id}"
        )
    approved_source_sha256 = implementation.get("approved_source_sha256")
    if approved_source_sha256 is not None and not (
        isinstance(approved_source_sha256, str)
        and _SHA256_PATTERN.fullmatch(approved_source_sha256)
    ):
        raise ValueError(
            f"invalid approved_source_sha256: {implementation_id}"
        )


def capability_descriptor(contract: dict[str, Any]) -> dict[str, str]:
    """Return the compact semantic descriptor embedded in graph versions."""
    description = str(contract.get("industry_semantics") or "").strip()
    return {
        "capability_description": description,
        "descriptor_hash": canonical_hash({
            "capability_id": str(contract.get("capability_id") or ""),
            "industry_semantics": description,
            "when_to_use": contract.get("when_to_use") or [],
            "preconditions": contract.get("preconditions") or [],
            "prohibitions": contract.get("prohibitions") or [],
        }),
    }
