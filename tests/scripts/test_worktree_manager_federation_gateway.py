"""Focused federation behavior tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import pytest
from server.manager import runtime as manager
from server.manager.domain.federation import FederatedGateway, ServiceRoute
from server.manager.http.peer_handler import peer_control_handler
from server.manager.network_endpoints import server_endpoints


def _federated_state(tmp_path, node_id: str, octet: int):
    root = tmp_path / node_id
    root.mkdir()
    state = manager.ManagerState(
        root,
        "python",
        server_role="main",
        server_id=node_id,
        state_root=root / "state",
    )
    state.configure_transfer_endpoints(server_endpoints(
        client_control_endpoint=f"https://{node_id}.example:7998",
        client_data_endpoint=f"https://{node_id}.example:7997",
        overlay_bind_address=f"10.77.0.{octet}",
    ))
    return state


def test_authenticated_bootstrap_returns_multi_node_directory(
    tmp_path, monkeypatch,
) -> None:
    joining = _federated_state(tmp_path, "node-a", 10)
    bootstrap = _federated_state(tmp_path, "node-b", 11)
    third = _federated_state(tmp_path, "node-c", 12)
    bootstrap.federation_registration_token = "cluster-token"
    bootstrap.federation_registry.register(
        third.registration_payload("https://node-c.example:7998"),
    )
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
        "https://node-b.example:7998",
    )
    server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0), peer_control_handler(bootstrap),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        request = Request(
            endpoint + "/api/federation/register",
            data=json.dumps(joining.registration_payload(
                "https://node-a.example:7998",
            )).encode("utf-8"),
            headers={
                "Authorization": "Bearer cluster-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            value = json.load(response)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert value["bootstrap_server_id"] == "node-b"
    assert {item["server_id"] for item in value["nodes"]} == {
        "node-b", "node-c",
    }
    assert value["peer"]["server_id"] == "node-b"
    assert "node-a" not in {item["server_id"] for item in value["nodes"]}
    assert all("proxy_token" not in item for item in value["nodes"])

    direct_registration_urls = joining.accept_federation_catalog({
        **value,
        "_roundtrip_ms": 7,
    })
    assert joining.federation_registry.describe("node-b") is not None
    assert joining.federation_registry.describe("node-c") is None
    assert direct_registration_urls == (
        "http://10.77.0.12:17998/api/federation/register",
    )


@pytest.mark.parametrize("tamper", ["server_id", "endpoint"])
def test_registration_rejects_unsigned_route_identity_before_mutation(
    tmp_path,
    tamper,
) -> None:
    joining = _federated_state(tmp_path, "node-a", 10)
    bootstrap = _federated_state(tmp_path, "node-b", 11)
    bootstrap.federation_registration_token = "cluster-token"
    payload = joining.registration_payload("https://node-a.example:7998")
    if tamper == "server_id":
        payload["server_id"] = "forged-node"
    else:
        payload["endpoint"] = "https://forged.example:7998"
    server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0), peer_control_handler(bootstrap),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        request = Request(
            endpoint + "/api/federation/register",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer cluster-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as raised:
            urlopen(request, timeout=3)
        assert raised.value.code == 400
        raised.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert bootstrap.federation_registry.describe("node-a") is None
    assert bootstrap.federation_registry.describe("forged-node") is None
    with pytest.raises(KeyError):
        bootstrap.transfer_endpoints.require("node-a")


def test_registration_response_uses_signed_public_endpoint_not_host_header(
    tmp_path,
    monkeypatch,
) -> None:
    joining = _federated_state(tmp_path, "node-a", 10)
    bootstrap = _federated_state(tmp_path, "node-b", 11)
    bootstrap.federation_registration_token = "cluster-token"
    monkeypatch.delenv("FACTORTESTER_MANAGER_PUBLIC_ENDPOINT", raising=False)
    server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0), peer_control_handler(bootstrap),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        request = Request(
            endpoint + "/api/federation/register",
            data=json.dumps(
                joining.federation_registration_payload()
            ).encode("utf-8"),
            headers={
                "Authorization": "Bearer cluster-token",
                "Content-Type": "application/json",
                "Host": "10.77.0.11:17998",
            },
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            value = json.load(response)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert value["peer"]["endpoint"] == "https://node-b.example:7998"
    assert value["peer"]["transfer_node"]["client_control_endpoint"] == (
        "https://node-b.example:7998"
    )

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
