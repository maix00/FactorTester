from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager

from flask import Flask, jsonify, request, session
from werkzeug.serving import make_server


@contextmanager
def order_audit_server():
    app = Flask(__name__)
    app.secret_key = "order-audit-e2e"

    @app.post("/login")
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

    @app.get("/api/jobs/job-1/artifacts/order_audit")
    def order_audit():
        assert session.get("username") == "alice"
        return jsonify(
            run_id="run-1",
            strategies={"A1": {"groups": [{
                "order_group_id": "G1",
                "status": "partially_filled",
                "products": ["RB.SHF"],
                "requested_quantity": 10.0,
                "filled_quantity": 6.0,
                "active_leaves": 4.0,
                "terminal_unfilled": 4.0,
                "child_count": 1,
            }]}},
        )

    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def run_cli(executable: str, args: list[str], env: dict[str, str]):
    return subprocess.run(
        [executable, *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_installed_cli_reads_order_audit_over_real_http(tmp_path):
    executable = shutil.which("factortester")
    assert executable, "install factortester into the active test environment"
    env = {
        **os.environ,
        "FACTORTESTER_HOME": str(tmp_path / "factortester-home"),
    }
    with order_audit_server() as base_url:
        run_cli(executable, ["configure", "--base-url", base_url], env)
        run_cli(
            executable,
            ["login", "--username", "alice", "--password", "pw"],
            env,
        )
        result = run_cli(
            executable, ["job", "orders", "job-1", "--json"], env,
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
