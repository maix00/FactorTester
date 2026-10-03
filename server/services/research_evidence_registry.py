"""Persistent, content-addressed research Evidence objects."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from server.services.research_evidence_envelope import validate_agent_evidence_envelope
from server.services.research_evidence_scope import (
    canonical,
    check_identity_scope,
    reference,
    text,
    validate_applicability,
)
from server.services.research_evidence_catalog.schema import (
    ensure_schema as ensure_catalog_schema,
)
from server.services.research_evidence_catalog.sources import (
    get_composed_evidence,
)
from server.services.research_evidence_catalog.lifecycle import (
    get_evidence_lifecycle,
    require_active_evidence,
)


def ensure_schema(conn) -> None:
    ensure_catalog_schema(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_evidence_objects (
            evidence_ref TEXT PRIMARY KEY, evidence_kind TEXT NOT NULL,
            envelope_hash TEXT NOT NULL UNIQUE, envelope_json TEXT NOT NULL,
            applicability_json TEXT NOT NULL, owner TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_evidence_admissions (
            admission_ref TEXT PRIMARY KEY, evidence_ref TEXT NOT NULL,
            environment_ref TEXT NOT NULL, subject_ref TEXT NOT NULL,
            qualification TEXT NOT NULL, note TEXT NOT NULL, owner TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(evidence_ref, environment_ref, subject_ref)
        )
    """)


def put_evidence(*, owner: str, envelope: Any, applicability: Any) -> dict[str, Any]:
    value = validate_agent_evidence_envelope(envelope)
    scope = validate_applicability(applicability)
    check_identity_scope(value, scope)
    envelope_hash = str(value["envelope_hash"])
    evidence_ref = f"evidence:{value['evidence_kind']}:sha256:{envelope_hash}"
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO research_evidence_objects VALUES (?, ?, ?, ?, ?, ?, ?)",
            (evidence_ref, value["evidence_kind"], envelope_hash,
             canonical(value), canonical(scope), owner, now),
        )
        row = conn.execute(
            "SELECT created_at FROM research_evidence_objects WHERE evidence_ref=?",
            (evidence_ref,),
        ).fetchone()
    return {
        "evidence_ref": evidence_ref, "evidence_kind": value["evidence_kind"],
        "envelope_hash": envelope_hash, "applicability": scope,
        "created_at": float(row["created_at"]),
    }


def get_evidence(*, owner: str, evidence_ref: str) -> dict[str, Any]:
    import json

    reference(evidence_ref)
    try:
        composed = get_composed_evidence(
            owner=owner, evidence_ref=evidence_ref,
        )
    except KeyError:
        composed = None
    if composed is not None:
        fragments = composed.pop("fragments")
        tags = composed.pop("tags")
        applicability = composed.pop("applicability")
        created_at = composed.pop("created_at")
        identity_refs = composed.pop("identity_refs")
        limitations = composed.pop("limitations")
        conflicts = composed.pop("conflicts")
        envelope = {
            "schema_version": 3,
            "envelope_id": evidence_ref,
            "evidence_kind": composed["evidence_kind"],
            "title": composed["title_zh"],
            "title_zh": composed["title_zh"],
            "description_zh": composed["description_zh"],
            "claim_summary": composed["claim_summary"],
            "fragment_refs": composed["fragment_refs"],
            "identity_refs": identity_refs,
            "metric_refs": [],
            "artifact_refs": [],
            "hypotheses_tested": 0,
            "stop_condition": None,
            "limitations": limitations,
            "conflicts": conflicts,
        }
        return {
            "evidence_ref": evidence_ref,
            "evidence_kind": composed["evidence_kind"],
            "envelope": envelope,
            "applicability": applicability,
            "fragments": fragments,
            "tags": tags,
            "owner": owner,
            "created_at": created_at,
            "lifecycle": get_evidence_lifecycle(
                owner=owner, evidence_ref=evidence_ref,
            ),
        }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT evidence_ref, evidence_kind, envelope_json, applicability_json, owner, created_at "
            "FROM research_evidence_objects WHERE evidence_ref=? AND owner=?",
            (evidence_ref, owner),
        ).fetchone()
    if row is None:
        raise KeyError("research evidence not found")
    value = {
        "evidence_ref": row["evidence_ref"], "evidence_kind": row["evidence_kind"],
        "envelope": json.loads(row["envelope_json"]),
        "applicability": json.loads(row["applicability_json"]),
        "migration_status": "unverifiable_fragment",
        "fragments": [],
        "tags": [],
        "owner": row["owner"], "created_at": float(row["created_at"]),
    }
    value["lifecycle"] = get_evidence_lifecycle(
        owner=owner, evidence_ref=evidence_ref,
    )
    return value


def admit_evidence(*, owner: str, evidence_ref: str, environment_ref: str,
                   subject_ref: str, qualification: str, note: str = "") -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        return _admit_evidence(
            conn, owner=owner, evidence_ref=evidence_ref,
            environment_ref=environment_ref, subject_ref=subject_ref,
            qualification=qualification, note=note,
        )


def _admit_evidence(
    conn, *, owner: str, evidence_ref: str, environment_ref: str,
    subject_ref: str, qualification: str, note: str,
) -> dict[str, Any]:
    if qualification not in {"unreviewed", "eligible", "limited", "rejected"}:
        raise ValueError("invalid evidence qualification")
    reference(evidence_ref)
    text(environment_ref, "environment_ref")
    text(subject_ref, "subject_ref")
    text(note, "note", allow_empty=True, maximum=1000)
    values = {"evidence_ref": evidence_ref, "environment_ref": environment_ref,
              "subject_ref": subject_ref, "qualification": qualification, "note": note}
    admission_ref = "admission:" + hashlib.sha256(canonical(values).encode()).hexdigest()
    exists = conn.execute(
        """SELECT 1 FROM research_evidence_objects
           WHERE evidence_ref=? AND owner=?
           UNION ALL
           SELECT 1 FROM research_fragment_evidence_objects
           WHERE evidence_ref=? AND owner=?
           LIMIT 1""",
        (evidence_ref, owner, evidence_ref, owner),
    ).fetchone()
    if exists is None:
        raise KeyError("research evidence not found")
    require_active_evidence(
        conn, owner=owner, evidence_ref=evidence_ref,
    )
    now = time.time()
    conn.execute(
        """INSERT INTO research_evidence_admissions
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_ref, environment_ref, subject_ref) DO UPDATE SET
              admission_ref=excluded.admission_ref, qualification=excluded.qualification,
              note=excluded.note, owner=excluded.owner, created_at=excluded.created_at""",
        (admission_ref, evidence_ref, environment_ref, subject_ref,
         qualification, note, owner, now),
    )
    return {"admission_ref": admission_ref, **values}
