#!/usr/bin/env python3
"""Explicitly migrate legacy Research-Evidence links to Report-Evidence links."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

LEGACY = "research_catalog_evidence_links"
CURRENT = "research_catalog_report_evidence_links"


def migrate(db_path: Path) -> dict[str, int | str]:
    path = db_path.expanduser().resolve()
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if LEGACY not in tables:
            return {"status": "not_required", "migrated": 0}
        if CURRENT in tables:
            raise RuntimeError(f"{CURRENT} already exists; refusing an ambiguous migration")
        invalid = int(conn.execute(
            f"""SELECT COUNT(*) FROM {LEGACY} link
                  LEFT JOIN research_catalog_reports report
                    ON report.report_id=link.report_id
                 WHERE link.report_id='' OR report.report_id IS NULL
                    OR report.research_id<>link.research_id"""
        ).fetchone()[0])
        if invalid:
            raise RuntimeError(
                f"legacy links contain {invalid} rows without a matching Report"
            )
        conn.execute("BEGIN IMMEDIATE")
        conn.executescript(f"""
            CREATE TABLE {CURRENT} (
                link_ref TEXT PRIMARY KEY,
                evidence_ref TEXT NOT NULL,
                evidence_owner_ref TEXT NOT NULL,
                report_id TEXT NOT NULL,
                branch_ref TEXT NOT NULL,
                job_id TEXT NOT NULL,
                profile_ref TEXT NOT NULL,
                purpose TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                revoked_at REAL NOT NULL,
                FOREIGN KEY(report_id) REFERENCES research_catalog_reports(report_id)
            );
            INSERT INTO {CURRENT}
                (link_ref, evidence_ref, evidence_owner_ref, report_id,
                 branch_ref, job_id, profile_ref, purpose, status,
                 created_at, revoked_at)
            SELECT link_ref, evidence_ref, evidence_owner_ref, report_id,
                   branch_ref, job_id, profile_ref, purpose, status,
                   created_at, revoked_at
              FROM {LEGACY};
            CREATE INDEX idx_research_catalog_evidence
                ON {CURRENT}(evidence_ref, status);
            DROP TABLE {LEGACY};
        """)
        migrated = int(conn.execute(f"SELECT COUNT(*) FROM {CURRENT}").fetchone()[0])
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        conn.commit()
    return {"status": "migrated", "migrated": migrated}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path", type=Path)
    args = parser.parse_args()
    result = migrate(args.db_path)
    print(f"{result['status']}: {result['migrated']} link(s)")


if __name__ == "__main__":
    main()
