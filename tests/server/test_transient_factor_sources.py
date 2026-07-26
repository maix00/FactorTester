from __future__ import annotations

import json
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
    assert sources.load_source(scope["scope_id"], "ProfileAlpha", owner="") is None
    root = tmp_path / "transient_factor_sources" / scope["scope_id"]
    assert root.exists()
    assert sources.cleanup_scope(scope["scope_id"])
    assert not root.exists()
    assert sources.scope_status(scope["scope_id"]) == "cleaned"


def test_scope_status_detects_source_corruption(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    scope = sources.create_scope(
        owner="alice",
        entries=[{
            "path": "custom_factors/ProfileAlpha.py",
            "source_code": "class ProfileAlpha:\n    pass\n",
        }],
    )
    source_path = (
        tmp_path / "transient_factor_sources" / scope["scope_id"]
        / "custom_factors" / "ProfileAlpha.py"
    )
    source_path.write_text("class ProfileAlpha:\n    changed = True\n", encoding="utf-8")
    assert sources.scope_status(scope["scope_id"]) == "corrupt"


def test_transient_scope_rejects_non_factor_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    with pytest.raises(ValueError, match="custom_factors"):
        sources.validate_entries([{
            "path": "../secret.py",
            "source_code": "secret",
        }])


def test_transient_scope_requires_an_owner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    with pytest.raises(ValueError, match="owner"):
        sources.create_scope(owner="", entries=[{
            "path": "custom_factors/ProfileAlpha.py",
            "source_code": "class ProfileAlpha:\n    pass\n",
        }])


def test_factor_registry_prefers_run_override_without_persisting_source() -> None:
    source = "class ProfileAlpha:\n    pass\n"
    with factor_registry.transient_factor_source_scope(
        owner="alice",
        overrides={"ProfileAlpha": source}
    ):
        resolved = factor_registry.resolve_factor_family_source(
            "ProfileAlpha",
            username="alice",
        )
    assert resolved["source_kind"] == "custom"
    assert resolved["source_code"] == source


def test_transient_override_wins_over_public_name_collision(monkeypatch) -> None:
    source = "class ProfileAlpha:\n    pass\n"
    monkeypatch.setattr(
        factor_registry,
        "_public_factor_source_exists",
        lambda factor_id: factor_id == "ProfileAlpha",
    )
    monkeypatch.setattr(
        factor_registry,
        "load_public_factor_source",
        lambda factor_id: "class PublicAlpha:\n    pass\n",
    )
    with factor_registry.transient_factor_source_scope(
        owner="alice",
        overrides={"ProfileAlpha": source}
    ):
        resolved = factor_registry.resolve_factor_family_source(
            "ProfileAlpha",
            username="alice",
        )
    assert resolved["source_kind"] == "custom"
    assert resolved["source_mode"] == "transient_run_source"
    assert resolved["source_code"] == source


def test_transient_override_is_bound_to_owner() -> None:
    source = "class ProfileAlpha:\n    pass\n"
    with factor_registry.transient_factor_source_scope(
        owner="alice",
        overrides={"ProfileAlpha": source},
    ):
        assert factor_registry._transient_source("alice", "ProfileAlpha") == source
        assert factor_registry._transient_source("bob", "ProfileAlpha") == ""


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


def test_cleanup_uses_aggregate_run_attempt_query(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    scope = sources.create_scope(
        owner="alice",
        entries=[{
            "path": "custom_factors/ProfileAlpha.py",
            "source_code": "class ProfileAlpha:\n    pass\n",
        }],
    )

    class Record:
        owner = "alice"
        run_id = "run-1"
        job_spec = {"transient_factor_source_scope_id": scope["scope_id"]}

    class Repository:
        def all_run_attempts_terminal(self, *, owner: str, run_id: str):
            return True

    assert sources.cleanup_for_terminal_job(Repository(), Record())
    assert sources.scope_status(scope["scope_id"]) == "cleaned"


def test_stale_scope_cleanup_keeps_active_job_sources(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    scope = sources.create_scope(
        owner="alice",
        entries=[{
            "path": "custom_factors/ProfileAlpha.py",
            "source_code": "class ProfileAlpha:\n    pass\n",
        }],
    )
    manifest_path = (
        tmp_path / "transient_factor_sources" / scope["scope_id"] / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at"] = 1.0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class ActiveRepository:
        def has_active_transient_scope(self, *, owner: str = "", scope_id: str):
            return True

    class EmptyRepository:
        def has_active_transient_scope(self, *, owner: str = "", scope_id: str):
            return False

    assert sources.cleanup_stale_scopes(ActiveRepository(), max_age_seconds=0.0) == 0
    assert sources.scope_status(scope["scope_id"]) == "available"
    assert sources.cleanup_stale_scopes(EmptyRepository(), max_age_seconds=0.0) == 1
    assert sources.scope_status(scope["scope_id"]) == "cleaned"


def test_stale_cleanup_removes_incomplete_manifest_without_active_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sources.Settings, "CACHE_DB_PATH", str(tmp_path / "cache.sqlite"))
    root = tmp_path / "transient_factor_sources" / ("a" * 32)
    root.mkdir(parents=True)
    (root / "custom_factors").mkdir()
    (root / "custom_factors" / "ProfileAlpha.py").write_text(
        "class ProfileAlpha:\n    pass\n",
        encoding="utf-8",
    )

    class Repository:
        def has_active_transient_scope(self, *, owner: str = "", scope_id: str):
            return False

    assert sources.cleanup_stale_scopes(Repository(), max_age_seconds=0.0) == 1
    assert not root.exists()
