from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import threading
from contextlib import contextmanager

from flask import Flask, Response, jsonify, request, session
from werkzeug.serving import make_server


@contextmanager
def order_audit_server():
    app = Flask(__name__)
    app.secret_key = "order-audit-e2e"

    @app.post("/auth/login")
    def login():
        assert request.get_json() == {"username": "alice", "password": "pw"}
        session["username"] = "alice"
        return jsonify(success=True, username="alice")

    @app.post("/api/keep_login")
    def keep_login():
        return jsonify(success=True, keep_login=True)

    @app.get("/static/config/modules.json")
    def modules():
        return jsonify(success=True, modules=[])

    raw = json.dumps({
        "run_id": "run-1",
        "strategies": {"A1": {"groups": [{
            "order_group_id": "G1",
            "status": "partially_filled",
            "products": ["RB.SHF"],
            "requested_quantity": 10.0,
            "filled_quantity": 6.0,
            "active_leaves": 4.0,
            "terminal_unfilled": 4.0,
            "child_count": 1,
        }]}},
    }, separators=(",", ":")).encode()

    @app.post("/api/jobs/job-1/artifacts/order_audit/access")
    def order_audit_access():
        assert session.get("username") == "alice"
        return jsonify(
            success=True,
            artifact={
                "name": "order_audit",
                "content_type": "application/json",
                "content_hash": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            },
            access={
                "url": request.host_url.rstrip("/") + "/data/order_audit",
                "bearer": "order-audit-capability",
                "expected_size": len(raw),
            },
        )

    @app.get("/data/order_audit")
    def order_audit_data():
        assert not request.cookies
        assert request.headers["Authorization"] == "Bearer order-audit-capability"
        return Response(raw, content_type="application/json")

    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def run_cli(command: list[str], args: list[str], env: dict[str, str]):
    return subprocess.run(
        [*command, *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_installed_cli_reads_order_audit_over_real_http(tmp_path):
    # The supported client distribution is App-managed; a system-wide
    # ``factortester`` executable is intentionally not required.  Exercise
    # the same client entrypoint from the current checkout instead.
    command = [sys.executable, "-m", "tools.cli.app"]
    env = {
        **os.environ,
        "FACTORTESTER_HOME": str(tmp_path / "factortester-home"),
    }
    with order_audit_server() as base_url:
        run_cli(command, ["configure", "--base-url", base_url], env)
        run_cli(
            command,
            ["login", "--username", "alice", "--password", "pw"],
            env,
        )
        result = run_cli(
            command, ["job", "orders", "job-1", "--json"], env,
        )

    payload = json.loads(result.stdout)
    assert payload["job_id"] == "job-1"
    assert payload["groups"][0] == {
        "active_leaves": 4.0,
        "child_count": 1,
        "filled_quantity": 6.0,
        "order_group_id": "G1",
        "products": ["RB.SHF"],
        "requested_quantity": 10.0,
        "status": "partially_filled",
        "strategy_id": "A1",
        "terminal_unfilled": 4.0,
    }
