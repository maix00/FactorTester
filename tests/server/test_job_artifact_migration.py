from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from server.jobs.artifact_migration import inspect, migrate


def _database(path: Path, source: Path) -> None:
    payload = b"historical result"
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path("job-1") / "result.json"
    (source / relative).parent.mkdir(parents=True)
    (source / relative).write_bytes(payload)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE research_job_artifacts (
                job_id TEXT, name TEXT, relative_path TEXT,
                content_hash TEXT, size_bytes INTEGER, state TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO research_job_artifacts VALUES (?, ?, ?, ?, ?, ?)",
            ("job-1", "result", str(relative), digest, len(payload), "active"),
        )


def test_inspect_and_migrate_verified_source(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite"
    source = tmp_path / "old-results"
    canonical = tmp_path / "shared-results"
    _database(database, source)

    report = inspect(database, canonical, [source])
    assert report["counts"] == {
        "canonical": 0,
        "source": 1,
        "missing": 0,
        "conflict": 0,
    }
    result = migrate(report, apply=True)
    assert result["copied"] == 1
    assert (canonical / "job-1" / "result.json").read_bytes() == b"historical result"

    second = inspect(database, canonical, [source])
    assert second["counts"]["canonical"] == 1


def test_migration_does_not_accept_hash_mismatch(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite"
    source = tmp_path / "old-results"
    canonical = tmp_path / "shared-results"
    _database(database, source)
    (source / "job-1" / "result.json").write_bytes(b"changed")

    report = inspect(database, canonical, [source])
    assert report["counts"]["conflict"] == 1
    assert report["counts"]["source"] == 0
    result = migrate(report, apply=True)
    assert result["copied"] == 0
    assert not (canonical / "job-1" / "result.json").exists()
