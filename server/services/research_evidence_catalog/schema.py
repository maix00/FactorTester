"""SQLite schema for source, fragment, Evidence and tag catalog records."""

from __future__ import annotations


def ensure_schema(conn) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS research_evidence_sources (
            source_ref TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            identity_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            audit_json TEXT NOT NULL,
            owner TEXT NOT NULL,
            captured_at REAL NOT NULL,
            UNIQUE(owner, source_kind, identity_json, content_hash)
        );
        CREATE TABLE IF NOT EXISTS research_evidence_fragments (
            fragment_ref TEXT PRIMARY KEY,
            source_ref TEXT NOT NULL,
            selector_json TEXT NOT NULL,
            fragment_hash TEXT NOT NULL,
            title_zh TEXT NOT NULL,
            summary_zh TEXT NOT NULL,
            preview_json TEXT NOT NULL,
            owner TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(owner, source_ref, selector_json, fragment_hash)
        );
        CREATE TABLE IF NOT EXISTS research_fragment_evidence_objects (
            evidence_ref TEXT PRIMARY KEY,
            evidence_kind TEXT NOT NULL,
            fragment_refs_json TEXT NOT NULL,
            title_zh TEXT NOT NULL,
            description_zh TEXT NOT NULL,
            claim_summary TEXT NOT NULL,
            applicability_json TEXT NOT NULL,
            identity_refs_json TEXT NOT NULL,
            limitations_json TEXT NOT NULL,
            conflicts_json TEXT NOT NULL,
            owner TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_evidence_catalog_state (
            owner TEXT PRIMARY KEY,
            revision INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_evidence_tags (
            tag_ref TEXT PRIMARY KEY,
            title_zh TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            description_zh TEXT NOT NULL,
            created_by_profile_ref TEXT NOT NULL,
            status TEXT NOT NULL,
            owner TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(owner, normalized_title)
        );
        CREATE TABLE IF NOT EXISTS research_evidence_tag_proposals (
            proposal_token TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            catalog_revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            candidates_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_evidence_object_tags (
            evidence_ref TEXT NOT NULL,
            tag_ref TEXT NOT NULL,
            owner TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY(owner, evidence_ref, tag_ref)
        );
        CREATE TABLE IF NOT EXISTS research_evidence_lifecycle (
            owner TEXT NOT NULL,
            evidence_ref TEXT NOT NULL,
            status TEXT NOT NULL,
            latest_transition_ref TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY(owner, evidence_ref)
        );
        CREATE TABLE IF NOT EXISTS research_evidence_status_events (
            event_ref TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            evidence_ref TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_evidence_source_owner
            ON research_evidence_sources(owner, source_kind);
        CREATE INDEX IF NOT EXISTS idx_research_evidence_fragment_source
            ON research_evidence_fragments(owner, source_ref);
        CREATE INDEX IF NOT EXISTS idx_research_fragment_evidence_owner
            ON research_fragment_evidence_objects(owner, evidence_kind);
        CREATE INDEX IF NOT EXISTS idx_research_evidence_tags_owner
            ON research_evidence_tags(owner, status);
        CREATE INDEX IF NOT EXISTS idx_research_evidence_lifecycle_status
            ON research_evidence_lifecycle(owner, status);
        CREATE INDEX IF NOT EXISTS idx_research_evidence_status_target
            ON research_evidence_status_events(
                owner, evidence_ref, created_at
            );
    """)


def catalog_revision(conn, owner: str) -> int:
    ensure_schema(conn)
    conn.execute(
        "INSERT OR IGNORE INTO research_evidence_catalog_state VALUES (?, 0)",
        (owner,),
    )
    row = conn.execute(
        "SELECT revision FROM research_evidence_catalog_state WHERE owner=?",
        (owner,),
    ).fetchone()
    return int(row["revision"])


def bump_catalog_revision(conn, owner: str) -> int:
    catalog_revision(conn, owner)
    conn.execute(
        "UPDATE research_evidence_catalog_state "
        "SET revision=revision+1 WHERE owner=?",
        (owner,),
    )
    return catalog_revision(conn, owner)
