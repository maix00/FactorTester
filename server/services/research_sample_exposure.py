"""ResearchRun-level protection against repeated sample exposure."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from server.services.research_sample_identity import derive_sample_identity


_LEGACY_PROTECTED_SAMPLE_ROLES = frozenset({
    "confirmation", "holdout", "validation",
})


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


def validate_sample_use_exposure(
    conn: sqlite3.Connection,
    *,
    owner: str,
    run_spec_hash: str,
    sample_identity: dict[str, Any] | None,
    sample_use: dict[str, Any] | None,
) -> None:
    """Enforce sealed-use contracts independently of optional TrialPlans.

    A sealed contract may execute each predeclared RunSpec once. Any previous
    overlapping Run outside that contract means the sample is not pristine.
    An explicitly open Run may record a later exploratory exposure, but it
    invalidates further sealed use of that overlapping sample.
    """
    identity = sample_identity or {}
    start = str(identity.get("sample_start") or "")
    end = str(identity.get("sample_end") or "")
    current_hash = str(run_spec_hash).removeprefix("sha256:")
    current_use = sample_use or {}
    current_sealed = current_use.get("protection") == "sealed"

    unknown_rows = conn.execute(
        """
        SELECT sample_use_json, sample_use_hash, trial_plan_hash, trial_stage
        FROM research_runs
        WHERE owner=?
          AND (
              trial_stage IN ('confirmation', 'holdout', 'validation')
              OR sample_use_hash<>''
          )
          AND (sample_start='' OR sample_end='')
        """,
        (owner,),
    ).fetchall()
    if any(_is_sealed_row(row) for row in unknown_rows):
        # An unreadable prior scope could intersect any later run by this owner.
        raise ValueError(
            "prior sealed sample scope cannot be proven for this owner"
        )

    if not start or not end or start > end:
        existing_rows = conn.execute(
            """
            SELECT sample_use_json, sample_use_hash, trial_plan_hash, trial_stage
            FROM research_runs
            WHERE owner=? AND (
                trial_stage IN ('confirmation', 'holdout', 'validation')
                OR sample_use_hash<>''
            )
            """,
            (owner,),
        ).fetchall()
        if any(_is_sealed_row(row) for row in existing_rows):
            raise ValueError(
                "sample identity is unavailable; cannot rule out sealed-sample overlap"
            )
        return

    date_rows = conn.execute(
        """
        SELECT * FROM research_runs
        WHERE owner=? AND sample_start<>'' AND sample_end<>''
          AND sample_start<=? AND sample_end>=?
        ORDER BY created_at, run_id
        """,
        (owner, end, start),
    ).fetchall()
    if not date_rows:
        return

    current_members = _exact_current_members(identity)
    if current_members is None:
        if current_sealed or any(_is_sealed_row(row) for row in date_rows):
            raise ValueError(
                "product membership cannot be proven for an overlapping sealed sample"
            )
        return
    current_set = set(current_members)

    for row in date_rows:
        prior_members = _parse_exact_members(
            row["sample_universe_members_json"]
        )
        if prior_members is None:
            prior_members = _recover_members_from_run_spec(row)
        if prior_members is None:
            if current_sealed or _is_sealed_row(row):
                raise ValueError(
                    "prior product membership cannot be proven for an overlapping sample"
                )
            continue
        if not current_set.intersection(prior_members):
            continue

        prior_use = _sample_use_from_row(row)
        if current_sealed:
            if (
                prior_use is not None
                and prior_use.get("sample_use_hash")
                == current_use.get("sample_use_hash")
            ):
                allowed = set(current_use.get("member_run_spec_hashes") or [])
                if current_hash not in allowed:
                    raise ValueError(
                        "sealed comparison does not include this RunSpec"
                    )
                if str(row["run_spec_hash"] or "") == current_hash:
                    raise ValueError(
                        "sealed comparison member has already been exposed"
                    )
                continue
            raise ValueError(
                "sealed sample was already exposed by an overlapping Run"
            )

        if _is_sealed_row(row):
            if sample_use is None:
                raise ValueError(
                    "sealed sample reuse requires an explicit sample_use exposure"
                )
            if sample_use is not None and sample_use.get("protection") == "open":
                # This Run is persisted as a new, explicitly non-confirmatory exposure.
                continue
            raise ValueError(
                "sealed sample cannot be reused under a different comparison"
            )


def _exact_current_members(identity: dict[str, Any]) -> list[str] | None:
    try:
        return require_exact_product_membership(identity)
    except ValueError:
        return None


def _sample_use_from_row(row: sqlite3.Row) -> dict[str, Any] | None:
    try:
        value = json.loads(str(row["sample_use_json"] or "{}"))
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and value.get("sample_use_hash") else None


def _is_sealed_row(row: sqlite3.Row) -> bool:
    sample_use = _sample_use_from_row(row)
    if sample_use is not None:
        return sample_use.get("protection") == "sealed"
    if str(row["sample_use_hash"] or ""):
        return True
    return (
        bool(str(row["trial_plan_hash"] or ""))
        and str(row["trial_stage"] or "") in _LEGACY_PROTECTED_SAMPLE_ROLES
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
