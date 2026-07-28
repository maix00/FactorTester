"""Server-side admission of reusable Evidence into one Graph transition."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson

from server.services.research_evidence_registry import ensure_schema
from server.services.research_evidence_scope import canonical, reference


_MAX_BINDINGS = 16
_ADMISSION_PREFIX = "admission:"


def resolve_graph_evidence_admissions(
    conn,
    *, owner: str, workspace_id: str, instance_id: str, branch_id: str,
    branch_row: Any, cycle_checkpoint: dict[str, Any] | None,
    submitted: Any,
) -> dict[str, Any]:
    """Return a bounded server-derived projection of admitted Evidence.

    Evidence itself remains reusable and owner-scoped in the Registry.  Every
    target Graph branch needs a separate admission, so a reference copied from
    a different research environment cannot silently qualify a transition.
    """
    if submitted in (None, []):
        return {"bindings": [], "evidence_refs": [], "eligible": False}
    if not isinstance(submitted, list) or not submitted:
        raise ValueError("admitted_evidence must be a non-empty array")
    if len(submitted) > _MAX_BINDINGS:
        raise ValueError("admitted_evidence exceeds the binding limit")
    ensure_schema(conn)
    environment_ref = f"workspace:{workspace_id}"
    subject_ref = f"graph-branch:{instance_id}:{branch_id}"
    identities = _branch_identities(branch_row, cycle_checkpoint)
    bindings: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    seen_admissions: set[str] = set()
    for item in submitted:
        evidence_ref, admission_ref = _submitted_pair(item)
        if evidence_ref in seen_evidence or admission_ref in seen_admissions:
            raise ValueError("admitted_evidence bindings must be unique")
        row = conn.execute(
            """
            SELECT objects.evidence_ref, objects.evidence_kind,
                   objects.envelope_hash, objects.applicability_json,
                   admissions.admission_ref, admissions.qualification
            FROM research_evidence_admissions AS admissions
            JOIN research_evidence_objects AS objects
              ON objects.evidence_ref=admissions.evidence_ref
             AND objects.owner=admissions.owner
            WHERE admissions.admission_ref=? AND admissions.evidence_ref=?
              AND admissions.owner=? AND admissions.environment_ref=?
              AND admissions.subject_ref=?
            """,
            (admission_ref, evidence_ref, owner, environment_ref, subject_ref),
        ).fetchone()
        if row is None:
            raise ValueError("evidence admission is not valid for this Graph branch")
        applicability = _applicability(row["applicability_json"])
        _validate_identity_scope(applicability, identities)
        bindings.append({
            "evidence_ref": str(row["evidence_ref"]),
            "admission_ref": str(row["admission_ref"]),
            "evidence_kind": str(row["evidence_kind"]),
            "envelope_hash": str(row["envelope_hash"]),
            "qualification": str(row["qualification"]),
            "applicability_hash": hashlib.sha256(
                canonical(applicability).encode()
            ).hexdigest(),
        })
        seen_evidence.add(evidence_ref)
        seen_admissions.add(admission_ref)
    return {
        "bindings": bindings,
        "evidence_refs": [item["evidence_ref"] for item in bindings],
        "eligible": all(item["qualification"] == "eligible" for item in bindings),
    }


def _submitted_pair(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"evidence_ref", "admission_ref"}:
        raise ValueError("admitted_evidence item must contain evidence_ref and admission_ref")
    evidence_ref = reference(value["evidence_ref"])
    admission_ref = value["admission_ref"]
    if (
        not isinstance(admission_ref, str)
        or not admission_ref.startswith(_ADMISSION_PREFIX)
        or len(admission_ref) != len(_ADMISSION_PREFIX) + 64
        or any(char not in "0123456789abcdef" for char in admission_ref[len(_ADMISSION_PREFIX):])
    ):
        raise ValueError("admission_ref is invalid")
    return evidence_ref, admission_ref


def _applicability(raw: Any) -> dict[str, Any]:
    try:
        value = orjson.loads(raw)
    except (orjson.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("stored evidence applicability is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("stored evidence applicability is invalid")
    return value


def _branch_identities(
    branch_row: Any, cycle_checkpoint: dict[str, Any] | None,
) -> dict[str, str]:
    checkpoint = cycle_checkpoint or {}
    return {
        "contract_hash": str(checkpoint.get("contract_hash") or ""),
        "methodology_hash": str(checkpoint.get("methodology_hash") or ""),
        "trial_plan_hash": str(
            branch_row["current_trial_plan_hash"] or checkpoint.get("trial_plan_hash") or ""
        ),
    }


def _validate_identity_scope(
    applicability: dict[str, Any], identities: dict[str, str],
) -> None:
    for field in ("contract_hash", "methodology_hash", "trial_plan_hash"):
        expected = str(applicability.get(field) or "").removeprefix("sha256:")
        if not expected:
            continue
        actual = identities[field].removeprefix("sha256:")
        if not actual or actual != expected:
            raise ValueError(
                f"evidence applicability.{field} does not match this Graph branch"
            )
