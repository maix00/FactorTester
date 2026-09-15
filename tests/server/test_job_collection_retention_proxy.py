"""Bulk retention deletes must reach the service, not the Manager shell.

``DELETE /api/jobs/artifacts`` (clear every retained result the caller owns)
and ``DELETE /api/jobs`` (clear terminal history) carry no job id, so the
per-job proxy pattern cannot match them.  Before this branch existed the CLI
received an HTML page from the shell instead of JSON.
"""

from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.http import job_proxy_routes
from server.manager.http.gateway import GatewayResponse


class _Handler(job_proxy_routes.JobProxyRoutesMixin):
    """Real mixin so sibling helpers resolve, with routing stubbed out."""

    def __init__(self, calls, *, session=None, routes=("route-1",)):
        self.headers = {}
        self._session_value = session
        self._routes = list(routes)
        self.sent = []
        self.state = SimpleNamespace(
            server_id="local",
            route_request=lambda *a, **k: calls.append(k) or GatewayResponse(
                200, b'{"success": true}', "application/json",
            ),
        )

    def _session(self):
        return self._session_value

    def _visitor_mode(self):
        return None

    def _job_routes(self, parsed, principal=None, *, for_artifact_storage=False):
        return list(self._routes)

    def _send_gateway_response(self, response, **kwargs):
        self.sent.append(kwargs)


def _handler(calls, *, session=None, routes=("route-1",)):
    return _Handler(calls, session=session, routes=routes)


@pytest.mark.parametrize("path", ["/api/jobs/artifacts", "/api/jobs"])
def test_collection_delete_is_forwarded_with_query(monkeypatch, path):
    calls = []
    monkeypatch.setattr(job_proxy_routes, "json_response", lambda *a, **k: calls.append("json"))
    handler = _handler(calls, session={"username": "alice"})
    assert handler._proxy_job_request(urlparse(f"{path}?workspace_id=w1"), method="DELETE") is True
    assert calls == [{"path": f"{path}?workspace_id=w1", "principal": "alice", "method": "DELETE"}]


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH"])
def test_collection_paths_reject_methods_other_than_delete(monkeypatch, method):
    seen = []
    monkeypatch.setattr(
        job_proxy_routes, "json_response",
        lambda handler, body, code: seen.append((body.get("error"), code)),
    )
    handler = _handler(seen, session={"username": "alice"})
    assert handler._proxy_job_request(urlparse("/api/jobs/artifacts"), method=method) is True
    assert seen == [("method not allowed", 405)]


def test_collection_delete_requires_login(monkeypatch):
    seen = []
    monkeypatch.setattr(
        job_proxy_routes, "json_response",
        lambda handler, body, code: seen.append((body.get("error"), code)),
    )
    handler = _handler(seen, session=None)
    assert handler._proxy_job_request(urlparse("/api/jobs/artifacts"), method="DELETE") is True
    assert seen == [("login required", 401)]


def test_collection_delete_reports_missing_storage(monkeypatch):
    seen = []
    monkeypatch.setattr(
        job_proxy_routes, "json_response",
        lambda handler, body, code: seen.append((body.get("error"), code)),
    )
    handler = _handler(seen, session={"username": "alice"}, routes=())
    assert handler._proxy_job_request(urlparse("/api/jobs"), method="DELETE") is True
    assert seen == [("retention storage is unavailable", 503)]


def test_per_job_delete_still_uses_the_job_pattern(monkeypatch):
    calls = []
    monkeypatch.setattr(job_proxy_routes, "json_response", lambda *a, **k: calls.append("json"))
    handler = _handler(calls, session={"username": "alice"})
    assert handler._proxy_job_request(
        urlparse("/api/jobs/job-1/artifacts"), method="DELETE",
    ) is True
    assert calls == [{"path": "/api/jobs/job-1/artifacts", "principal": "alice", "method": "DELETE"}]
