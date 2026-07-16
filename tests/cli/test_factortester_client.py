from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from flask import Flask, jsonify, request, session
from werkzeug.serving import make_server

from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession


@contextmanager
def running_server(app: Flask) -> Iterator[str]:
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def fake_server() -> Iterator[str]:
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.post("/login")
    def login():
        data = request.get_json()
        if data == {"username": "alice", "password": "pw"}:
            session["username"] = "alice"
            return jsonify(success=True, username="alice")
        return jsonify(success=False, error="bad login"), 401

    @app.post("/api/workspaces")
    def create_workspace():
        assert session.get("username") == "alice"
        return jsonify(success=True, workspace={"workspace_id": "workspace-1", "revision": 1}), 201

    @app.get("/api/workspaces")
    def list_workspaces():
        assert session.get("username") == "alice"
        return jsonify(success=True, workspaces=[{"workspace_id": "workspace-1", "revision": 1}])

    @app.post("/api/runs")
    def submit_run():
        payload = request.get_json()
        assert payload["workspace_id"] == "workspace-1"
        return jsonify(success=True, run_id="run-1", jobs=[{"job_id": "job-1", "kind": "ic"}]), 202

    @app.get("/api/jobs")
    def list_jobs():
        return jsonify(success=True, jobs=[{"job_id": "job-1", "status": "queued"}])

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_page":
            return jsonify(success=True, parent=parent, modules=[{"key": "single_factor_page/setting_template", "label": "模板", "kind": "tab"}])
        return jsonify(success=True, modules=[{"key": "single_factor_page", "label": "因子家族测试设置", "kind": "module", "has_children": True}])

    @app.get("/static/config/modules.json")
    def home_modules():
        return jsonify(success=True, modules=[{"id": "single_factor_test", "title": "单因子测试"}])

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(
            success=True,
            application=application,
            tab_lists={"local-settings": [{"key": "engine", "label": "执行引擎"}]},
            defaults={"engine_mode": {"value": "auto", "label": "执行模式", "control_template": "select", "tab_key": "engine"}},
        )

    @app.get("/api/backtest/settings/<application>/tabs/<tab_key>")
    def tab(application: str, tab_key: str):
        return jsonify(
            success=True,
            application=application,
            tab={"key": tab_key, "label": "执行引擎"},
            settings=[{"key": "engine_mode", "label": "执行模式", "control_template": "select", "default": "auto", "tab": tab_key}],
        )

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, product_groups=[{"id": "pg-1", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library():
        return jsonify(success=True, factors=[{"alias": "SgCCS|N:2m"}])

    with running_server(app) as url:
        yield url


def test_client_uses_real_http_and_cookies(fake_server: str, tmp_path) -> None:
    client = FactorTesterClient(HttpSession(fake_server, cookies=tmp_path / "cookies.lwp"))

    assert client.login("alice", "pw")["username"] == "alice"
    workspace = client.create_workspace(factor_family_alias="MmRet")
    assert workspace["workspace_id"] == "workspace-1"
    assert client.list_workspaces()[0]["workspace_id"] == "workspace-1"
    assert client.submit_run("workspace-1", 1, analyses=["ic"])["run_id"] == "run-1"
    assert client.list_jobs(workspace_id="workspace-1")[0]["job_id"] == "job-1"
    assert client.list_modules()[0]["key"] == "single_factor_test"
    assert client.list_modules(parent="single_factor_page")[0]["kind"] == "tab"


def test_client_discards_corrupt_cookie_jar_without_traceback(fake_server: str, tmp_path) -> None:
    cookie_file = tmp_path / "cookies.lwp"
    cookie_file.write_text("not an LWP cookie jar\n", encoding="utf-8")

    client = FactorTesterClient(HttpSession(fake_server, cookies=cookie_file))

    assert client.list_modules()[0]["key"] == "single_factor_test"
    assert cookie_file.read_text(encoding="utf-8").startswith("#LWP-Cookies-2.0")


def test_client_fetches_settings_and_candidates(fake_server: str, tmp_path) -> None:
    client = FactorTesterClient(HttpSession(fake_server, cookies=tmp_path / "cookies.lwp"))
    client.login("alice", "pw")

    assert client.manifest("group_test")["application"] == "group_test"
    assert client.tab_manifest("group_test", "engine")["tab"]["key"] == "engine"
    assert client.list_candidates("product_path_selection")[0]["id"] == "pg-1"
    assert client.list_candidates("factor_candidates")[0]["alias"] == "SgCCS|N:2m"


def test_client_detects_old_module_endpoint_when_parent_is_ignored(tmp_path) -> None:
    app = Flask(__name__)

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[{"key": "single_factor_family_test"}])

    with running_server(app) as url:
        client = FactorTesterClient(HttpSession(url, cookies=tmp_path / "cookies.lwp"))
        with pytest.raises(RuntimeError, match="分层导航版本"):
            client.list_modules(parent="single_factor_family_test")
