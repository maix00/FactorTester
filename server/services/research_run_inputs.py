"""Pure input normalization for immutable ResearchRun creation."""

from __future__ import annotations

from typing import Any

import orjson

from server.services.research_sample_exposure import require_exact_product_membership
from server.services.research_sample_identity import derive_sample_identity


def derive_sample_identity_or_none(
    run_spec: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        return derive_sample_identity(run_spec)
    except ValueError:
        return None


def persisted_sample_identity(
    *,
    sample_identity: dict[str, Any] | None,
) -> dict[str, str]:
    identity = sample_identity or {}
    exact_members = (
        identity.get("universe_membership_assurance")
        == "exact_frozen_product_scope"
    )
    members_json = (
        orjson.dumps(require_exact_product_membership(identity)).decode()
        if exact_members else ""
    )
    assurance = "server_derived_unbound" if sample_identity else "unavailable"
    return {
        "sample_identity_hash": str(identity.get("sample_hash") or ""),
        "sample_start": str(identity.get("sample_start") or ""),
        "sample_end": str(identity.get("sample_end") or ""),
        "sample_universe_hash": str(identity.get("universe_hash") or ""),
        "sample_universe_members_json": members_json,
        "sample_design_context_hash": str(
            identity.get("design_context_hash") or ""
        ),
        "sample_identity_assurance": assurance,
    }
