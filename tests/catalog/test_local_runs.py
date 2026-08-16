from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.cli.catalog.local_runs import (
    LocalRunRequirementsError,
    LocalRunStore,
    validate_local_run_requirements,
)
from tools.cli.local_sources.contracts import validate_local_source_manifest


def _manifest(status: str = "ready"):
    return validate_local_source_manifest({
        "schema_version": 1,
        "managed_by": "factortester-client",
        "source_id": "bundle",
        "source_name": "本地 Bundle",
        "source_kind": "external_connector",
        "provider_kind": "synthetic",
        "version": "1",
        "connector": {
            "entrypoint": "connector.py",
            "probe_mode": "explicit",
            "credential_store": "keychain",
        },
        "availability": {
            "status": status,
            "available_product_refs": ["bundle:ALPHA"],
        },
        "members": [{
            "id": "daily",
            "label": "日线",
            "timezone": "Asia/Taipei",
            "time_columns": {"timestamp": "timestamp"},
            "data_columns": {"close": "close"},
            "data_mode": {
                "id": "daily", "title_zh": "日线", "available": True,
                "sampling_mode": "bar", "frequency": "1d",
                "data_kind": "ohlcv", "market_depth": "none",
                "delivery_mode": "historical",
            },
        }],
        "categories": [],
        "products": [{
            "product_ref": "bundle:ALPHA",
            "alias": "ALPHA",
            "display_name": "阿尔法",
            "class_path": "Product/Futures",
            "category_values": {},
            "product_kind": "future",
            "metadata": {"code": "ALPHA"},
        }],
    })


def test_local_preflight_requires_ready_product_and_frequency() -> None:
    result = validate_local_run_requirements(
        [_manifest()],
        [{"product_ref": "ALPHA", "frequency": "1d"}],
    )
    assert result["valid"] is True
    assert result["available"][0]["source_id"] == "bundle"

    with pytest.raises(LocalRunRequirementsError, match="缺少") as error:
        validate_local_run_requirements(
            [_manifest()],
            [{"product_ref": "ALPHA", "frequency": "5m"}],
        )
    assert error.value.missing == [{
        "product_ref": "ALPHA",
        "frequency": "5m",
        "reason": "local data source does not provide this product/frequency",
    }]


def test_local_run_store_outbox_is_durable_and_summary_only(tmp_path: Path) -> None:
    root = tmp_path / "FactorTester"
    store = LocalRunStore(root)
    store.record(
        local_job_id="local-001",
        owner_ref="GTHT@MaxJJW@1234",
        requirements=[{"product_ref": "ALPHA", "frequency": "1d"}],
        summary={"chart": {"points": 3}},
        artifact_manifest=[{
            "name": "equity.png",
            "size_bytes": 3,
            "content_hash": "a" * 64,
            "local_path": str(root / "jobs" / "local-001" / "equity.png"),
        }],
    )

    operation = LocalRunStore(root).pending_outbox()[0]
    assert operation["operation_kind"] == "sync_summary"
    assert "local_path" not in operation["payload"]["artifact_manifest"][0]
    assert operation["payload"]["raw_artifacts_remote"] is False
    assert LocalRunStore(root).get("local-001")["requirements"][0]["frequency"] == "1d"


def test_explicit_upload_intent_is_separate_from_summary_sync(tmp_path: Path) -> None:
    root = tmp_path / "FactorTester"
    store = LocalRunStore(root)
    artifact = root / "chart.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"abc")
    store.record(
        local_job_id="local-002",
        owner_ref="alice",
        requirements=[{"product_ref": "ALPHA"}],
        artifact_manifest=[{
            "name": "chart.png",
            "size_bytes": 3,
            "content_hash": "a" * 64,
            "local_path": str(artifact),
        }],
    )
    intent = store.enqueue_artifact_upload("local-002", "chart.png")
    operations = store.pending_outbox()
    assert intent["raw_artifacts_remote"] is True
    assert {item["operation_kind"] for item in operations} == {
        "sync_summary", "upload_artifact",
    }


def test_outbox_claim_recovers_stale_sending_and_keeps_upload_state(tmp_path: Path) -> None:
    root = tmp_path / "FactorTester"
    store = LocalRunStore(root)
    artifact = root / "chart.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"abc")
    store.record(
        local_job_id="local-003",
        owner_ref="alice",
        requirements=[{"product_ref": "ALPHA"}],
        artifact_manifest=[{
            "name": "chart.png", "size_bytes": 3, "content_hash": "a" * 64,
            "local_path": str(artifact),
        }],
    )
    with store.connection() as connection:
        connection.execute(
            "UPDATE local_run_outbox SET state='sending', updated_at=?",
            (0,),
        )
    claimed = store.claim_outbox(limit=10)
    assert len(claimed) == 1
    assert claimed[0]["state"] == "sending"
    assert claimed[0]["attempts"] == 1
    store.mark_artifact_uploaded("local-003", "chart.png", "transfer-1")
    assert LocalRunStore(root).get("local-003")["artifact_manifest"][0]["upload_state"] == "uploaded"


def test_local_run_record_keeps_uploaded_artifact_on_summary_refresh(tmp_path: Path) -> None:
    root = tmp_path / "FactorTester"
    store = LocalRunStore(root)
    artifact = root / "chart.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"abc")
    digest = hashlib.sha256(b"abc").hexdigest()
    manifest = [{
        "name": "chart.png", "size_bytes": 3, "content_hash": digest,
        "local_path": str(artifact),
    }]
    store.record(
        local_job_id="local-004", owner_ref="alice",
        requirements=[{"product_ref": "ALPHA"}], artifact_manifest=manifest,
    )
    store.mark_artifact_uploaded("local-004", "chart.png", "transfer-4")
    refreshed = store.record(
        local_job_id="local-004", owner_ref="alice",
        requirements=[{"product_ref": "ALPHA"}],
        summary={"ic_mean": 0.2}, artifact_manifest=manifest,
    )
    assert refreshed["artifact_manifest"][0]["upload_state"] == "uploaded"
    assert refreshed["server_projection"]["artifact_manifest"][0]["upload_state"] == "uploaded"


def test_explicit_upload_rejects_artifact_outside_client_root(tmp_path: Path) -> None:
    root = tmp_path / "FactorTester"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"abc")
    digest = hashlib.sha256(b"abc").hexdigest()
    store = LocalRunStore(root)
    store.record(
        local_job_id="local-005", owner_ref="alice",
        requirements=[{"product_ref": "ALPHA"}],
        artifact_manifest=[{
            "name": "outside.txt", "size_bytes": 3, "content_hash": digest,
            "local_path": str(outside),
        }],
    )
    store.enqueue_artifact_upload("local-005", "outside.txt")
    operation = next(
        item for item in store.pending_outbox()
        if item["operation_kind"] == "upload_artifact"
    )
    from tools.cli.catalog.local_run_sync import _upload_artifact

    with pytest.raises(FileNotFoundError, match="unavailable"):
        _upload_artifact(store, object(), operation["payload"])
