"""Manager storage control must not depend on a running Job worker."""

import json

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
        return 0

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
    assert repo.calls == [("inventory", {
        "owner": "alice", "category": "output:result", "limit": 1,
        "offset": 0,
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
