"""Focused federation behavior tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from server.manager import runtime as manager
from server.manager.domain.federation import FederatedGateway, ServiceRoute
from server.manager.http.peer_handler import peer_control_handler

def test_federated_gateway_reaches_service_only_through_peer_manager(tmp_path) -> None:
    class ServiceHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path.endswith("/stream"):
                body = b'data: {"job_id":"job-1","status":"running"}\n\n'
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps({"success": True, "job_id": "job-1"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            return

    service = ThreadingHTTPServer(("127.0.0.1", 0), ServiceHandler)
    service_thread = threading.Thread(target=service.serve_forever, daemon=True)
    service_thread.start()
    service_port = service.server_address[1]
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        server_id="remote-main",
        fixed_port=service_port,
        fixed_branch="main",
        state_root=tmp_path / "manager-state",
    )
    state.capability_path.write_text("manager-capability", encoding="ascii")
    state.federation_proxy_path.write_text("proxy-token", encoding="ascii")
    gateway = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        peer_control_handler(state),
    )
    manager_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    manager_thread.start()
    endpoint = f"http://127.0.0.1:{gateway.server_address[1]}"
    route = ServiceRoute(
        server_id="remote-main",
        role="main",
        branch="main",
        revision="abc123",
        port=service_port,
        endpoint=endpoint,
        peer_control_endpoint=endpoint,
        proxy_token="proxy-token",
        remote=True,
        online=True,
    )
    federated = FederatedGateway(timeout=3)
    try:
        response = federated.request(
            route,
            path="/api/jobs/job-1",
            principal="user@1",
        )
        assert response.status == 200
        assert response.json_object()["job_id"] == "job-1"

        with federated.open_stream(
            route,
            path="/api/jobs/job-1/stream",
            principal="user@1",
        ) as stream:
            assert b"job-1" in stream.read()

        capability = federated.capabilities(
            route,
            payload={"summary": True},
        )
        assert capability["target"]["server_id"] == "remote-main"
        assert capability["target"]["port"] == service_port
        assert capability["target"]["branch"] == "main"
        assert capability["ports"][0]["port"] == service_port
    finally:
        gateway.shutdown()
        gateway.server_close()
        manager_thread.join(timeout=2)
        service.shutdown()
        service.server_close()
        service_thread.join(timeout=2)

