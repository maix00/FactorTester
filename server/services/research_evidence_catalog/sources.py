"""Immutable source captures, fragments and composed Evidence objects."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import settings as Settings
from server.services.research_evidence_scope import (
    check_identity_scope,
    validate_applicability,
)
from tools.data.sqlite.db import connect_sqlite

from .provenance import validate_file_provenance
from .schema import ensure_schema
from .validation import (
    canonical,
    digest,
    fragment_reference,
    object_value,
    required_text,
    sha256,
    source_reference,
    text_list,
    validate_identity,
    validate_selector,
)
from .validation import (
    evidence_kind as validate_evidence_kind,
)
from .validation import (
    source_kind as validate_source_kind,
)


def capture_job_source(*, owner: str, job_id: str) -> dict[str, Any]:
    """Capture one server-owned terminal JobAttempt as an immutable source."""
    from server.jobs.repository import JobRepository
    from server.jobs.states import TERMINAL_STATUSES

    detail = JobRepository().load_detail(job_id, owner=owner)
    if detail is None:
        raise KeyError("research job not found")
    job = detail["job"]
    if job.status not in TERMINAL_STATUSES:
        raise ValueError("JobAttempt must be terminal before evidence capture")
    server_id = str(
        os.environ.get("FACTORTESTER_SERVER_ID") or "local"
    ).strip()
    artifacts = [
        {
            key: item.get(key)
            for key in ("name", "filename", "content_hash", "content_type")
            if item.get(key) not in (None, "")
        }
        for item in detail.get("active_artifacts") or []
        if isinstance(item, dict)
    ]
    snapshot = {
        "job_id": job.job_id,
        "server_id": server_id,
        "run_id": job.run_id,
        "attempt": job.attempt,
        "status": job.status.value,
        "service_port": job.service_port,
        "kind": job.kind,
        "job_spec_hash": job.job_spec_hash,
        "run_spec_hash": job.run_spec_hash,
        "result_summary": job.result_summary,
        "error": job.error,
        "terminal_assurance": (
            job.terminal_assurance.to_dict()
            if job.terminal_assurance is not None else None
        ),
        "artifacts": artifacts,
    }
    source = put_source_capture(
        owner=owner,
        source_kind="job",
        identity={
            "job_id": job.job_id,
            "server_id": server_id,
            "run_id": job.run_id,
            "attempt": job.attempt,
            "service_port": job.service_port,
        },
        content_hash=digest(snapshot),
        audit=snapshot,
        captured_at=job.finished_at or job.updated_at or time.time(),
    )
    source["available_fragments"] = _job_fragment_catalog(snapshot)
    return source


def put_source_capture(
    *,
    owner: str,
    source_kind: str,
    identity: Any,
    content_hash: str,
    audit: Any,
    captured_at: float | None = None,
) -> dict[str, Any]:
    kind = validate_source_kind(source_kind)
    normalized_identity = object_value(identity, "identity")
    normalized_hash = sha256(content_hash, "content_hash")
    normalized_audit = object_value(audit, "audit", allow_empty=True)
    identity_payload = {
        "owner": required_text(owner, "owner", maximum=256),
        "source_kind": kind,
        "identity": normalized_identity,
        "content_hash": normalized_hash,
    }
    source_ref = f"source:{kind}:sha256:{digest(identity_payload)}"
    timestamp = time.time() if captured_at is None else float(captured_at)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        conn.execute(
            """INSERT OR IGNORE INTO research_evidence_sources
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                source_ref,
                kind,
                canonical(normalized_identity),
                normalized_hash,
                canonical(normalized_audit),
                owner,
                timestamp,
            ),
        )
        row = conn.execute(
            "SELECT * FROM research_evidence_sources "
            "WHERE source_ref=? AND owner=?",
            (source_ref, owner),
        ).fetchone()
    if row is None:
        raise KeyError("source capture belongs to another owner")
    return _source_row(row)


def get_source_capture(*, owner: str, source_ref: str) -> dict[str, Any]:
    source_reference(source_ref)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM research_evidence_sources "
            "WHERE source_ref=? AND owner=?",
            (source_ref, owner),
        ).fetchone()
    if row is None:
        raise KeyError("research evidence source not found")
    return _source_row(row)


def put_source_fragment(
    *,
    owner: str,
    source_ref: str,
    selector: Any,
    fragment_hash: str,
    title_zh: str,
    summary_zh: str,
    preview: Any | None = None,
    created_at: float | None = None,
) -> dict[str, Any]:
    source = get_source_capture(owner=owner, source_ref=source_ref)
    normalized_selector = validate_selector(source["source_kind"], selector)
    normalized_hash = sha256(fragment_hash, "fragment_hash")
    title = required_text(
        title_zh, "title_zh", maximum=32, chinese=True,
    )
    summary = required_text(
        summary_zh, "summary_zh", maximum=240, chinese=True,
    )
    normalized_preview = object_value(
        preview or {}, "preview", allow_empty=True,
    )
    identity = {
        "source_ref": source_ref,
        "selector": normalized_selector,
        "fragment_hash": normalized_hash,
    }
    fragment_ref = (
        f"fragment:{source['source_kind']}:sha256:{digest(identity)}"
    )
    timestamp = time.time() if created_at is None else float(created_at)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        conn.execute(
            """INSERT OR IGNORE INTO research_evidence_fragments
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fragment_ref,
                source_ref,
                canonical(normalized_selector),
                normalized_hash,
                title,
                summary,
                canonical(normalized_preview),
                owner,
                timestamp,
            ),
        )
        row = conn.execute(
            "SELECT * FROM research_evidence_fragments "
            "WHERE fragment_ref=? AND owner=?",
            (fragment_ref, owner),
        ).fetchone()
    if row is None:
        raise KeyError("source fragment belongs to another owner")
    return _fragment_row(row)


def list_source_fragments(
    *, owner: str, source_ref: str,
) -> list[dict[str, Any]]:
    source_reference(source_ref)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT * FROM research_evidence_fragments "
            "WHERE owner=? AND source_ref=? ORDER BY created_at, rowid",
            (owner, source_ref),
        ).fetchall()
    return [_fragment_row(row) for row in rows]


def create_evidence(
    *,
    owner: str,
    evidence_kind: str,
    fragment_refs: list[str],
    title_zh: str,
    description_zh: str,
    claim_summary: str,
    applicability: Any,
    identity_refs: Any,
    limitations: Any,
    conflicts: Any,
    created_at: float | None = None,
) -> dict[str, Any]:
    kind = validate_evidence_kind(evidence_kind)
    refs = _fragment_refs(fragment_refs)
    title = required_text(
        title_zh, "title_zh", maximum=32, chinese=True,
    )
    description = required_text(
        description_zh, "description_zh", maximum=512, chinese=True,
    )
    claim = required_text(
        claim_summary, "claim_summary", maximum=512,
    )
    scope = validate_applicability(applicability)
    identity = validate_identity(kind, identity_refs)
    check_identity_scope({"identity_refs": identity}, scope)
    normalized_limitations = text_list(limitations, "limitations")
    normalized_conflicts = text_list(conflicts, "conflicts")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        found = conn.execute(
            f"""SELECT f.fragment_ref, s.source_kind, s.audit_json
                FROM research_evidence_fragments f
                JOIN research_evidence_sources s
                  ON s.source_ref=f.source_ref AND s.owner=f.owner
                WHERE f.owner=? AND f.fragment_ref IN (
                    {','.join('?' for _ in refs)}
                )""",
            (owner, *refs),
        ).fetchall()
        if {row["fragment_ref"] for row in found} != set(refs):
            raise KeyError("one or more research evidence fragments not found")
        for row in found:
            if row["source_kind"] != "file":
                continue
            audit = json.loads(row["audit_json"])
            try:
                validate_file_provenance(audit.get("provenance"))
            except ValueError as exc:
                raise ValueError(
                    "local file fragments require authoritative-download or "
                    "Git-blob provenance; Agent-authored reports are not "
                    "Evidence sources"
                ) from exc
        immutable = {
            "owner": required_text(owner, "owner", maximum=256),
            "evidence_kind": kind,
            "fragment_refs": refs,
            "title_zh": title,
            "description_zh": description,
            "claim_summary": claim,
            "applicability": scope,
            "identity_refs": identity,
            "limitations": normalized_limitations,
            "conflicts": normalized_conflicts,
        }
        evidence_ref = f"evidence:{kind}:sha256:{digest(immutable)}"
        timestamp = time.time() if created_at is None else float(created_at)
        conn.execute(
            """INSERT OR IGNORE INTO research_fragment_evidence_objects
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evidence_ref,
                kind,
                canonical(refs),
                title,
                description,
                claim,
                canonical(scope),
                canonical(identity),
                canonical(normalized_limitations),
                canonical(normalized_conflicts),
                owner,
                timestamp,
            ),
        )
    return get_composed_evidence(owner=owner, evidence_ref=evidence_ref)


def get_composed_evidence(
    *, owner: str, evidence_ref: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM research_fragment_evidence_objects "
            "WHERE evidence_ref=? AND owner=?",
            (evidence_ref, owner),
        ).fetchone()
        if row is None:
            raise KeyError("fragment-bound research evidence not found")
        fragment_refs = json.loads(row["fragment_refs_json"])
        fragments = conn.execute(
            f"""SELECT f.*, s.source_kind, s.identity_json, s.audit_json,
                       s.content_hash AS source_content_hash,
                       s.captured_at
                FROM research_evidence_fragments f
                JOIN research_evidence_sources s
                  ON s.source_ref=f.source_ref AND s.owner=f.owner
                WHERE f.owner=? AND f.fragment_ref IN (
                    {','.join('?' for _ in fragment_refs)}
                )""",
            (owner, *fragment_refs),
        ).fetchall()
        tags = conn.execute(
            """SELECT t.* FROM research_evidence_tags t
               JOIN research_evidence_object_tags et
                 ON et.tag_ref=t.tag_ref AND et.owner=t.owner
               WHERE et.owner=? AND et.evidence_ref=?
               ORDER BY t.title_zh""",
            (owner, evidence_ref),
        ).fetchall()
    by_ref = {
        fragment["fragment_ref"]: _fragment_with_source_row(fragment)
        for fragment in fragments
    }
    return {
        "evidence_ref": row["evidence_ref"],
        "evidence_kind": row["evidence_kind"],
        "fragment_refs": fragment_refs,
        "fragments": [by_ref[ref] for ref in fragment_refs],
        "title_zh": row["title_zh"],
        "description_zh": row["description_zh"],
        "claim_summary": row["claim_summary"],
        "applicability": json.loads(row["applicability_json"]),
        "identity_refs": json.loads(row["identity_refs_json"]),
        "limitations": json.loads(row["limitations_json"]),
        "conflicts": json.loads(row["conflicts_json"]),
        "tags": [
            {
                "tag_ref": tag["tag_ref"],
                "title_zh": tag["title_zh"],
                "description_zh": tag["description_zh"],
                "status": tag["status"],
            }
            for tag in tags
        ],
        "created_at": float(row["created_at"]),
    }


def find_job_evidence(
    *, owner: str, job_id: str,
) -> dict[str, Any] | None:
    """Return the latest fragment-bound Evidence composed from one Job."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        row = conn.execute(
            """SELECT DISTINCT e.evidence_ref
               FROM research_fragment_evidence_objects e
               JOIN json_each(e.fragment_refs_json) refs
               JOIN research_evidence_fragments f
                 ON f.fragment_ref=refs.value AND f.owner=e.owner
               JOIN research_evidence_sources s
                 ON s.source_ref=f.source_ref AND s.owner=e.owner
               LEFT JOIN research_evidence_lifecycle l
                 ON l.evidence_ref=e.evidence_ref AND l.owner=e.owner
               WHERE e.owner=? AND s.source_kind='job'
                 AND json_extract(s.identity_json, '$.job_id')=?
                 AND COALESCE(l.status, 'active')='active'
               ORDER BY e.created_at DESC LIMIT 1""",
            (owner, job_id),
        ).fetchone()
    if row is None:
        return None
    return get_composed_evidence(
        owner=owner, evidence_ref=str(row["evidence_ref"]),
    )


def _fragment_refs(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("fragment_refs must be a non-empty array")
    refs = list(dict.fromkeys(fragment_reference(item) for item in value))
    return refs


def _job_fragment_catalog(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items = [{
        "selector": {"field": "status"},
        "title_zh": "任务终态",
        "preview": {"status": snapshot["status"]},
    }]
    if snapshot.get("result_summary") is not None:
        items.append({
            "selector": {"json_pointer": "/result_summary"},
            "title_zh": "任务结果摘要",
            "preview": snapshot["result_summary"],
        })
    if snapshot.get("terminal_assurance") is not None:
        items.append({
            "selector": {"json_pointer": "/terminal_assurance"},
            "title_zh": "任务终态校验",
            "preview": snapshot["terminal_assurance"],
        })
    for artifact in snapshot.get("artifacts") or []:
        artifact_name = str(
            artifact.get("name") or artifact.get("filename") or ""
        )
        items.append({
            "selector": {"artifact_ref": artifact_name},
            "title_zh": _job_artifact_title(artifact_name),
            "preview": artifact,
        })
    return items


def _job_artifact_title(name: str) -> str:
    titles = {
        "net_returns": "净收益序列",
        "net_return_series": "净收益序列",
        "equity_curve_report": "权益曲线报告",
        "equity_curve_receipt": "权益曲线校验回执",
    }
    return titles.get(name, ("任务生成物 " + name).strip())[:32]


def _source_row(row) -> dict[str, Any]:
    return {
        "source_ref": row["source_ref"],
        "source_kind": row["source_kind"],
        "identity": json.loads(row["identity_json"]),
        "content_hash": row["content_hash"],
        "audit": json.loads(row["audit_json"]),
        "captured_at": float(row["captured_at"]),
    }


def _fragment_row(row) -> dict[str, Any]:
    return {
        "fragment_ref": row["fragment_ref"],
        "source_ref": row["source_ref"],
        "selector": json.loads(row["selector_json"]),
        "fragment_hash": row["fragment_hash"],
        "title_zh": row["title_zh"],
        "summary_zh": row["summary_zh"],
        "preview": json.loads(row["preview_json"]),
        "created_at": float(row["created_at"]),
    }


def _fragment_with_source_row(row) -> dict[str, Any]:
    value = _fragment_row(row)
    value["source"] = {
        "source_kind": row["source_kind"],
        "identity": json.loads(row["identity_json"]),
        "content_hash": row["source_content_hash"],
        "audit": json.loads(row["audit_json"]),
        "captured_at": float(row["captured_at"]),
    }
    return value
