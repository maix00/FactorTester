"""Paged metadata projection for the user Evidence catalog."""

from __future__ import annotations

import json
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from .schema import ensure_schema


def list_evidence_page(
    *,
    owner: str,
    page: int = 1,
    page_size: int = 20,
    text: str = "",
    include_excluded: bool = False,
) -> dict[str, Any]:
    """Return one metadata-only page without reading fragment contents."""
    selected_page = max(1, int(page))
    selected_size = min(max(1, int(page_size)), 100)
    query = str(text or "").strip().casefold()
    like = f"%{_escape_like(query)}%"
    lifecycle_clause = (
        "1=1" if include_excluded
        else "COALESCE(l.status, 'active')='active'"
    )
    text_clause = """(
        ?='' OR lower(e.title_zh) LIKE ? ESCAPE '\\'
             OR lower(e.description_zh) LIKE ? ESCAPE '\\'
             OR lower(e.claim_summary) LIKE ? ESCAPE '\\'
    )"""
    parameters = (owner, query, like, like, like)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        total = int(conn.execute(
            f"""SELECT COUNT(*) AS count
                  FROM research_fragment_evidence_objects e
                  LEFT JOIN research_evidence_lifecycle l
                    ON l.owner=e.owner AND l.evidence_ref=e.evidence_ref
                 WHERE e.owner=? AND {lifecycle_clause} AND {text_clause}""",
            parameters,
        ).fetchone()["count"])
        rows = conn.execute(
            f"""SELECT e.*,
                       COALESCE(l.status, 'active') AS lifecycle_status
                  FROM research_fragment_evidence_objects e
                  LEFT JOIN research_evidence_lifecycle l
                    ON l.owner=e.owner AND l.evidence_ref=e.evidence_ref
                 WHERE e.owner=? AND {lifecycle_clause} AND {text_clause}
                 ORDER BY e.created_at DESC, e.evidence_ref
                 LIMIT ? OFFSET ?""",
            parameters + (
                selected_size, (selected_page - 1) * selected_size,
            ),
        ).fetchall()
        evidence_refs = [str(row["evidence_ref"]) for row in rows]
        sources = _source_projection(conn, owner, evidence_refs)
        tags = _tag_projection(conn, owner, evidence_refs)
    items = [
        _list_item(row, sources=sources, tags=tags)
        for row in rows
    ]
    return {
        "items": items,
        "page": selected_page,
        "page_size": selected_size,
        "total": total,
        "has_previous": selected_page > 1,
        "has_next": selected_page * selected_size < total,
    }


def get_evidence_summary(*, owner: str, evidence_ref: str) -> dict[str, Any]:
    """Read one Evidence envelope without joining its fragments."""
    target = str(evidence_ref or "").strip()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        row = conn.execute(
            """SELECT e.*,
                      COALESCE(l.status, 'active') AS lifecycle_status
                 FROM research_fragment_evidence_objects e
                 LEFT JOIN research_evidence_lifecycle l
                   ON l.owner=e.owner AND l.evidence_ref=e.evidence_ref
                WHERE e.owner=? AND e.evidence_ref=?""",
            (owner, target),
        ).fetchone()
        if row is None:
            raise KeyError("research Evidence not found")
        sources = _source_projection(conn, owner, [target])
        tags = _tag_projection(conn, owner, [target])
    return _list_item(row, sources=sources, tags=tags)


def list_evidence_relationship_page(
    *, owner: str, evidence_ref: str, page: int = 1, page_size: int = 20,
) -> dict[str, Any]:
    """List Report consumers; Research is derived and Job is provenance."""
    selected_page = max(1, int(page))
    selected_size = min(max(1, int(page_size)), 100)
    target = str(evidence_ref or "").strip()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        exists = conn.execute(
            "SELECT 1 FROM research_fragment_evidence_objects "
            "WHERE owner=? AND evidence_ref=?",
            (owner, target),
        ).fetchone()
        if exists is None:
            raise KeyError("research Evidence not found")
        if not _table_exists(conn, "research_catalog_evidence_links"):
            return _empty_page(selected_page, selected_size)
        total = int(conn.execute(
            """SELECT COUNT(*) AS count
                 FROM research_catalog_evidence_links
                WHERE evidence_ref=? AND evidence_owner_ref=?
                  AND report_id<>'' AND status='active'""",
            (target, owner),
        ).fetchone()["count"])
        rows = conn.execute(
            """SELECT link.*,
                      research.title AS research_title,
                      report.title AS report_title
                 FROM research_catalog_evidence_links link
                 LEFT JOIN research_catalog_researches research
                   ON research.research_id=link.research_id
                 LEFT JOIN research_catalog_reports report
                   ON report.report_id=link.report_id
                WHERE link.evidence_ref=? AND link.evidence_owner_ref=?
                  AND link.report_id<>'' AND link.status='active'
                ORDER BY link.created_at DESC, link.link_ref
                LIMIT ? OFFSET ?""",
            (
                target, owner, selected_size,
                (selected_page - 1) * selected_size,
            ),
        ).fetchall()
    return {
        "items": [{
            "link_ref": str(row["link_ref"]),
            "research_id": str(row["research_id"]),
            "research_title": str(row["research_title"] or ""),
            "report_id": str(row["report_id"] or ""),
            "report_title": str(row["report_title"] or ""),
            "profile_ref": str(row["profile_ref"] or ""),
            "purpose": str(row["purpose"] or ""),
            "created_at": float(row["created_at"]),
        } for row in rows],
        "page": selected_page,
        "page_size": selected_size,
        "total": total,
        "has_previous": selected_page > 1,
        "has_next": selected_page * selected_size < total,
    }


def _source_projection(conn, owner: str, refs: list[str]) -> dict[str, dict]:
    if not refs:
        return {}
    placeholders = ",".join("?" for _ in refs)
    rows = conn.execute(
        f"""SELECT DISTINCT e.evidence_ref, s.source_kind, s.identity_json
              FROM research_fragment_evidence_objects e
              JOIN json_each(e.fragment_refs_json) selected
              JOIN research_evidence_fragments f
                ON f.fragment_ref=selected.value AND f.owner=e.owner
              JOIN research_evidence_sources s
                ON s.source_ref=f.source_ref AND s.owner=e.owner
             WHERE e.owner=? AND e.evidence_ref IN ({placeholders})""",
        (owner, *refs),
    ).fetchall()
    result: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        item = result.setdefault(
            str(row["evidence_ref"]), {
                "kinds": set(), "locations": set(), "job_refs": set(),
            },
        )
        item["kinds"].add(str(row["source_kind"]))
        identity = json.loads(row["identity_json"])
        location = str(
            identity.get("server_id")
            or identity.get("storage_server_id")
            or ("local" if row["source_kind"] == "file" else "")
        ).strip()
        if location:
            item["locations"].add(location)
        job_id = str(identity.get("job_id") or "").strip()
        if job_id:
            item["job_refs"].add(job_id)
    return result


def _tag_projection(conn, owner: str, refs: list[str]) -> dict[str, list[str]]:
    if not refs:
        return {}
    placeholders = ",".join("?" for _ in refs)
    rows = conn.execute(
        f"""SELECT evidence_ref, tag_ref
              FROM research_evidence_object_tags
             WHERE owner=? AND evidence_ref IN ({placeholders})
             ORDER BY tag_ref""",
        (owner, *refs),
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(str(row["evidence_ref"]), []).append(
            str(row["tag_ref"])
        )
    return result


def _list_item(row, *, sources: dict[str, dict], tags: dict[str, list[str]]) -> dict:
    evidence_ref = str(row["evidence_ref"])
    source = sources.get(evidence_ref, {
        "kinds": set(), "locations": set(), "job_refs": set(),
    })
    applicability = json.loads(row["applicability_json"])
    return {
        "evidence_ref": evidence_ref,
        "title_zh": str(row["title_zh"]),
        "description_zh": str(row["description_zh"]),
        "claim_summary": str(row["claim_summary"]),
        "evidence_kind": str(row["evidence_kind"]),
        "source_kinds": sorted(source["kinds"]),
        "source_locations": sorted(source["locations"]),
        "job_refs": sorted(source["job_refs"]),
        "applicable_objects": {
            "factor_refs": list(applicability.get("factor_refs") or []),
            "product_refs": list(applicability.get("product_refs") or []),
            "sample_refs": list(applicability.get("sample_refs") or []),
        },
        "applicable_environment": {
            "product_group_refs": list(
                applicability.get("product_group_refs") or []
            ),
            "data_source_refs": list(
                applicability.get("data_source_refs") or []
            ),
            "environment_refs": list(
                applicability.get("environment_refs") or []
            ),
            "source_refs": list(applicability.get("source_refs") or []),
            "time_window": applicability.get("time_window"),
        },
        "tag_refs": tags.get(evidence_ref, []),
        "lifecycle_status": str(row["lifecycle_status"]),
        "created_at": float(row["created_at"]),
        "access": {
            "can_view": True,
            "can_preview": True,
            "can_download": True,
            "can_manage": True,
            "access_basis": "owner",
        },
    }


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
    ).fetchone() is not None


def _empty_page(page: int, page_size: int) -> dict[str, Any]:
    return {
        "items": [], "page": page, "page_size": page_size, "total": 0,
        "has_previous": page > 1, "has_next": False,
    }


__all__ = [
    "get_evidence_summary", "list_evidence_page",
    "list_evidence_relationship_page",
]
