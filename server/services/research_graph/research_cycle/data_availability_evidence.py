"""Factual, request-bound availability EvidenceEnvelope projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from tools.data.availability.model import canonical_hash


REQUEST_FIELDS = {"products", "sources", "probe", "expanded"}
_SECRET_FIELDS = {
    "access_token",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "token",
}


def validate_availability_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("data_availability_request must be an object")
    extra = sorted(set(value) - REQUEST_FIELDS)
    if extra:
        raise ValueError(
            "data_availability_request contains unsupported fields: "
            + ", ".join(extra)
        )
    products = _scope(value.get("products"), field="products")
    sources = _scope(value.get("sources"), field="sources")
    expanded = value.get("expanded", False)
    if expanded is not False:
        raise ValueError(
            "Graph availability evidence requires expanded=false"
        )
    probe = value.get("probe", False)
    if not isinstance(probe, bool):
        raise ValueError("data_availability_request.probe must be boolean")
    return {
        "products": products,
        "sources": sources,
        "probe": probe,
        "expanded": False,
    }


def project_availability_evidence(
    *,
    profile: Any,
    request: dict[str, Any],
    checkpoint: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Validate provider output and bind facts to current research identity."""
    normalized = _validate_profile(profile, request=request)
    present = _requested_products_present(normalized)
    profile_hash = str(normalized["profile_hash"]).removeprefix("sha256:")
    profile_ref = "data-availability-profile:sha256:" + profile_hash
    value = {
        "schema_version": 2,
        "envelope_id": (
            "data-availability:"
            + json_hash({
                "profile_hash": profile_hash,
                "contract_hash": checkpoint["contract_hash"],
                "methodology_hash": checkpoint["methodology_hash"],
            })
        ),
        "evidence_kind": "data_availability",
        "source_refs": [profile_ref],
        "identity_refs": {
            "contract_hash": checkpoint["contract_hash"],
            "methodology_hash": checkpoint["methodology_hash"],
        },
        "facts": {
            "profile_ref": profile_ref,
            "profile_as_of": normalized["as_of"],
            "request": deepcopy(request),
            "product_status": [
                {
                    "product": product,
                    "available": product in _available_products(normalized),
                }
                for product in request["products"]
            ],
            "requested_product_availability_present": present,
        },
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [
            "Availability does not establish point-in-time integrity, "
            "replayability, latency fitness, or discharge an obligation."
        ],
        "conflicts": [],
    }
    return validate_agent_evidence_envelope(value), present


def project_data_provenance_evidence(
    *,
    profile: Any,
    request: dict[str, Any],
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """Bind a compact server-owned status without claiming PIT validity."""
    normalized = _validate_profile(profile, request=request)
    present = _requested_products_present(normalized)
    profile_hash = str(normalized["profile_hash"]).removeprefix("sha256:")
    profile_ref = "data-availability-profile:sha256:" + profile_hash
    entries = [
        item for item in normalized["entries"]
        if item.get("status") == "available"
    ]
    replayable = bool(entries) and all(
        item.get("replayable") is True for item in entries
    )
    # The current provider profile carries file metadata, not a verified
    # dataset-manifest@2. Keep this false until a content-hash verifier owns
    # every provenance dimension below.
    point_in_time_verified = False
    if not present:
        integrity_status = "unavailable"
    elif point_in_time_verified:
        integrity_status = "verified"
    else:
        integrity_status = "bounded_unverified"
    open_dimensions = [] if point_in_time_verified else [
        "adjustment_vintage",
        "availability_time",
        "calendar",
        "contract_membership_vintage",
        "session",
        "source_content_checksum",
        "timezone",
    ]
    bound_dimensions = (
        [
            "adjustment_vintage",
            "availability_time",
            "calendar",
            "contract_membership_vintage",
            "coverage",
            "frequency",
            "product_identity",
            "session",
            "source_content_checksum",
            "snapshot_reference",
            "timezone",
        ]
        if point_in_time_verified
        else [
            "coverage",
            "frequency",
            "product_identity",
            "snapshot_reference",
        ]
    )
    value = {
        "schema_version": 2,
        "envelope_id": (
            "data-provenance:"
            + json_hash({
                "profile_hash": profile_hash,
                "contract_hash": checkpoint["contract_hash"],
                "methodology_hash": checkpoint["methodology_hash"],
            })
        ),
        "evidence_kind": "data_contract",
        "source_refs": [profile_ref],
        "identity_refs": {
            "contract_hash": checkpoint["contract_hash"],
            "methodology_hash": checkpoint["methodology_hash"],
        },
        "facts": {
            "profile_ref": profile_ref,
            "integrity_status": integrity_status,
            "requested_product_availability_present": present,
            "point_in_time_verified": point_in_time_verified,
            "replayable": replayable,
            "bound_dimensions": bound_dimensions,
            "open_dimensions": open_dimensions,
        },
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": (
            []
            if point_in_time_verified
            else [
                "The bound snapshot does not prove every field was available "
                "at signal time; the point-in-time obligation remains open."
            ]
        ),
        "conflicts": [],
    }
    return validate_agent_evidence_envelope(value)
def _validate_profile(
    profile: Any,
    *,
    request: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(profile, dict) or profile.get("schema_version") != 2:
        raise ValueError("availability service must return schema_version 2")
    value = deepcopy(profile)
    if value.get("product_scope") != request["products"]:
        raise ValueError("availability product scope mismatch")
    if value.get("source_scope") != request["sources"]:
        raise ValueError("availability source scope mismatch")
    if value.get("probe") is not request["probe"]:
        raise ValueError("availability probe scope mismatch")
    if value.get("expanded") is not False:
        raise ValueError("availability expanded scope mismatch")
    entries = value.get("entries")
    if not isinstance(entries, list) or not all(
        isinstance(item, dict) for item in entries
    ):
        raise ValueError("availability entries must be an object array")
    declared_hash = str(value.pop("profile_hash", ""))
    if declared_hash != canonical_hash(value):
        raise ValueError("availability profile_hash mismatch")
    if _contains_secret_field(value):
        raise ValueError("availability profile contains credential material")
    value["profile_hash"] = declared_hash
    return value


def _requested_products_present(profile: dict[str, Any]) -> bool:
    return all(
        product in _available_products(profile)
        for product in profile["product_scope"]
    )


def _available_products(profile: dict[str, Any]) -> set[str]:
    return {
        str(entry.get("product") or "")
        for entry in profile["entries"]
        if entry.get("status") == "available"
    }


def _scope(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(
            f"data_availability_request.{field} must be non-empty"
        )
    normalized = [
        str(item).strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]
    if len(normalized) != len(value) or len(set(normalized)) != len(normalized):
        raise ValueError(
            f"data_availability_request.{field} must contain unique text"
        )
    return normalized


def _contains_secret_field(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in _SECRET_FIELDS
            or _contains_secret_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret_field(item) for item in value)
    return False
