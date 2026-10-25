from __future__ import annotations

import os

from server.jobs.dispatch import preflight


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORTESTER_BROKER_URL", "amqp://guest:guest@localhost//")
    monkeypatch.setenv("FACTORTESTER_JOB_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("FACTORTESTER_DEPLOYMENT_ID", "local-docker")
    monkeypatch.setenv("FACTORTESTER_SERVICE_PORT", "8001")


def test_preflight_accepts_wal_shared_directory(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    report = preflight.check_deployment()
    assert report["ok"] is True, report["errors"]
    assert report["target"]["queue"] == "factortester.jobs.local-docker.8001"
    assert report["journal_mode"].lower() == "wal"


def test_preflight_rejects_missing_target(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("FACTORTESTER_SERVICE_PORT", "0")
    monkeypatch.setenv("FACTORTESTER_DEPLOYMENT_ID", "")
    report = preflight.check_deployment()
    assert report["ok"] is False
    assert any("SERVICE_PORT" in error for error in report["errors"])
    assert any("DEPLOYMENT_ID" in error for error in report["errors"])


def test_preflight_reports_missing_executor(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("FACTORTESTER_NAUTILUS_EXECUTOR", "missing.module:execute")
    report = preflight.check_deployment(check_executor=True)
    assert report["ok"] is False
    assert report["executor"] == "unavailable"


def test_preflight_rejects_file_level_bind_mount(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    db = tmp_path / "jobs.db"
    db.write_bytes(b"")
    monkeypatch.setattr(os.path, "ismount", lambda value: str(value) == str(db))
    report = preflight.check_deployment()
    assert report["ok"] is False
    assert any("file bind mount" in error for error in report["errors"])
