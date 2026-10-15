from __future__ import annotations

import os
import io
import json
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.services.profile_storage_inventory import (
    ProfileStorageInventoryIncomplete,
    profile_storage_projection,
    scan_profile_storage,
)
from server.manager.http.core_get_routes import CoreGetRoutesMixin
from server.manager.http.federation.public_data import FederationPublicDataRoutesMixin


def test_profile_storage_inventory_classifies_one_principal_without_double_counting(
    tmp_path,
) -> None:
    root = tmp_path / "users" / "alice" / "profiles" / "self"
    report = root / "research" / "report-1" / "REPORT.md"
    upload = root / "uploads" / "chart.png"
    draft = root / "factor-worktree" / "factor.py"
    for target, data in ((report, b"report"), (upload, b"image"),
                         (draft, b"source")):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    hardlink = root / "reports" / "copy.md"
    hardlink.parent.mkdir(parents=True)
    os.link(report, hardlink)
    (root / "uploads" / "external").symlink_to(tmp_path)
    os.link(report, root / "uploads" / "report-copy.md")
    other = tmp_path / "users" / "bob" / "profiles" / "self" / "uploads" / "secret"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"ignore-me")

    value = scan_profile_storage(tmp_path, "alice")
    assert value["bytes"] == len(b"reportimagesource")
    assert value["categories"] == {
        "research_reports": {"bytes": 6, "file_count": 1},
        "profile_uploads": {"bytes": 5, "file_count": 1},
        "profile_workspaces": {"bytes": 6, "file_count": 1},
    }
    assert value["file_count"] == 5


def test_profile_storage_inventory_fails_closed_on_limits_or_unsafe_root(
    tmp_path,
) -> None:
    root = tmp_path / "users" / "alice" / "profiles" / "self"
    root.mkdir(parents=True)
    (root / "a").write_text("a")
    (root / "b").write_text("b")
    with pytest.raises(ProfileStorageInventoryIncomplete, match="file limit"):
        scan_profile_storage(tmp_path, "alice", max_files=1)
    (tmp_path / "users" / "alice" / "profiles").rename(
        tmp_path / "users" / "alice" / "profile-data"
    )
    (tmp_path / "users" / "alice" / "profiles").symlink_to("profile-data")
    with pytest.raises(ProfileStorageInventoryIncomplete, match="root"):
        scan_profile_storage(tmp_path, "alice")
    (tmp_path / "users" / "alice" / "profiles").unlink()
    (tmp_path / "users" / "alice" / "profiles").symlink_to("missing")
    with pytest.raises(ProfileStorageInventoryIncomplete, match="root"):
        scan_profile_storage(tmp_path, "alice")


def test_profile_inventory_route_is_session_scoped(tmp_path) -> None:
    alice = tmp_path / "users" / "alice" / "profiles" / "self" / "uploads" / "a"
    bob = tmp_path / "users" / "bob" / "profiles" / "self" / "uploads" / "b"
    for path, value in ((alice, b"alice"), (bob, b"bob-is-larger")):
        path.parent.mkdir(parents=True)
        path.write_bytes(value)

    class Handler(CoreGetRoutesMixin):
        def __init__(self, session, store=None):
            self._current_session = session
            self.state = SimpleNamespace(data_root=tmp_path, server_id="server-a",
                                         control_store=store)
            self.headers = {}
            self.wfile = io.BytesIO()
            self.status = None

        def _public_login_gate(self, _parsed, *, method):
            assert method == "GET"
            return True

        def _session(self):
            return self._current_session

        def send_response(self, status):
            self.status = status

        def send_header(self, _name, _value):
            pass

        def end_headers(self):
            pass

    path = urlparse("/api/storage/profile-inventory?principal=bob")
    class Control:
        def protected_entity_metadata_usage(self, principal):
            assert principal == "alice"
            return {"factors": {"bytes": 7, "item_count": 1},
                    "product_groups": {"bytes": 0, "item_count": 0}}

    handler = Handler({"username": "alice"}, Control())
    assert handler._get_entry_routes(path) is True
    response = json.loads(handler.wfile.getvalue())
    assert handler.status == 200
    assert response["principal"] == "alice"
    assert response["bytes"] == 5
    assert response["quota_included"] is False
    assert response["protected_metadata"]["factors"]["bytes"] == 7
    assert response["cross_server"]["coverage_complete"] is False
    assert response["cross_server"]["total_bytes"] is None

    anonymous = Handler(None)
    assert anonymous._get_entry_routes(path) is True
    assert anonymous.status == 401
    assert b"bob" not in anonymous.wfile.getvalue()


def test_profile_projection_never_treats_offline_or_stale_peer_as_zero(tmp_path) -> None:
    local = scan_profile_storage(tmp_path, "alice")
    remote = {"bytes": 9, "observed_at": 1.0, "categories": {
        "research_reports": {"bytes": 9, "file_count": 1},
        "profile_uploads": {"bytes": 0, "file_count": 0},
        "profile_workspaces": {"bytes": 0, "file_count": 0},
    }}
    complete = profile_storage_projection("local", local, [
        {"storage_server_id": "remote", "status": "current", "inventory": remote},
        {"storage_server_id": "remote", "status": "current", "inventory": remote},
    ])
    assert complete["coverage_complete"] is True
    assert complete["total_bytes"] == 9
    assert len(complete["servers"]) == 2
    stale = profile_storage_projection("local", local, [
        {"storage_server_id": "remote", "status": "stale", "inventory": remote},
        {"storage_server_id": "offline", "status": "unavailable", "inventory": None},
    ])
    assert stale["coverage_complete"] is False
    assert stale["total_bytes"] is None
    assert stale["measured_current_bytes"] == 0
    assert [row["status"] for row in stale["servers"]] == [
        "current", "stale", "unavailable",
    ]
    invalid = profile_storage_projection("local", local, [
        {"storage_server_id": "remote", "status": "current",
         "inventory": {**remote, "bytes": 999}},
    ])
    assert invalid["servers"][1]["status"] == "unavailable"


def test_peer_profile_storage_requires_account_identity(tmp_path) -> None:
    class Peer(FederationPublicDataRoutesMixin):
        state = SimpleNamespace(data_root=tmp_path, server_id="source")

    peer = Peer()
    value = peer._public_data_value(
        kind="storage", operation="profile-inventory",
        principal="alice", payload={},
    )
    assert value["storage_server_id"] == "source"
    assert value["bytes"] == 0
    with pytest.raises(PermissionError, match="account identity"):
        peer._public_data_value(
            kind="storage", operation="profile-inventory",
            principal="__public_jobs__", payload={},
        )
