"""Persistent, content-addressed research Evidence objects."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from server.services.research_graph.research_cycle.evidence import validate_agent_evidence_envelope
from server.services.research_evidence_scope import (
    canonical,
    check_identity_scope,
    reference,
    text,
    validate_applicability,
)


def ensure_schema(conn) -> None:
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
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT evidence_ref, evidence_kind, envelope_json, applicability_json, owner, created_at "
            "FROM research_evidence_objects WHERE evidence_ref=? AND owner=?",
            (evidence_ref, owner),
        ).fetchone()
    if row is None:
        raise KeyError("research evidence not found")
    return {
        "evidence_ref": row["evidence_ref"], "evidence_kind": row["evidence_kind"],
        "envelope": json.loads(row["envelope_json"]),
        "applicability": json.loads(row["applicability_json"]),
        "owner": row["owner"], "created_at": float(row["created_at"]),
    }


def admit_evidence(*, owner: str, evidence_ref: str, environment_ref: str,
                   subject_ref: str, qualification: str, note: str = "") -> dict[str, Any]:
    if qualification not in {"unreviewed", "eligible", "limited", "rejected"}:
        raise ValueError("invalid evidence qualification")
    reference(evidence_ref)
    text(environment_ref, "environment_ref")
    text(subject_ref, "subject_ref")
    text(note, "note", allow_empty=True, maximum=1000)
    values = {"evidence_ref": evidence_ref, "environment_ref": environment_ref,
              "subject_ref": subject_ref, "qualification": qualification, "note": note}
    admission_ref = "admission:" + hashlib.sha256(canonical(values).encode()).hexdigest()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        exists = conn.execute(
            "SELECT 1 FROM research_evidence_objects WHERE evidence_ref=? AND owner=?",
            (evidence_ref, owner),
        ).fetchone()
        if exists is None:
            raise KeyError("research evidence not found")
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
