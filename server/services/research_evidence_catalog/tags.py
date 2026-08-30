"""User-scoped Agent tag governance for reusable Evidence."""

from __future__ import annotations

from difflib import SequenceMatcher
import json
import time
from typing import Any
import uuid

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from .lifecycle import require_active_evidence
from .schema import (
    bump_catalog_revision,
    catalog_revision,
    ensure_schema,
)
from .validation import profile_reference, required_text


_PROPOSAL_TTL_SECONDS = 15 * 60


def propose_tag(
    *,
    owner: str,
    title_zh: str,
    description_zh: str,
    created_by_profile_ref: str,
    distinct_reason: str = "",
) -> dict[str, Any]:
    title = required_text(title_zh, "title_zh", maximum=24, chinese=True)
    description = required_text(
        description_zh, "description_zh", maximum=240, chinese=True,
    )
    profile = profile_reference(created_by_profile_ref)
    normalized = _normalize(title)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        revision = catalog_revision(conn, owner)
        rows = conn.execute(
            "SELECT * FROM research_evidence_tags "
            "WHERE owner=? AND status='active' ORDER BY title_zh",
            (owner,),
        ).fetchall()
        candidates = [
            _tag_row(row)
            for row in rows
            if (
                row["normalized_title"] == normalized
                or SequenceMatcher(
                    None, row["normalized_title"], normalized,
                ).ratio() >= 0.72
            )
        ]
        reason = distinct_reason.strip()
        can_create = not candidates or bool(reason)
        token = uuid.uuid4().hex if can_create else None
        payload = {
            "title_zh": title,
            "normalized_title": normalized,
            "description_zh": description,
            "created_by_profile_ref": profile,
            "distinct_reason": reason,
        }
        if token:
            conn.execute(
                """INSERT INTO research_evidence_tag_proposals
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    token,
                    owner,
                    revision,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    json.dumps(candidates, ensure_ascii=False, sort_keys=True),
                    time.time(),
                ),
            )
    return {
        "proposal_token": token,
        "catalog_revision": revision,
        "candidates": candidates,
        "next_actions": (
            [{
                "action": "create_tag",
                "argv": [
                    "factortester", "research", "evidence", "tag", "create",
                    "--proposal-token", token,
                ],
            }]
            if token else [{
                "action": "reuse_tag_or_explain_distinction",
                "argv": [
                    "factortester", "research", "evidence", "tag", "propose",
                    "--distinct-reason", "<区别说明>",
                ],
            }]
        ),
    }


def create_tag(*, owner: str, proposal_token: str) -> dict[str, Any]:
    token = required_text(
        proposal_token, "proposal_token", maximum=128,
    )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM research_evidence_tag_proposals "
            "WHERE proposal_token=? AND owner=?",
            (token, owner),
        ).fetchone()
        if row is None:
            raise KeyError("tag proposal not found")
        if time.time() - float(row["created_at"]) > _PROPOSAL_TTL_SECONDS:
            raise ValueError("tag proposal expired")
        if int(row["catalog_revision"]) != catalog_revision(conn, owner):
            raise ValueError("tag catalog changed; propose the tag again")
        payload = json.loads(row["payload_json"])
        tag_ref = f"tag:{uuid.uuid4().hex}"
        now = time.time()
        conn.execute(
            """INSERT INTO research_evidence_tags
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
            (
                tag_ref,
                payload["title_zh"],
                payload["normalized_title"],
                payload["description_zh"],
                payload["created_by_profile_ref"],
                owner,
                now,
                now,
            ),
        )
        conn.execute(
            "DELETE FROM research_evidence_tag_proposals "
            "WHERE proposal_token=?",
            (token,),
        )
        revision = bump_catalog_revision(conn, owner)
    return {
        "tag_ref": tag_ref,
        "title_zh": payload["title_zh"],
        "description_zh": payload["description_zh"],
        "created_by_profile_ref": payload["created_by_profile_ref"],
        "status": "active",
        "catalog_revision": revision,
    }


def list_tags(
    *, owner: str, include_retired: bool = False,
) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        where = "" if include_retired else "AND t.status='active'"
        rows = conn.execute(
            f"""SELECT t.*,
                       COUNT(CASE
                         WHEN COALESCE(l.status, 'active')='active'
                         THEN et.evidence_ref
                       END) AS evidence_count
                FROM research_evidence_tags t
                LEFT JOIN research_evidence_object_tags et
                  ON et.tag_ref=t.tag_ref AND et.owner=t.owner
                LEFT JOIN research_evidence_lifecycle l
                  ON l.evidence_ref=et.evidence_ref AND l.owner=et.owner
                WHERE t.owner=? {where}
                GROUP BY t.tag_ref
                ORDER BY t.title_zh""",
            (owner,),
        ).fetchall()
    return [
        {**_tag_row(row), "evidence_count": int(row["evidence_count"])}
        for row in rows
    ]


def update_tag(
    *,
    owner: str,
    tag_ref: str,
    title_zh: str,
    description_zh: str,
) -> dict[str, Any]:
    title = required_text(title_zh, "title_zh", maximum=24, chinese=True)
    description = required_text(
        description_zh, "description_zh", maximum=240, chinese=True,
    )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        cursor = conn.execute(
            """UPDATE research_evidence_tags
               SET title_zh=?, normalized_title=?, description_zh=?,
                   updated_at=?
               WHERE owner=? AND tag_ref=? AND status='active'""",
            (
                title,
                _normalize(title),
                description,
                time.time(),
                owner,
                tag_ref,
            ),
        )
        if cursor.rowcount != 1:
            raise KeyError("active evidence tag not found")
        revision = bump_catalog_revision(conn, owner)
    return {
        "tag_ref": tag_ref,
        "title_zh": title,
        "description_zh": description,
        "status": "active",
        "catalog_revision": revision,
    }


def retire_tag(*, owner: str, tag_ref: str) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        cursor = conn.execute(
            """UPDATE research_evidence_tags
               SET status='retired', updated_at=?
               WHERE owner=? AND tag_ref=? AND status='active'""",
            (time.time(), owner, tag_ref),
        )
        if cursor.rowcount != 1:
            raise KeyError("active evidence tag not found")
        revision = bump_catalog_revision(conn, owner)
    return {
        "tag_ref": tag_ref,
        "status": "retired",
        "catalog_revision": revision,
    }


def attach_tag(
    *, owner: str, evidence_ref: str, tag_ref: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        evidence = conn.execute(
            "SELECT 1 FROM research_fragment_evidence_objects "
            "WHERE owner=? AND evidence_ref=?",
            (owner, evidence_ref),
        ).fetchone()
        tag = conn.execute(
            "SELECT 1 FROM research_evidence_tags "
            "WHERE owner=? AND tag_ref=? AND status='active'",
            (owner, tag_ref),
        ).fetchone()
        if evidence is None:
            raise KeyError("fragment-bound research evidence not found")
        if tag is None:
            raise KeyError("active evidence tag not found")
        require_active_evidence(
            conn, owner=owner, evidence_ref=evidence_ref,
        )
        conn.execute(
            """INSERT OR IGNORE INTO research_evidence_object_tags
               VALUES (?, ?, ?, ?)""",
            (evidence_ref, tag_ref, owner, time.time()),
        )
        revision = bump_catalog_revision(conn, owner)
    return {
        "evidence_ref": evidence_ref,
        "tag_ref": tag_ref,
        "catalog_revision": revision,
    }


def detach_tag(
    *, owner: str, evidence_ref: str, tag_ref: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        conn.execute(
            "DELETE FROM research_evidence_object_tags "
            "WHERE owner=? AND evidence_ref=? AND tag_ref=?",
            (owner, evidence_ref, tag_ref),
        )
        revision = bump_catalog_revision(conn, owner)
    return {
        "evidence_ref": evidence_ref,
        "tag_ref": tag_ref,
        "catalog_revision": revision,
    }


def _tag_row(row) -> dict[str, Any]:
    return {
        "tag_ref": row["tag_ref"],
        "title_zh": row["title_zh"],
        "description_zh": row["description_zh"],
        "created_by_profile_ref": row["created_by_profile_ref"],
        "status": row["status"],
    }


def _normalize(value: str) -> str:
    return "".join(value.casefold().split())
