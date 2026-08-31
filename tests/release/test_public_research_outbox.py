from __future__ import annotations

from pathlib import Path

from tools.cli.release.research_reporting.public_research.client import (
    ManagerRequestError,
    PublicResearchClient,
)
from tools.cli.release.research_reporting.public_research.object_uploads import (
    ResearchObjectUpload,
)
from tools.cli.release.research_reporting.public_research.outbox import (
    PublicResearchOutbox,
)


def _projection(report_id: str, generation: int) -> dict:
    return {
        "schema_version": 2,
        "report_id": report_id,
        "generation": generation,
        "projection_hash": f"hash-{generation}",
        "components": [],
        "bindings": [],
        "assets": [],
        "attachments": [],
        "local_resources": [],
    }


def _upload(content: bytes = b"report attachment") -> ResearchObjectUpload:
    import hashlib

    return ResearchObjectUpload(
        object_kind="research_attachment",
        object_id="attachment:sha256:abc",
        filename="attachment.txt",
        content_type="text/plain",
        content_hash=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def test_outbox_replaces_older_pending_projection_for_one_report(
    tmp_path: Path,
) -> None:
    outbox = PublicResearchOutbox(tmp_path)
    first = outbox.enqueue_publish(
        owner_ref="GTHT@MaxJJW@1",
        profile_ref="profile-1",
        report_id="report-1",
        projection=_projection("report-1", 1),
        public_title="",
        show_profile=False,
        uploads=(_upload(),),
    )
    second = outbox.enqueue_publish(
        owner_ref="GTHT@MaxJJW@1",
        profile_ref="profile-1",
        report_id="report-1",
        projection=_projection("report-1", 2),
        public_title="",
        show_profile=False,
        uploads=(),
    )

    assert first != second
    assert [item["operation_id"] for item in outbox.pending()] == [second]
    assert outbox.load(first)["manifest"]["state"] == "superseded"
    loaded = outbox.load(second)
    assert loaded["projection"]["generation"] == 2
    assert loaded["uploads"] == ()


def test_public_report_sync_keeps_operation_when_manager_is_offline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = PublicResearchClient(tmp_path, manager_url="http://manager.invalid")
    operation_id = client.outbox.enqueue_publish(
        owner_ref="GTHT@MaxJJW@1",
        profile_ref="profile-1",
        report_id="report-1",
        projection=_projection("report-1", 1),
        public_title="",
        show_profile=False,
        uploads=(),
    )

    def unavailable(*_args, **_kwargs):
        raise ManagerRequestError(0, "Manager publication service is unavailable")

    monkeypatch.setattr(client, "_request", unavailable)
    result = client.sync_pending(operation_id=operation_id)

    assert result[0]["status"] == "pending_sync"
    assert client.outbox.pending()[0]["operation_id"] == operation_id
    assert client.outbox.load(operation_id)["manifest"]["state"] == "pending"


def test_public_report_sync_marks_operation_complete_after_reconnect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = PublicResearchClient(tmp_path, manager_url="http://manager.invalid")
    operation_id = client.outbox.enqueue_publish(
        owner_ref="GTHT@MaxJJW@1",
        profile_ref="profile-1",
        report_id="report-1",
        projection=_projection("report-1", 1),
        public_title="",
        show_profile=False,
        uploads=(_upload(),),
    )
    uploaded = []

    def request(method, path, **_kwargs):
        if path == "/api/research-publications/publish":
            return {
                "success": True,
                "publication_id": "publication-1",
                "storage_server_id": "server-1",
            }
        raise AssertionError((method, path))

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(
        client, "_upload_object",
        lambda **kwargs: uploaded.append(kwargs["upload"].object_id),
    )
    result = client.sync_pending(operation_id=operation_id)

    assert result[0]["status"] == "synced"
    assert result[0]["publication_id"] == "publication-1"
    assert uploaded == ["attachment:sha256:abc"]
    assert client.outbox.pending() == []
    assert client.outbox.load(operation_id)["manifest"]["state"] == "completed"
