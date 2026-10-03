"""ResearchRun-level protection against repeated sample exposure."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from server.services.research_sample_identity import derive_sample_identity


PROTECTED_SAMPLE_ROLES = frozenset({"confirmation", "holdout", "validation"})


def require_exact_product_membership(
    sample_identity: dict[str, Any] | None,
) -> list[str]:
    """Return canonical frozen members or reject an unprovable protected run."""
    identity = sample_identity or {}
    members = identity.get("universe_members")
    if (
        identity.get("universe_membership_assurance")
        != "exact_frozen_product_scope"
        or not isinstance(members, list)
        or not members
        or any(
            not isinstance(member, str)
            or not member.strip()
            or member != member.strip()
            for member in members
        )
        or len(set(members)) != len(members)
    ):
        raise ValueError(
            "protected sample role requires an exact frozen product-membership snapshot"
        )
    return sorted(members)


def validate_protected_sample_exposure(
    conn: sqlite3.Connection,
    *,
    owner: str,
    trial_plan_hash: str,
    trial_plan_schema_version: int,
    trial_stage: str,
    sample_identity_hash: str,
    sample_start: str,
    sample_end: str,
    sample_universe_members_json: str,
) -> None:
    """Reject an overlapping earlier ResearchRun before registering this run.

    The caller holds the ResearchRun write transaction while this check and
    insertion execute. Unknown prior membership fails closed for date-overlap
    candidates; the check does not expand mutable product groups at read time.
    """
    if trial_stage not in PROTECTED_SAMPLE_ROLES:
        return
    if not sample_identity_hash:
        raise ValueError(
            "protected sample role requires server-derived sample identity"
        )
    try:
        current_members = json.loads(sample_universe_members_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "protected sample role requires an exact frozen product-membership snapshot"
        ) from exc
    if (
        not isinstance(current_members, list)
        or not current_members
        or any(
            not isinstance(member, str)
            or not member.strip()
            or member != member.strip()
            for member in current_members
        )
        or len(set(current_members)) != len(current_members)
    ):
        raise ValueError(
            "protected sample role requires an exact frozen product-membership snapshot"
        )
    if not sample_start or not sample_end or sample_start > sample_end:
        raise ValueError(
            "protected sample role requires an unambiguous date range"
        )

    cursor = conn.execute(
        """
        SELECT sample_start, sample_end, sample_universe_hash,
               sample_universe_members_json, run_spec_json
        FROM research_runs
        WHERE owner=?
          AND sample_start<>''
          AND sample_end<>''
          AND sample_start<=?
          AND sample_end>=?
          AND (
              trial_plan_hash<>?
              OR (?<5 AND trial_stage<>?)
          )
        """,
        (
            owner,
            sample_end,
            sample_start,
            trial_plan_hash,
            trial_plan_schema_version,
            trial_stage,
        ),
    )
    current_set = set(current_members)
    for row in cursor:
        prior_members = _parse_exact_members(
            row["sample_universe_members_json"]
        )
        if prior_members is None:
            prior_members = _recover_members_from_run_spec(row)
        if prior_members is None:
            raise ValueError(
                "prior product membership cannot be proven for an "
                "overlapping date range"
            )
        if current_set.intersection(prior_members):
            raise ValueError(
                "protected sample was already exposed for overlapping "
                "products and dates"
            )


def _parse_exact_members(value: Any) -> list[str] | None:
    try:
        members = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(members, list)
        or not members
        or any(
            not isinstance(member, str)
            or not member.strip()
            or member != member.strip()
            for member in members
        )
        or len(set(members)) != len(members)
    ):
        return None
    return members


def _recover_members_from_run_spec(row: sqlite3.Row) -> list[str] | None:
    try:
        run_spec = json.loads(str(row["run_spec_json"] or ""))
        identity = derive_sample_identity(run_spec)
        if (
            identity["sample_start"] != str(row["sample_start"])
            or identity["sample_end"] != str(row["sample_end"])
            or (
                row["sample_universe_hash"]
                and identity["universe_hash"]
                != str(row["sample_universe_hash"])
            )
        ):
            return None
        return require_exact_product_membership(identity)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
