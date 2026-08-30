"""Facet catalog and scope-first Evidence search."""

from __future__ import annotations

from datetime import date
import json
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from .schema import ensure_schema
from .tags import list_tags
from .validation import EVIDENCE_KINDS, SOURCE_KINDS


def list_facets(*, owner: str) -> dict[str, list[dict[str, Any]]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        evidence_counts = {
            row["evidence_kind"]: int(row["count"])
            for row in conn.execute(
                """SELECT e.evidence_kind, COUNT(*) AS count
                   FROM research_fragment_evidence_objects e
                   LEFT JOIN research_evidence_lifecycle l
                     ON l.owner=e.owner AND l.evidence_ref=e.evidence_ref
                   WHERE e.owner=?
                     AND COALESCE(l.status, 'active')='active'
                   GROUP BY e.evidence_kind""",
                (owner,),
            ).fetchall()
        }
        source_counts = {
            row["source_kind"]: int(row["count"])
            for row in conn.execute(
                """SELECT source_kind, COUNT(*) AS count
                   FROM research_evidence_sources
                   WHERE owner=? GROUP BY source_kind""",
                (owner,),
            ).fetchall()
        }
    system = [
        {
            "facet_ref": f"evidence_kind:{kind}",
            "facet_group": "evidence_kind",
            "title": kind,
            "count": evidence_counts.get(kind, 0),
            "mutable": False,
        }
        for kind in sorted(EVIDENCE_KINDS)
    ] + [
        {
            "facet_ref": f"source_kind:{kind}",
            "facet_group": "source_kind",
            "title": kind,
            "count": source_counts.get(kind, 0),
            "mutable": False,
        }
        for kind in sorted(SOURCE_KINDS)
    ]
    agent = [
        {
            "facet_ref": tag["tag_ref"],
            "facet_group": "agent_tag",
            "title": tag["title_zh"],
            "description_zh": tag["description_zh"],
            "count": tag["evidence_count"],
            "mutable": True,
        }
        for tag in list_tags(owner=owner)
    ]
    return {"system": system, "agent": agent}


def search_evidence(
    *,
    owner: str,
    product_refs: list[str] | None = None,
    factor_refs: list[str] | None = None,
    sample_refs: list[str] | None = None,
    time_window: dict[str, str] | None = None,
    evidence_kinds: list[str] | None = None,
    source_kinds: list[str] | None = None,
    tag_refs: list[str] | None = None,
    text: str = "",
    limit: int = 20,
    include_excluded: bool = False,
) -> dict[str, Any]:
    requested_tags = list(dict.fromkeys(tag_refs or []))
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """SELECT e.*,
                      COALESCE(l.status, 'active') AS lifecycle_status
               FROM research_fragment_evidence_objects e
               LEFT JOIN research_evidence_lifecycle l
                 ON l.owner=e.owner AND l.evidence_ref=e.evidence_ref
               WHERE e.owner=?
                 AND (?=1 OR COALESCE(l.status, 'active')='active')
               ORDER BY e.created_at DESC LIMIT 500""",
            (owner, 1 if include_excluded else 0),
        ).fetchall()
        tag_rows = conn.execute(
            """SELECT evidence_ref, tag_ref
               FROM research_evidence_object_tags WHERE owner=?""",
            (owner,),
        ).fetchall()
        source_rows = conn.execute(
            """SELECT DISTINCT e.evidence_ref, s.source_kind
               FROM research_fragment_evidence_objects e
               JOIN json_each(e.fragment_refs_json) refs
               JOIN research_evidence_fragments f
                 ON f.fragment_ref=refs.value AND f.owner=e.owner
               JOIN research_evidence_sources s
                 ON s.source_ref=f.source_ref AND s.owner=e.owner
               WHERE e.owner=?""",
            (owner,),
        ).fetchall()
    tags_by_evidence: dict[str, set[str]] = {}
    for row in tag_rows:
        tags_by_evidence.setdefault(row["evidence_ref"], set()).add(
            row["tag_ref"]
        )
    sources_by_evidence: dict[str, set[str]] = {}
    for row in source_rows:
        sources_by_evidence.setdefault(row["evidence_ref"], set()).add(
            row["source_kind"]
        )
    items = []
    for row in rows:
        lifecycle_status = str(row["lifecycle_status"])
        if lifecycle_status == "excluded" and not include_excluded:
            continue
        scope = json.loads(row["applicability_json"])
        tags = tags_by_evidence.get(row["evidence_ref"], set())
        sources = sources_by_evidence.get(row["evidence_ref"], set())
        compatible, matched, conflicts = _compatible(
            scope=scope,
            product_refs=product_refs or [],
            factor_refs=factor_refs or [],
            sample_refs=sample_refs or [],
            time_window=time_window,
        )
        if not compatible:
            continue
        if evidence_kinds and row["evidence_kind"] not in evidence_kinds:
            continue
        if source_kinds and not set(source_kinds).issubset(sources):
            continue
        if requested_tags and not set(requested_tags).issubset(tags):
            continue
        haystack = " ".join((
            row["title_zh"],
            row["description_zh"],
            row["claim_summary"],
        )).casefold()
        if text.strip() and text.strip().casefold() not in haystack:
            continue
        if evidence_kinds:
            matched.append("evidence_kind")
        if source_kinds:
            matched.append("source_kind")
        if requested_tags:
            matched.append("agent_tag")
        if text.strip():
            matched.append("text")
        items.append({
            "evidence_ref": row["evidence_ref"],
            "title_zh": row["title_zh"],
            "description_zh": row["description_zh"],
            "evidence_kind": row["evidence_kind"],
            "source_kinds": sorted(sources),
            "tag_refs": sorted(tags),
            "matched_by": matched,
            "scope_compatibility": "compatible",
            "conflicts": conflicts + json.loads(row["conflicts_json"]),
            "limitations": json.loads(row["limitations_json"]),
            "lifecycle_status": lifecycle_status,
        })
        if len(items) >= min(max(1, int(limit)), 100):
            break
    return {
        "items": items,
        "next_actions": [
            {
                "action": "inspect_evidence",
                "argv": [
                    "factortester", "research", "evidence", "get",
                    "<evidence_ref>", "--json",
                ],
            },
            {
                "action": "capture_source_if_no_match",
                "argv": [
                    "factortester", "research", "evidence", "source", "--help",
                ],
            },
        ],
    }


def _compatible(
    *,
    scope: dict[str, Any],
    product_refs: list[str],
    factor_refs: list[str],
    sample_refs: list[str],
    time_window: dict[str, str] | None,
) -> tuple[bool, list[str], list[str]]:
    matched: list[str] = []
    conflicts: list[str] = []
    for field, requested, label in (
        ("product_refs", product_refs, "product_ref"),
        ("factor_refs", factor_refs, "factor_ref"),
        ("sample_refs", sample_refs, "sample_ref"),
    ):
        if not requested:
            continue
        available = set(scope.get(field) or [])
        if not set(requested).issubset(available):
            conflicts.append(f"{label} outside evidence scope")
            return False, matched, conflicts
        matched.append(label)
    if time_window:
        available = scope.get("time_window")
        if not isinstance(available, dict) or not _contains(
            available, time_window,
        ):
            conflicts.append("time_window outside evidence scope")
            return False, matched, conflicts
        matched.append("time_window")
    return True, matched, conflicts


def _contains(available: dict[str, str], requested: dict[str, str]) -> bool:
    try:
        available_start = date.fromisoformat(str(available["start"])[:10])
        available_end = date.fromisoformat(str(available["end"])[:10])
        requested_start = date.fromisoformat(str(requested["start"])[:10])
        requested_end = date.fromisoformat(str(requested["end"])[:10])
    except (KeyError, TypeError, ValueError):
        return False
    return available_start <= requested_start <= requested_end <= available_end
