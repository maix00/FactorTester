from __future__ import annotations

from pathlib import Path

from server.manager.storage.local_run_projection import LocalRunProjection


def _payload() -> dict:
    return {
        "local_job_id": "local-001",
        "title": "本地 IC",
        "kind": "ic_test",
        "status": "succeeded",
        "execution_mode": "local",
        "updated_at": 100.0,
        "created_at": 90.0,
        "requirements": [{"product_ref": "ALPHA", "frequency": "1d"}],
        "summary": {"ic_mean": 0.12},
        "artifact_manifest": [{
            "name": "chart.png",
            "file_name": "chart.png",
            "role": "output",
            "content_type": "image/png",
            "size_bytes": 3,
            "content_hash": "a" * 64,
            "upload_state": "local_only",
            "local_path": "/must-not-cross-boundary/chart.png",
        }],
        "metadata_hash": "b" * 64,
    }


def test_projection_is_owner_scoped_and_does_not_store_local_path(tmp_path: Path) -> None:
    projection = LocalRunProjection(
        tmp_path / "local-run.sqlite", server_id="public-1",
    )
    stored = projection.upsert("alice", _payload())
    assert stored["job"]["local_run"] is True
    assert stored["job"]["task_name"] == "本地 IC"
    assert stored["job"]["output_artifact_count"] == 1
    assert stored["job"]["output_artifact_bytes"] == 3
    assert stored["task_detail"]["artifacts"][0]["state"] == "local_only"
    assert projection.get("bob", "local-001") is None
    with projection._connection() as db:  # noqa: SLF001 - verify storage boundary
        raw = db.execute("SELECT payload_json FROM local_runs").fetchone()[0]
    assert "must-not-cross-boundary" not in raw


def test_projection_drops_source_code_and_does_not_trust_uploaded_state(tmp_path: Path) -> None:
    payload = _payload()
    payload["configuration"] = {
        "source_code": "class Secret: pass",
        "display": "safe",
    }
    payload["artifact_manifest"][0]["upload_state"] = "uploaded"
    payload["artifact_manifest"][0]["storage_transfer_id"] = "forged-transfer"
    projection = LocalRunProjection(tmp_path / "local-run.sqlite", server_id="public-1")

    stored = projection.upsert("alice", payload)

    assert stored["task_detail"]["artifacts"][0]["state"] == "local_only"
    assert "source_code" not in stored["task_detail"]["configuration"]
    with projection._connection() as db:  # noqa: SLF001 - verify trust boundary
        raw = db.execute("SELECT payload_json FROM local_runs").fetchone()[0]
    assert "forged-transfer" not in raw


def test_uploaded_artifact_becomes_downloadable_only_after_ack(tmp_path: Path) -> None:
    projection = LocalRunProjection(tmp_path / "local-run.sqlite", server_id="public-1")
    projection.upsert("alice", _payload())
    updated = projection.mark_artifact_uploaded(
        "alice", "local-001", "chart.png", "upload-transfer-1",
    )
    artifact = updated["task_detail"]["artifacts"][0]
    assert artifact["state"] == "active"
    assert artifact["upload_state"] == "uploaded"
    assert artifact["storage_transfer_id"] == "upload-transfer-1"
    assert updated["job"]["raw_artifacts_remote"] is True


def test_later_summary_sync_cannot_revoke_uploaded_artifact(tmp_path: Path) -> None:
    projection = LocalRunProjection(tmp_path / "local-run.sqlite", server_id="public-1")
    projection.upsert("alice", _payload())
    projection.mark_artifact_uploaded(
        "alice", "local-001", "chart.png", "upload-transfer-2",
    )
    refreshed = projection.upsert("alice", _payload())
    artifact = refreshed["task_detail"]["artifacts"][0]
    assert artifact["upload_state"] == "uploaded"
    assert artifact["storage_transfer_id"] == "upload-transfer-2"
