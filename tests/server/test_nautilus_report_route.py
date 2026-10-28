"""The isolated report response stays authenticated, bounded, and opaque."""

from __future__ import annotations

import hashlib
from io import BytesIO
from types import SimpleNamespace

from server.manager.http import job_transfer_routes


class _Response:
    status = 200

    def __init__(self, body):
        self._body = BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, count):
        return self._body.read(count)


class _Handler(job_transfer_routes.JobTransferRoutesMixin):
    def __init__(self, body: bytes, *, authenticated=True):
        self.body = body
        self.authenticated = authenticated
        self.state = SimpleNamespace(prepare_artifact_download=lambda **_: {
            "url": "https://data.example.test/report", "bearer": "one-time-ticket",
        })
        self.wfile = BytesIO()
        self.status = None
        self.response_headers = {}

    def _session(self):
        return {"username": "owner"} if self.authenticated else None

    def _job_routes(self, *_args, **_kwargs):
        return [SimpleNamespace(server_id="server-a")]

    def _artifact_metadata(self, routes, *, job_id, name, principal):
        assert job_id == "job-a" and principal == "owner"
        if name == "nautilus_receipt.json":
            return routes[0], {"state": "active"}, "owner"
        if name == "tearsheet.html":
            return routes[0], {
                "name": name, "size_bytes": len(self.body),
                "content_hash": hashlib.sha256(self.body).hexdigest(),
            }, "owner"
        return None

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass


def test_isolated_report_has_document_sandbox_and_digest_check(monkeypatch):
    body = b"<html><script>window.x=1</script></html>"
    handler = _Handler(body)
    captured = []

    class _Opener:
        def open(self, request, timeout):
            captured.append((request, timeout))
            return _Response(body)

    monkeypatch.setattr(job_transfer_routes, "build_opener", lambda *_: _Opener())
    parsed = SimpleNamespace(
        path="/api/jobs/job-a/artifacts/tearsheet.html", query="view=isolated",
    )
    assert handler._serve_isolated_nautilus_report(parsed) is True
    assert handler.status == 200
    assert handler.wfile.getvalue() == body
    assert "sandbox allow-scripts" in handler.response_headers["Content-Security-Policy"]
    assert "allow-same-origin" not in handler.response_headers["Content-Security-Policy"]
    assert handler.response_headers["Content-Disposition"].startswith("inline")
    assert captured[0][0].get_header("Authorization") == "Bearer one-time-ticket"


def test_isolated_report_rejects_changed_bytes(monkeypatch):
    body = b"<html>expected</html>"
    handler = _Handler(body)

    class _Opener:
        def open(self, request, timeout):
            return _Response(b"<html>changed!</html>")

    monkeypatch.setattr(job_transfer_routes, "build_opener", lambda *_: _Opener())
    parsed = SimpleNamespace(
        path="/api/jobs/job-a/artifacts/tearsheet.html", query="view=isolated",
    )
    assert handler._serve_isolated_nautilus_report(parsed) is True
    assert handler.status == 503
    assert handler.response_headers.get("Content-Type", "").startswith("application/json")
    assert handler.wfile.getvalue().startswith(b"{")
