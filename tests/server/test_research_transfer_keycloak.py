from __future__ import annotations

import sqlite3
import base64
import hashlib
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.identity.keycloak_research import KeycloakResearchAuthorization
from server.identity.keycloak_research_transfer import KeycloakResearchTransferAuthorization
from server.manager.services.research_catalog import ResearchCatalog


def _setup(tmp_path):
    path = tmp_path / "research.sqlite"
    legacy = ResearchCatalog(path)
    research_id = legacy.create_research(owner_ref="alice", title="Research")["research_id"]
    legacy.register_report(research_id, actor="alice", report_id="report", profile_ref="self")
    legacy.add_membership(research_id, actor="alice", principal_ref="bob", profile_ref="work", role="editor")
    catalog = ResearchCatalog(path, profile_authorizer=KeycloakResearchAuthorization())
    record = {"report_id": "report", "owner_ref": "alice", "publication_id": "publication"}
    transfer = SimpleNamespace(principal="bob", principal_identity_id="bob-id",
                               request_owner_manager_id="local", source_server_id="local")
    return catalog, research_id, record, transfer


class Evaluator:
    def __init__(self):
        self.adapter = self
        self.allow = {("research_profile", "read"), ("research_profile", "use"), ("research_profile", "write")}
        self.during = None
    def user_by_identity_id(self, identity):
        if identity != "bob-id":
            return None
        return {"id": "subject-b", "username": "bob", "enabled": True,
                "attributes": {"tr_identity_id": ["bob-id"]}}
    def evaluate(self, _identity, *, candidates):
        values = {(kind, ref, scope): (kind, scope) in self.allow
                  for kind, ref, scopes in candidates for scope in scopes}
        if self.during:
            self.during()
        return values


def test_live_source_decision_handles_member_read_authoring_and_revocation(tmp_path):
    catalog, _rid, record, transfer = _setup(tmp_path)
    evaluator = Evaluator()
    auth = KeycloakResearchTransferAuthorization(catalog, evaluator_factory=lambda: evaluator)
    auth.authorize(transfer=transfer, record=record, metadata={})
    auth.authorize(transfer=transfer, record=record, metadata={"purpose": "report_authoring"})
    evaluator.allow.remove(("research_profile", "write"))
    auth.authorize(transfer=transfer, record=record, metadata={})
    with pytest.raises(PermissionError, match="authoring"):
        auth.authorize(transfer=transfer, record=record, metadata={"purpose": "report_authoring"})
    evaluator.allow.clear()
    # Local public/owner labels cannot override the Keycloak result.
    with pytest.raises(PermissionError, match="Keycloak denied"):
        auth.authorize(transfer=transfer, record={**record, "visibility": "public"}, metadata={})


def test_foreign_identity_and_unavailable_delegation_fail_closed(tmp_path):
    catalog, _rid, record, transfer = _setup(tmp_path)
    evaluator = Evaluator()
    auth = KeycloakResearchTransferAuthorization(catalog, evaluator_factory=lambda: evaluator)
    transfer.principal = "alice"
    with pytest.raises(PermissionError, match="principal"):
        auth.authorize(transfer=transfer, record=record, metadata={})
    transfer.principal = "bob"
    transfer.principal_identity_id = ""
    with pytest.raises(PermissionError, match="stable user"):
        auth.authorize(transfer=transfer, record=record, metadata={})
    transfer.principal_identity_id = "bob-id"
    transfer.request_owner_manager_id = "remote"
    with pytest.raises(PermissionError, match="delegation"):
        auth.authorize(transfer=transfer, record=record, metadata={})
    auth = KeycloakResearchTransferAuthorization(catalog, evaluator_factory=lambda: evaluator,
        verify_foreign_delegation=lambda *, transfer, identity_id: identity_id == "bob-id")
    auth.authorize(transfer=transfer, record=record, metadata={})


def test_policy_update_during_source_evaluation_cannot_use_old_profile_decision(tmp_path):
    catalog, rid, record, transfer = _setup(tmp_path)
    evaluator = Evaluator()
    def change():
        with sqlite3.connect(catalog.db_path) as db:
            db.execute("""INSERT INTO research_profile_policy_versions VALUES (?, 'bob', 'work', 1)
                ON CONFLICT(research_id,principal_ref,profile_ref) DO UPDATE SET revision=revision+1""", (rid,))
    evaluator.during = change
    auth = KeycloakResearchTransferAuthorization(catalog, evaluator_factory=lambda: evaluator)
    with pytest.raises(PermissionError, match="Keycloak denied"):
        auth.authorize(transfer=transfer, record=record, metadata={})


def test_report_only_download_does_not_grant_authoring_and_unregistered_bytes_are_denied(tmp_path):
    catalog, _rid, record, transfer = _setup(tmp_path)
    evaluator = Evaluator()
    evaluator.allow = {("research_report", "read"), ("research_report", "use")}
    auth = KeycloakResearchTransferAuthorization(catalog, evaluator_factory=lambda: evaluator)
    auth.authorize(transfer=transfer, record=record, metadata={})
    with pytest.raises(PermissionError, match="authoring"):
        auth.authorize(transfer=transfer, record=record, metadata={"purpose": "report_authoring"})
    with pytest.raises(PermissionError, match="not registered"):
        auth.authorize(transfer=transfer, record={**record, "owner_ref": "other"}, metadata={})


def test_7997_rechecks_live_policy_even_for_a_previously_issued_ticket(tmp_path):
    from server.manager.data_plane.context import DataPlaneRuntime
    from server.manager.data_plane.server import ClientDataPlaneHTTPServer
    from server.manager.objects.adapters.public_research import PublicResearchOriginAdapter
    from server.manager.storage.transfers import TransferAttemptStore, TransferStore, TransferTicketStore
    from server.manager.transfers.coordinator import DownloadRequest, TransferCoordinator
    from server.manager.transfers.planner import NodeEndpoint
    from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary
    from tools.cli.release.research_reporting.public_research.object_store import PublicResearchObjectStore

    catalog, _rid, _record, _transfer = _setup(tmp_path)
    evaluator = Evaluator()
    auth = KeycloakResearchTransferAuthorization(catalog, evaluator_factory=lambda: evaluator)
    raw = b"isolated 7997 research object"
    digest = hashlib.sha256(raw).hexdigest()
    library = PublicResearchLibrary(tmp_path / "public", storage_server_id="local")
    publication = library.sync({"report_id": "report", "owner_ref": "alice", "projection": {
        "schema_version": 2, "report_id": "report", "generation": 1, "projection_hash": "hash",
        "title": "Report", "components": [], "assets": [], "local_resources": [],
        "attachments": [{"attachment_ref": "attachment:sha256:" + digest, "filename": "a.txt",
                         "media_type": "text/plain", "content_hash": digest,
                         "content_base64": base64.b64encode(raw).decode()}],
    }})["publication_id"]
    database = tmp_path / "transfers.sqlite"
    coordinator = TransferCoordinator(manager_id="local", client_data_endpoint="http://127.0.0.1:7997",
        requests=TransferStore(database, server_id="local"), attempts=TransferAttemptStore(database, server_id="local"),
        tickets=TransferTicketStore(database, server_id="local"))
    now = time.time()
    access = coordinator.prepare_download(DownloadRequest(idempotency_key="research", principal="bob",
        principal_identity_id="bob-id", storage_server_id="local", job_id="", artifact_name="",
        expected_size=len(raw), expected_sha256=digest, expires_at=now + 300, object_kind="research_attachment",
        object_id=publication + ":attachment:sha256:" + digest), endpoints={"local": NodeEndpoint(
            server_id="local", peer_data_endpoint="http://127.0.0.1:17997",
            peer_control_endpoint="http://127.0.0.1:17998", observed_at=now, expires_at=now+300, online=True)}, now=now)
    runtime = DataPlaneRuntime(server_id="local", transfer_database=database, staging_root=tmp_path / "incoming",
        origin_resolver=PublicResearchOriginAdapter(PublicResearchObjectStore(library), authorization=auth))
    server = ClientDataPlaneHTTPServer(("127.0.0.1", 0), runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}" + access.path
        headers = {"Authorization": "Bearer " + access.bearer}
        with urlopen(Request(url, headers=headers), timeout=10) as response:
            assert response.read() == raw
        evaluator.allow.clear()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url, headers=headers), timeout=10)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
