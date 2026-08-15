from __future__ import annotations

import io
from types import SimpleNamespace
from urllib.parse import urlparse

from server.manager.data_plane.streaming import BoundedRequestBody
from server.manager.http.transfer_metrics_routes import TransferMetricsRoutesMixin
from server.manager.http.transfer_metrics_routes import _window_seconds
from server.manager.storage.transfers import TransferTelemetryStore, TransferTicketStore
from server.manager.transfers.models import TransferTicketRole
from server.manager.transfers.models import TransferMode, TransferOperation


def _context(*, attempt_id: str = "attempt-1", size: int = 12):
    return SimpleNamespace(
        transfer=SimpleNamespace(
            transfer_id="transfer-1",
            object_kind="research_attachment",
            operation=TransferOperation.DOWNLOAD,
            source_server_id="node-a",
            destination_server_id="node-b",
        ),
        attempt=SimpleNamespace(
            attempt_id=attempt_id,
            mode=TransferMode.DIRECT_PULL,
            expected_size=size,
            resume_offset=0,
        ),
    )


def test_telemetry_records_stream_bytes_and_dimensions(tmp_path) -> None:
    store = TransferTelemetryStore(
        tmp_path / "transfers.sqlite", server_id="node-b",
    )
    handle = store.begin(
        _context(),
        surface="client",
        action="download",
        process_instance_id="process-1",
        now=100.0,
    )
    store.authorize(handle)
    store.set_expected_bytes(handle, 8, now=101.0)
    store.record_bytes(handle, 8, now=102.0)
    store.finish(handle, status="completed", now=103.0)

    summary = store.summary(now=104.0, since=90.0)
    assert summary["totals"] == {
        "attempts": 1,
        "transferred_bytes": 8,
        "expected_bytes": 8,
        "duration_ms": 3000,
        "average_duration_ms": 3000.0,
        "failed_attempts": 0,
    }
    assert summary["active"]["connections"] == 0
    assert summary["dimensions"][0]["mode"] == "direct_pull"


def test_telemetry_prunes_stale_active_streams_and_keeps_failures(tmp_path) -> None:
    store = TransferTelemetryStore(
        tmp_path / "transfers.sqlite", server_id="node-b",
    )
    handle = store.begin(
        _context(attempt_id="attempt-2"),
        surface="peer",
        action="origin",
        process_instance_id="process-1",
        now=100.0,
    )
    store.authorize(handle)
    store.record_bytes(handle, 3, now=101.0)
    active = store.summary(now=110.0, since=90.0)
    assert active["active"]["connections"] == 1
    store.prune(now=200.0, stale_seconds=30.0, retention_seconds=60.0)
    assert store.summary(now=201.0, since=90.0)["active"]["connections"] == 0

    store.finish(
        handle,
        status="failed",
        failure_reason="destination unavailable",
        now=202.0,
    )
    summary = store.summary(now=203.0, since=90.0)
    assert summary["totals"]["failed_attempts"] == 1
    assert summary["failure_reasons"][0]["failure_reason"] == (
        "destination unavailable"
    )


def test_bounded_request_body_reports_bytes_read() -> None:
    seen: list[int] = []
    body = BoundedRequestBody(
        io.BytesIO(b"payload"),
        length=7,
        on_read=seen.append,
    )
    assert body.read(3) == b"pay"
    assert body.read() == b"load"
    assert seen == [3, 4]


def test_metrics_window_is_bounded() -> None:
    assert _window_seconds("") == 24 * 60 * 60
    assert _window_seconds("60") == 60
    try:
        _window_seconds("59")
    except ValueError as exc:
        assert "window_seconds" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("a sub-minute metrics window must be rejected")


def test_expired_ticket_cleanup_keeps_recent_capabilities(tmp_path) -> None:
    store = TransferTicketStore(tmp_path / "transfers.sqlite", server_id="node-a")
    old = store.issue(
        transfer_id="transfer-old",
        attempt_id="attempt-old",
        role=TransferTicketRole.CLIENT_DOWNLOAD,
        principal="alice",
        node_id="",
        start_offset=0,
        end_offset=1,
        expires_at=100.0,
        now=0.0,
    )
    recent = store.issue(
        transfer_id="transfer-recent",
        attempt_id="attempt-recent",
        role=TransferTicketRole.CLIENT_DOWNLOAD,
        principal="alice",
        node_id="",
        start_offset=0,
        end_offset=1,
        expires_at=950.0,
        now=900.0,
    )
    assert store.cleanup_expired(now=1_000.0, grace_seconds=100.0) == 1
    try:
        store.verify(
            old.bearer,
            required_role=TransferTicketRole.CLIENT_DOWNLOAD,
            attempt_id="attempt-old",
            node_id="",
            start_offset=0,
            end_offset=1,
            now=1_000.0,
        )
    except PermissionError:
        pass
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expired ticket should have been removed")
    assert store.verify(
        recent.bearer,
        required_role=TransferTicketRole.CLIENT_DOWNLOAD,
        attempt_id="attempt-recent",
        node_id="",
        start_offset=0,
        end_offset=1,
        now=901.0,
    ).attempt_id == "attempt-recent"


class _MetricsHandler(TransferMetricsRoutesMixin):
    def __init__(self, store, *, allowed: bool = True) -> None:
        self.state = SimpleNamespace(transfer_telemetry=store)
        self.allowed = allowed
        self.status = None
        self.headers = {}
        self.body = io.BytesIO()
        self.wfile = self.body

    def _require_super_admin_session(self) -> bool:
        if self.allowed:
            return True
        self.send_response(403)
        return False

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, _name: str, _value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass


def test_metrics_summary_is_admin_only_and_bounded(tmp_path) -> None:
    store = TransferTelemetryStore(
        tmp_path / "transfers.sqlite", server_id="node-a",
    )
    denied = _MetricsHandler(store, allowed=False)
    assert denied._get_transfer_metrics(urlparse("/api/transfers/metrics"))
    assert denied.status == 403

    allowed = _MetricsHandler(store)
    assert allowed._get_transfer_metrics(
        urlparse("/api/transfers/metrics?window_seconds=3600")
    )
    assert allowed.status == 200
    assert b'"success": true' in allowed.body.getvalue()
