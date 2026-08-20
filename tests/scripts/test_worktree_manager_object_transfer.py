from __future__ import annotations

import base64
import hashlib
import sqlite3
import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest
import settings as Settings

from server.manager import runtime as manager
from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.server import ClientDataPlaneHTTPServer
from server.manager.objects import (
    ObjectReference,
    TransferObjectKind,
    research_object_id,
    split_research_object_id,
)
from server.manager.objects.adapters.factor_source import (
    FactorSourceDestinationAdapter,
    FactorSourceOriginAdapter,
    FactorSourceStore,
)
from server.manager.objects.adapters.public_research import PublicResearchOriginAdapter
from server.manager.objects.adapters.public_research_destination import (
    PublicResearchDestinationAdapter,
)
from server.manager.objects.adapters.profile_workspace import (
    ProfileWorkspaceOriginAdapter,
)
from server.manager.objects.origin import ObjectOriginRegistry
from tools.cli.release.research_reporting.public_research.library import (
    PublicResearchLibrary,
)
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
)
from tools.cli.release.research_reporting.public_research.object_uploads import (
    detach_object_bytes,
)
from server.services.federated_factor_sources import (
    hydrate_source_free_entries,
    source_free_context,
    source_transfer_manifest,
)
from server.manager.services.agent_workspace import ensure_server_profile_workspace


@pytest.fixture(autouse=True)
def _isolated_manager_sqlite(tmp_path, monkeypatch):
    """Keep transfer integration tests away from the live Manager SQLite."""
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "manager.sqlite")


@contextmanager
def _running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_research_object_reference_is_opaque_after_publication_split() -> None:
    object_id = research_object_id("pub-1", "attachment:sha256:" + "a" * 64)

    assert split_research_object_id(object_id) == (
        "pub-1", "attachment:sha256:" + "a" * 64,
    )


def test_object_reference_normalizes_hash_and_metadata() -> None:
    value = ObjectReference(
        kind=TransferObjectKind.RESEARCH_ATTACHMENT,
        object_id="pub-1:attachment:sha256:" + "A" * 64,
        storage_server_id="public-1",
        expected_size=12,
        expected_sha256="A" * 64,
    ).normalized()

    assert value.kind is TransferObjectKind.RESEARCH_ATTACHMENT
    assert value.expected_sha256 == "a" * 64


def test_public_research_object_store_resolves_attachment_without_base64(
    tmp_path,
) -> None:
    raw = b"factor-source"
    digest = hashlib.sha256(raw).hexdigest()
    library = PublicResearchLibrary(tmp_path, storage_server_id="public-1")
    projection = {
        "schema_version": 2,
        "report_id": "report-1",
        "generation": 1,
        "projection_hash": "projection-1",
        "title": "Report",
        "components": [],
        "assets": [],
        "attachments": [{
            "attachment_ref": f"attachment:sha256:{digest}",
            "attachment_kind": "factor_source",
            "filename": "factor.py",
            "media_type": "text/x-python",
            "content_hash": digest,
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }],
        "local_resources": [],
    }
    receipt = library.sync({
        "report_id": "report-1",
        "owner_ref": "owner",
        "projection": projection,
    })
    store = PublicResearchObjectStore(library)
    value = store.resolve(
        receipt["publication_id"],
        TransferObjectKind.RESEARCH_ATTACHMENT,
        f"attachment:sha256:{digest}",
        "owner",
    )

    assert value.path.read_bytes() == raw
    assert store.metadata(
        receipt["publication_id"],
        TransferObjectKind.RESEARCH_ATTACHMENT,
        f"attachment:sha256:{digest}",
        "owner",
    )["size_bytes"] == len(raw)


def test_detach_object_bytes_rehashes_source_free_projection() -> None:
    raw = b"asset bytes"
    digest = hashlib.sha256(raw).hexdigest()
    projection = {
        "schema_version": 2,
        "report_id": "report-1",
        "generation": 1,
        "title": "Report",
        "components": [],
        "assets": [{
            "asset_id": "asset-1234",
            "filename": "plot.png",
            "media_type": "image/png",
            "content_hash": digest,
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }],
    }

    metadata, uploads = detach_object_bytes(projection)

    assert "content_base64" not in metadata["assets"][0]
    assert metadata["assets"][0]["size_bytes"] == len(raw)
    assert metadata["projection_hash"]
    assert uploads[0].object_id == "asset-1234"
    assert uploads[0].content == raw


def test_public_research_destination_promotes_verified_upload(tmp_path) -> None:
    raw = b"attachment uploaded over 7997"
    digest = hashlib.sha256(raw).hexdigest()
    library = PublicResearchLibrary(tmp_path / "research", storage_server_id="node-a")
    receipt = library.sync({
        "report_id": "report-upload",
        "owner_ref": "alice",
        "projection": {
            "schema_version": 2,
            "report_id": "report-upload",
            "generation": 1,
            "projection_hash": "hash",
            "title": "Report",
            "components": [],
            "assets": [],
            "local_resources": [],
            "related_objects": [],
            "attachments": [{
                "attachment_ref": f"attachment:sha256:{digest}",
                "filename": "source.py",
                "media_type": "text/x-python",
                "content_hash": digest,
                "size_bytes": len(raw),
            }],
        },
    })
    staged = tmp_path / "staged.bin"
    staged.write_bytes(raw)
    context = type("Context", (), {
        "transfer": type("Transfer", (), {
            "object_kind": "research_attachment",
            "object_id": (
                f"{receipt['publication_id']}:attachment:sha256:{digest}"
            ),
            "principal": "alice",
            "expected_size": len(raw),
            "expected_sha256": digest,
        })(),
    })()

    target = PublicResearchDestinationAdapter(
        PublicResearchObjectStore(library),
    )(context, staged)

    assert target.read_bytes() == raw
    assert not staged.exists()
    assert library.attachment(
        receipt["publication_id"],
        f"attachment:sha256:{digest}",
        "alice",
    )[0] == raw


def test_profile_workspace_origin_adapter_resolves_safe_file_and_rejects_symlink(
    tmp_path,
) -> None:
    root = ensure_server_profile_workspace(
        tmp_path / "data", "GTHT@MaxJJW@1234", "profile-main",
    )
    file_path = root / "research" / "notes.txt"
    file_path.write_text("workspace note", encoding="utf-8")
    transfer = SimpleNamespace(
        principal="GTHT@MaxJJW@1234",
        object_id="profile-main/research/notes.txt",
        expected_size=file_path.stat().st_size,
    )

    adapter = ProfileWorkspaceOriginAdapter(data_root=tmp_path / "data")
    assert adapter(transfer) == file_path

    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = root / "research" / "outside.txt"
    link.symlink_to(outside)
    transfer.object_id = "profile-main/research/outside.txt"
    transfer.expected_size = outside.stat().st_size
    with pytest.raises(ValueError, match="symlinks"):
        adapter(transfer)


def test_manager_object_ticket_and_7997_upload_promote_research_attachment(
    tmp_path,
) -> None:
    raw = b"attachment streamed through the object data plane"
    digest = hashlib.sha256(raw).hexdigest()
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    token = "user-token"
    state._sessions[state._token_hash(token)] = (
        "alice", "user", float("inf"),
    )
    receipt = state.public_research.sync({
        "report_id": "report-route",
        "owner_ref": "alice",
        "projection": {
            "schema_version": 2,
            "report_id": "report-route",
            "generation": 1,
            "projection_hash": "hash",
            "title": "Report",
            "components": [],
            "assets": [],
            "local_resources": [],
            "related_objects": [],
            "attachments": [{
                "attachment_ref": f"attachment:sha256:{digest}",
                "filename": "source.py",
                "media_type": "text/x-python",
                "content_hash": digest,
                "size_bytes": len(raw),
            }],
        },
    })
    research_store = PublicResearchObjectStore(state.public_research)
    data_runtime = DataPlaneRuntime(
        server_id=state.server_id,
        transfer_database=state.transfer_database_path,
        staging_root=state.transfer_submission_root,
            origin_resolver=ObjectOriginRegistry(
                adapters={
                    TransferObjectKind.RESEARCH_ATTACHMENT.value: (
                        PublicResearchOriginAdapter(research_store)
                    ),
                },
                fallback=lambda _transfer: tmp_path / "not-an-origin",
            ),
        destination_committer=PublicResearchDestinationAdapter(research_store),
    )
    data_server = ClientDataPlaneHTTPServer(
        ("127.0.0.1", 0), runtime=data_runtime,
    )
    data_endpoint = f"http://127.0.0.1:{data_server.server_address[1]}"
    state.configure_data_plane(
        client_host="127.0.0.1",
        client_port=data_server.server_address[1],
        client_control_endpoint="http://127.0.0.1:7998",
        client_data_endpoint=data_endpoint,
    )
    manager.Handler.state = state
    manager_server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)

    with _running(data_server), _running(manager_server) as manager_endpoint:
        access_request = Request(
            manager_endpoint + "/api/transfers/objects/access",
            data=json.dumps({
                "owner_ref": "alice",
                "publication_id": receipt["publication_id"],
                "object_kind": "research_attachment",
                "object_id": f"attachment:sha256:{digest}",
                "storage_server_id": state.server_id,
                "filename": "source.py",
                "content_type": "text/x-python",
                "size_bytes": len(raw),
                "sha256": digest,
            }).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(access_request) as response:
            access = json.loads(response.read())["access"]
        with urlopen(Request(
            access["url"],
            data=raw,
            method="PUT",
            headers={
                "Authorization": f"Bearer {access['bearer']}",
                "Content-Type": "text/x-python",
            },
        )) as response:
            assert response.status == 201

        download_request = Request(
            manager_endpoint + "/api/transfers/objects/download-access",
            data=json.dumps({
                "publication_id": receipt["publication_id"],
                "object_kind": "research_attachment",
                "object_id": f"attachment:sha256:{digest}",
            }).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(download_request) as response:
            download = json.loads(response.read())
        with urlopen(Request(
            download["access"]["url"],
            headers={
                "Authorization": f"Bearer {download['access']['bearer']}",
            },
        )) as response:
            assert response.read() == raw

    assert state.public_research.attachment(
        receipt["publication_id"],
        f"attachment:sha256:{digest}",
        "alice",
    )[0] == raw


def test_factor_source_origin_adapter_materializes_hash_bound_source(tmp_path) -> None:
    database = tmp_path / "sources.sqlite"
    source = "class MmDemo:\n    pass\n"
    digest = hashlib.sha256(source.encode()).hexdigest()
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE factor_family_sources (
                source_kind TEXT NOT NULL,
                owner_username TEXT NOT NULL DEFAULT '',
                factor_id TEXT NOT NULL,
                factor_name TEXT NOT NULL DEFAULT '',
                source_code TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                PRIMARY KEY (source_kind, owner_username, factor_id)
            )
            """
        )
        connection.execute(
            "INSERT INTO factor_family_sources VALUES (?, ?, ?, ?, ?, ?)",
            ("custom", "owner", "MmDemo", "Demo", source, 1.0),
        )

    transfer = type("Transfer", (), {
        "object_id": "owner:MmDemo",
        "expected_size": len(source.encode()),
        "expected_sha256": digest,
    })()
    path = FactorSourceOriginAdapter(
        database=database,
        cache_root=tmp_path / "cache",
    )(transfer)

    assert path.read_text(encoding="utf-8") == source


def test_factor_source_object_round_trip_and_source_free_context(tmp_path) -> None:
    database = tmp_path / "sources.sqlite"
    source = "class RemoteDemo:\n    pass\n"
    raw = source.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    object_id = "alice:RemoteDemo"
    source_path = tmp_path / "remote-demo.py"
    source_path.write_bytes(raw)

    FactorSourceDestinationAdapter(database=database)(
        type("Context", (), {
            "transfer": type("Transfer", (), {
                "object_kind": "factor_source",
                "object_id": object_id,
                "principal": "alice",
                "expected_size": len(raw),
                "expected_sha256": digest,
            })(),
        })(),
        source_path,
    )

    entry = {
        "canonical_family_ref": object_id,
        "source_kind": "custom",
        "source_owner": "alice",
        "source_access_policy": "owner_only",
        "factor_id": "RemoteDemo",
        "path": "manager_factor_sources/ignored.py",
        "source_code": source,
        "source_sha256": digest,
        "source_bytes": len(raw),
    }
    context = {
        "schema_version": 2,
        "owner": "alice",
        "run_spec_hash": "run-spec",
        "prepared": {
            "transient_sources": [],
            "portable_factor_sources": [entry],
        },
    }
    source_free = source_free_context(
        context, owner="alice", storage_server_id="local-feat",
    )
    source_free_entry = source_free["prepared"]["portable_factor_sources"][0]
    assert "source_code" not in source_free_entry
    assert source_free_entry["object_kind"] == "factor_source"
    assert source_free_entry["storage_server_id"] == "local-feat"

    hydrated = hydrate_source_free_entries(
        source_free["prepared"]["portable_factor_sources"],
        owner="alice",
        database=database,
    )
    assert hydrated[0]["source_code"] == source
    assert FactorSourceStore(database=database).metadata(object_id)[
        "source_sha256"
    ] == digest


def test_source_free_hydration_allows_an_exact_delegated_runspec_object(
    tmp_path,
) -> None:
    database = tmp_path / "manager.sqlite"
    object_id = "child:RemoteDemo"
    source = "class RemoteDemo:\n    pass\n"
    raw = source.encode()
    digest = hashlib.sha256(raw).hexdigest()
    source_path = tmp_path / "source.py"
    source_path.write_bytes(raw)
    FactorSourceStore(database=database).store_from_file(
        object_id, source_path, principal="child",
        expected_size=len(raw), expected_sha256=digest,
    )
    entry = {
        "canonical_family_ref": object_id,
        "object_kind": "factor_source",
        "object_id": object_id,
        "source_kind": "custom",
        "source_owner": "child",
        "factor_id": "RemoteDemo",
        "source_sha256": digest,
        "source_bytes": len(raw),
    }

    hydrated = hydrate_source_free_entries(
        [entry], owner="parent", allowed_object_ids={object_id},
        database=database,
    )

    assert hydrated[0]["source_code"] == source


def test_transient_factor_source_transfer_manifest_adds_canonical_identity() -> None:
    source = "class TransientDemo:\n    pass\n"
    digest = hashlib.sha256(source.encode()).hexdigest()

    values = source_transfer_manifest(
        [{
            "factor_id": "TransientDemo",
            "path": "custom_factors/TransientDemo.py",
            "source_code": source,
            "source_sha256": digest,
            "source_bytes": len(source.encode()),
        }],
        owner="alice",
        storage_server_id="local-feat",
    )

    assert values == [{
        "canonical_family_ref": "alice:TransientDemo",
        "source_kind": "custom",
        "source_owner": "alice",
        "source_access_policy": "transient_run_source",
        "factor_id": "TransientDemo",
        "path": "manager_factor_sources/"
        + hashlib.sha256("alice:TransientDemo".encode()).hexdigest()
        + ".py",
        "source_sha256": digest,
        "source_bytes": len(source.encode()),
        "object_kind": "factor_source",
        "object_id": "alice:TransientDemo",
        "storage_server_id": "local-feat",
        "source_code": source,
    }]


def test_origin_registry_keeps_job_adapter_as_fallback(tmp_path) -> None:
    fallback = tmp_path / "artifact.bin"
    fallback.write_bytes(b"artifact")
    transfer = type("Transfer", (), {
        "object_kind": TransferObjectKind.JOB_ARTIFACT,
    })()
    path = ObjectOriginRegistry(
        fallback=lambda _transfer: fallback,
    )(transfer)

    assert path == fallback.resolve()
