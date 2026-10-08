from __future__ import annotations

from pathlib import Path

from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.report_space import initialize_report_space
from tools.cli.release.research_reporting.workspace import initialize_report_workspace
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


def test_outbox_keeps_pending_branches_of_one_report_distinct(tmp_path: Path) -> None:
    outbox = PublicResearchOutbox(tmp_path)
    operations = [
        outbox.enqueue_publish(
            owner_ref="GTHT@MaxJJW@1", profile_ref="profile-1",
            report_id="report-1", publication_key=f"report-1:branch:{branch}",
            branch_ref=branch, projection=_projection("report-1", generation),
            public_title="", show_profile=False, uploads=(),
        )
        for branch, generation in (("first", 1), ("second", 2))
    ]

    assert [item["operation_id"] for item in outbox.pending()] == operations
    assert {item["branch_ref"] for item in outbox.pending()} == {"first", "second"}


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


def test_client_configures_one_uploaded_branch(monkeypatch, tmp_path: Path) -> None:
    client = PublicResearchClient(tmp_path, manager_url="http://manager.invalid")
    requests = []

    def request(method, path, **kwargs):
        requests.append((method, path, kwargs["payload"]))
        return {"success": True, "settings": {
            "publication_id": "publication-branch-b",
            "report_id": "report-1", "branch_ref": "branch-b",
            "visibility": "authorized", "auto_sync": False,
        }}

    monkeypatch.setattr(client, "_request", request)
    result = client.configure(
        "publication-branch-b", visibility="authorized", auto_sync=False,
        authorized_users=("GTHT@Reader@2",),
    )

    assert result["branch_ref"] == "branch-b"
    assert requests == [("POST", "/api/research-publications/settings", {
        "publication_id": "publication-branch-b",
        "visibility": "authorized", "auto_sync": False,
        "relay_local_files": False,
        "authorized_users": ["GTHT@Reader@2"],
    })]


def test_local_branch_publication_status_uses_complete_author_identity(tmp_path, monkeypatch):
    store = LocalProfileStore(tmp_path)
    value = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://manager.invalid",
        workspace_root=tmp_path / "profile-root",
    )
    value["session_binding"] = {
        "principal_ref": "GTHT@MaxA@1",
        "session_ref": "session-binding:test",
    }
    store.save(value)
    identity = initialize_report_space(store, "maxa", {
        "report_id": "same-report", "research_id": "research-1",
        "owner_ref": "GTHT@MaxA@1", "profile_ref": "maxa",
        "workspace_id": "workspace-1", "title": "Shared report",
    })
    report_workspace_id = identity["report_workspace_id"]
    for branch in ("branch-sgccs", "alternative"):
        initialize_report_workspace(
            workspace_root=tmp_path / "profile-root",
            report_workspace_id=report_workspace_id,
            report_id="same-report", branch_id=branch,
            workspace_id="workspace-1", title="Shared report",
            branch_ref=f"report-branch:{branch}",
        )
    client = PublicResearchClient(tmp_path, manager_url="http://manager.invalid")
    own = {"owner_ref": "GTHT@MaxA@1", "profile_ref": "maxa", "report_id": "same-report",
           "branch_ref": "branch-sgccs", "publication_id": "own-publication", "visibility": "authorized"}
    other = {**own, "owner_ref": "GTHT@Other@2", "publication_id": "other-publication"}
    monkeypatch.setattr(client, "list_publications", lambda: [own, other])
    values = {item["branch_id"]: item for item in client.list_local_reports()}
    assert values["branch-sgccs"]["publication_id"] == "own-publication"
    assert values["branch-sgccs"]["sync_status"] == "synced"
    assert values["alternative"]["publication_id"] is None
    assert values["alternative"]["sync_status"] == "local"
