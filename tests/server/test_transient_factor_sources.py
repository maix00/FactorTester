from __future__ import annotations

from pathlib import Path

import pytest

from server.services import transient_factor_sources as sources
from server.services import factor_registry
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus


def test_transient_scope_is_hashed_and_cleaned(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    entries = sources.validate_entries([{
        "path": "custom_factors/ProfileAlpha.py",
        "source_code": "class ProfileAlpha:\n    pass\n",
    }])
    scope = sources.create_scope(owner="alice", entries=entries)
    assert scope["mode"] == "transient_run_source"
    assert scope["files"][0]["source_sha256"]
    assert "source_code" not in scope["files"][0]
    assert sources.load_source(scope["scope_id"], "ProfileAlpha", owner="alice")
    assert sources.load_source(scope["scope_id"], "ProfileAlpha", owner="bob") is None
    root = tmp_path / "transient_factor_sources" / scope["scope_id"]
    assert root.exists()
    assert sources.cleanup_scope(scope["scope_id"])
    assert not root.exists()
    assert sources.scope_status(scope["scope_id"]) == "cleaned"


def test_transient_scope_rejects_non_factor_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    with pytest.raises(ValueError, match="custom_factors"):
        sources.validate_entries([{
            "path": "../secret.py",
            "source_code": "secret",
        }])


def test_factor_registry_prefers_run_override_without_persisting_source() -> None:
    source = "class ProfileAlpha:\n    pass\n"
    with factor_registry.transient_factor_source_scope(
        overrides={"ProfileAlpha": source}
    ):
        resolved = factor_registry.resolve_factor_family_source(
            "ProfileAlpha",
            username="alice",
        )
    assert resolved["source_kind"] == "custom"
    assert resolved["source_code"] == source


def test_scope_is_removed_only_after_all_run_attempts_are_terminal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    scope = sources.create_scope(
        owner="alice",
        entries=[{
            "path": "custom_factors/ProfileAlpha.py",
            "source_code": "class ProfileAlpha:\n    pass\n",
        }],
    )
    repository = JobRepository(tmp_path / "jobs.sqlite")
    for job_id in ("job-a", "job-b"):
        repository.create(JobRecord(
            job_id=job_id,
            run_id="run-1",
            owner="alice",
            workspace_id="workspace-1",
            kind="ic",
            status=JobStatus.RUNNING,
            job_spec={"transient_factor_source_scope_id": scope["scope_id"]},
            run_spec_hash="a" * 64,
        ))
    repository.transition("job-a", JobStatus.SUCCEEDED, expected=JobStatus.RUNNING)
    assert sources.scope_status(scope["scope_id"]) == "available"
    repository.transition("job-b", JobStatus.FAILED, expected=JobStatus.RUNNING)
    assert sources.scope_status(scope["scope_id"]) == "cleaned"
