"""Manager storage control must not depend on a running Job worker."""

import json
import io
from types import SimpleNamespace
from urllib.parse import urlparse

from server.manager.http.job_proxy_routes import JobProxyRoutesMixin
from server.manager.services.job_storage_control import job_storage_response


class _Repository:
    def __init__(self):
        self.calls = []

    def storage_inventory(self, **kwargs):
        self.calls.append(("inventory", kwargs))
        return {"covered_bytes": 4, "storage_server_id": "local",
                "categories": [], "cleanup_preview": {}}

    def storage_breakdown(self, **kwargs):
        return {"artifact_bytes": 4}

    def storage_quota(self, **kwargs):
        return 8

    def storage_servers(self, **kwargs):
        return []

    def mark_cleanup_outputs_deleted(self, **kwargs):
        self.calls.append(("cleanup", kwargs))
        return []

    def storage_usage(self, **kwargs):
        return 4

    def load_artifact(self, **kwargs):
        self.calls.append(("load_artifact", kwargs))
        return {"state": "active", "artifact_role": "input"}


def test_inventory_scopes_principal_without_worker():
    repo = _Repository()
    response = job_storage_response(
        path="/api/jobs/storage?limit=1&category=output%3Aresult",
        principal="alice", method="GET", repository=repo,
    )
    assert response.status == 200
    assert json.loads(response.body)["usage_bytes"] == 4
    assert json.loads(response.body)["quota_scope"] == "measured_account_storage"
    assert json.loads(response.body)["excluded_scopes"] == []
    assert repo.calls == [("inventory", {
        "owner": "alice", "category": "output:result", "limit": 1,
        "offset": 0, "group": "", "job_id": "",
    })]


def test_manager_forwards_business_group_and_job_cleanup_scope():
    repo = _Repository()
    response = job_storage_response(
        path="/api/jobs/storage?group=output%3Aimage&job_id=job-1",
        principal="alice", method="GET", repository=repo,
    )
    assert response.status == 200
    assert repo.calls == [("inventory", {
        "owner": "alice", "category": "", "limit": 50, "offset": 0,
        "group": "output:image", "job_id": "job-1",
    })]


def test_cleanup_requires_preview_token():
    repo = _Repository()
    response = job_storage_response(
        path="/api/jobs/artifacts?cleanup=eligible&expected_count=1&expected_bytes=4",
        principal="alice", method="DELETE", repository=repo,
    )
    assert response.status == 409
    assert not repo.calls


def test_public_principal_cannot_use_storage():
    response = job_storage_response(
        path="/api/jobs/storage", principal="__public_jobs__", method="GET",
        repository=_Repository(),
    )
    assert response.status == 401


def test_single_input_cannot_be_removed_from_storage_control():
    repo = _Repository()
    response = job_storage_response(
        path="/api/jobs/job-1/artifacts/source.py", principal="alice",
        method="DELETE", repository=repo,
    )
    assert response.status == 409
    assert repo.calls == [("load_artifact", {
        "job_id": "job-1", "owner": "alice", "name": "source.py",
    })]


def test_deferred_cleanup_route_uses_session_principal_and_control_authority():
    calls = []

    class Store:
        def deferred_output_cleanups(self, principal):
            calls.append(("list", principal))
            return []

        def queue_deferred_output_cleanup(self, **kwargs):
            calls.append(("queue", kwargs))
            return {"request_id": "a" * 32, "status": "pending"}

        def cancel_deferred_output_cleanup(self, **kwargs):
            calls.append(("cancel", kwargs))
            return {"request_id": kwargs["request_id"], "status": "cancelled"}

    class Handler(JobProxyRoutesMixin):
        def __init__(self, session):
            self.session = session
            self.state = SimpleNamespace(control_store=Store())
            self.status = None
            self.wfile = io.BytesIO()

        def _session(self):
            return self.session

        def _json_body(self, _limit):
            return {"server_id": "remote", "expected_bytes": 70,
                    "expected_count": 2, "observed_at": "2026-10-15T02:00:00Z",
                    "principal": "bob"}

        def send_response(self, status):
            self.status = status

        def send_header(self, *_args):
            pass

        def end_headers(self):
            pass

    handler = Handler({"username": "alice"})
    base = "/api/storage/deferred-job-cleanup"
    assert handler._deferred_job_cleanup_route(urlparse(base), method="POST")
    assert handler.status == 200
    assert calls[-1] == ("queue", {"principal": "alice", "server_id": "remote",
                                   "expected_bytes": 70, "expected_count": 2,
                                   "observed_at": "2026-10-15T02:00:00Z"})
    assert handler._deferred_job_cleanup_route(urlparse(base), method="GET")
    assert calls[-1] == ("list", "alice")
    assert handler._deferred_job_cleanup_route(
        urlparse(f"{base}/{'a' * 32}"), method="DELETE",
    )
    assert calls[-1] == ("cancel", {"principal": "alice", "request_id": "a" * 32})
    anonymous = Handler(None)
    assert anonymous._deferred_job_cleanup_route(urlparse(base), method="POST")
    assert anonymous.status == 401
