from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from server.manager import runtime as manager
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.node_models import NewNodeCommand


@contextmanager
def _running_manager(state):
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post_json(
    url: str,
    payload: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    body = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _challenge(base_url: str, node_id: str) -> str:
    with urlopen(
        f"{base_url}/api/federation/node/challenge?"
        + urlencode({"node_id": node_id}),
        timeout=2,
    ) as response:
        return str(json.loads(response.read())["challenge"])


def _signed_headers(
    key: NodeKey,
    *,
    challenge: str,
    method: str,
    path: str,
    body: bytes,
) -> dict[str, str]:
    return {
        "X-FactorTester-Node-ID": key.node_id,
        "X-FactorTester-Node-Challenge": challenge,
        "X-FactorTester-Node-Signature": key.sign_request(
            challenge=challenge,
            method=method,
            path=path,
            body=body,
        ),
    }


def _signed_post(
    base_url: str,
    path: str,
    key: NodeKey,
    payload: dict[str, object],
) -> dict[str, object]:
    body = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    challenge = _challenge(base_url, key.node_id)
    request = Request(
        base_url + path,
        data=body,
        headers={
            "Content-Type": "application/json",
            **_signed_headers(
                key,
                challenge=challenge,
                method="POST",
                path=path,
                body=body,
            ),
        },
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def test_node_enrollment_poll_and_ack_use_signed_7998_protocol(tmp_path) -> None:
    state = manager.ManagerState(tmp_path, "python", server_id="public-b1")
    state.federation_registration_token = "enroll-secret"
    key = NodeKey.load_or_create(tmp_path / "office-a.key", node_id="office-a")

    with _running_manager(state) as base_url:
        enrolled = _post_json(
            f"{base_url}/api/federation/node/enroll",
            key.public_record(),
            headers={"Authorization": "Bearer enroll-secret"},
        )
        assert enrolled["node"]["node_id"] == "office-a"
        assert "public_key" not in enrolled["node"]

        command = state.node_control_hub.enqueue(NewNodeCommand(
            idempotency_key="http-command-1",
            transfer_id="transfer-1",
            attempt_id="attempt-1",
            command_type="source.push",
            target_server_id="office-a",
            payload={"relay_endpoint": "https://public-b2:7997"},
            expires_at=4_000_000_000.0,
        ))
        polled = _signed_post(
            base_url,
            "/api/federation/node/control/poll",
            key,
            {
                "after_sequence": 0,
                "data_endpoint": "http://office-a:7997",
                "reachable_from": [],
                "timeout": 0,
            },
        )
        assert polled["commands"][0]["command_id"] == command.command_id

        acknowledged = _signed_post(
            base_url,
            "/api/federation/node/control/ack",
            key,
            {"command_id": command.command_id},
        )
        assert acknowledged == {"success": True}
        assert state.node_commands.pending(node_id="office-a") == []


def test_node_sse_stream_uses_durable_sequence_and_command_event(tmp_path) -> None:
    state = manager.ManagerState(tmp_path, "python", server_id="public-b1")
    state.federation_registration_token = "enroll-secret"
    key = NodeKey.load_or_create(tmp_path / "office-a.key", node_id="office-a")

    with _running_manager(state) as base_url:
        _post_json(
            f"{base_url}/api/federation/node/enroll",
            key.public_record(),
            headers={"Authorization": "Bearer enroll-secret"},
        )
        command = state.node_control_hub.enqueue(NewNodeCommand(
            idempotency_key="sse-command-1",
            transfer_id="transfer-1",
            attempt_id="attempt-1",
            command_type="source.push",
            target_server_id="office-a",
            payload={},
            expires_at=4_000_000_000.0,
        ))
        path = "/api/federation/node/control?" + urlencode({
            "data_endpoint": "http://office-a:7997",
            "reachable_from": "",
        })
        challenge = _challenge(base_url, key.node_id)
        request = Request(
            base_url + path,
            headers={
                "Accept": "text/event-stream",
                **_signed_headers(
                    key,
                    challenge=challenge,
                    method="GET",
                    path=path,
                    body=b"",
                ),
            },
        )
        with urlopen(request, timeout=2) as response:
            lines = [response.readline().decode("utf-8") for _ in range(4)]

    assert response.headers["Content-Type"].startswith("text/event-stream")
    assert lines[0] == f"id: {command.sequence}\n"
    assert lines[1] == "event: transfer-command\n"
    assert '"target_server_id":"office-a"' in lines[2]
