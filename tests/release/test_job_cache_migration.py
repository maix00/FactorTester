from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.cli.release.job_cache_migration import inspect, migrate


def _source(root: Path) -> None:
    payload = b"local cached artifact"
    job = root / "job-1"
    job.mkdir(parents=True)
    (job / "result.json").write_bytes(payload)
    (job / ".artifacts.json").write_text(
        json.dumps({
            "schema_version": 1,
            "job_id": "job-1",
            "artifacts": {
                "result": {
                    "file_name": "result.json",
                    "content_hash": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                }
            },
        }),
        encoding="utf-8",
    )


def test_local_cache_migration_is_verified_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "old-jobs"
    canonical = tmp_path / "jobs"
    _source(source)

    report = inspect(canonical, [source])
    assert report["counts"] == {
        "canonical": 0,
        "source": 1,
        "missing": 0,
        "conflict": 0,
    }
    result = migrate(report, apply=True)
    assert result["copied"] == 1
    assert (canonical / "job-1" / "result.json").read_bytes() == b"local cached artifact"

    second = inspect(canonical, [source])
    assert second["counts"]["canonical"] == 1


def test_local_cache_migration_rejects_invalid_bytes(tmp_path: Path) -> None:
    source = tmp_path / "old-jobs"
    canonical = tmp_path / "jobs"
    _source(source)
    (source / "job-1" / "result.json").write_bytes(b"changed")

    report = inspect(canonical, [source])
    assert report["counts"]["conflict"] == 1
    result = migrate(report, apply=True)
    assert result["copied"] == 0
    assert not (canonical / "job-1" / "result.json").exists()


def test_local_cache_migration_unions_manifests_for_one_job(tmp_path: Path) -> None:
    source = tmp_path / "old-jobs"
    canonical = tmp_path / "jobs"
    _source(source)
    second = source / "job-1" / "extra.json"
    second.write_bytes(b"extra")
    manifest = json.loads((source / "job-1" / ".artifacts.json").read_text())
    manifest["artifacts"]["extra"] = {
        "file_name": "extra.json",
        "content_hash": hashlib.sha256(b"extra").hexdigest(),
        "size_bytes": 5,
    }
    (source / "job-1" / ".artifacts.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    report = inspect(canonical, [source])
    assert report["job_count"] == 1
    assert report["artifact_count"] == 2
    assert report["counts"]["source"] == 2
    assert migrate(report, apply=True)["copied"] == 2
    assert (canonical / "job-1" / "extra.json").read_bytes() == b"extra"
