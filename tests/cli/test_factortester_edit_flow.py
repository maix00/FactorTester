from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import click
from click.testing import CliRunner
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from tools.cli.app import _backtest_errors, cli
from tools.cli.http import HttpClientError


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


def test_click_describe_and_edit_flow_uses_remote_manifests(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(
            success=True,
            application=application,
            tab_lists={"local-settings": [{"key": "risk", "label": "风险"}]},
            defaults={
                "allocation_mode": {
                    "value": "equal_risk",
                    "label": "分配方式",
                    "control_template": "select",
                    "tab_key": "risk",
                    "order": 1,
                    "options": [
                        {"value": "equal_risk", "label": "等风险"},
                        {"value": "equal_notional", "label": "等市值"},
                    ],
                }
            },
        )

    @app.get("/api/backtest/settings/<application>/tabs/<tab_key>")
    def tab(application: str, tab_key: str):
        return jsonify(
            success=True,
            application=application,
            tab={"key": tab_key, "label": "风险"},
            settings=[
                {
                    "key": "allocation_mode",
                    "label": "分配方式",
                    "control_template": "select",
                    "default": "equal_risk",
                    "tab": tab_key,
                    "options": [
                        {"value": "equal_risk", "label": "等风险"},
                        {"value": "equal_notional", "label": "等市值"},
                    ],
                }
            ],
        )

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True}])
        if parent == "group_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test/risk", "label": "风险", "kind": "tab", "has_children": True}])
        return jsonify(success=True, modules=[{"key": "single_factor_family_test", "label": "单因子家族测试", "kind": "module", "has_children": True}])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["describe", "group_test"])
        assert result.exit_code == 0
        assert "分配方式" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: 首页" in result.output
        assert "[module] single_factor_family_test" in result.output
        assert "group_test/risk" not in result.output

        result = runner.invoke(cli, ["list", "single_factor_family_test"])
        assert result.exit_code != 0
        assert "unexpected extra argument" in result.output.lower()

        result = runner.invoke(cli, ["single_factor_family_test", "--factor-family", "SgCCS"])
        assert result.exit_code == 0
        assert "单因子家族测试" in result.output
        assert "已选择 factor_family: SgCCS" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: 单因子家族测试 · SgCCS" in result.output
        assert "[module] backtest" in result.output

        result = runner.invoke(cli, ["backtest"])
        assert result.exit_code == 0
        assert "回测" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: backtest" in result.output
        assert "[tab] backtest/risk" in result.output

        result = runner.invoke(cli, ["back"])
        assert result.exit_code == 0
        assert "单因子家族测试" in result.output

        result = runner.invoke(cli, ["edit", "group_test"], input="1\n1\n2\nq\n")
        assert result.exit_code == 0
        assert "已设置 分配方式: equal_notional" in result.output
        assert "当前显式设置" in result.output


def test_click_login_failure_is_user_friendly(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)

    @app.post("/login")
    def login():
        return jsonify(success=False, error="用户名或密码错误"), 401

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["login", "--username", "alice", "--password", "bad"])
        assert result.exit_code != 0
        assert "Error: 请求失败 (401): 用户名或密码错误" in result.output
        assert "Traceback" not in result.output
        assert "tools/cli" not in result.output


def test_click_login_success_prints_welcome(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"])
        assert result.exit_code == 0
        assert "已登录: alice" in result.output
        assert "欢迎使用 FactorTester CLI" in result.output
        assert "factortester list" in result.output


def test_single_factor_family_can_jump_directly_to_child_module(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True}])
        if parent == "group_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test/time", "label": "时间范围", "kind": "tab", "has_children": True}])
        return jsonify(success=True, modules=[{"key": "single_factor_family_test", "label": "单因子家族测试", "kind": "module", "has_children": True}])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["single_factor_family_test", "--factor-family", "SgCCS", "backtest"])
        assert result.exit_code == 0
        assert "回测" in result.output
        assert "因子家族: SgCCS" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: backtest" in result.output
        assert "[tab] backtest/time" in result.output


def test_click_non_json_html_response_is_user_friendly(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)

    @app.get("/api/testers/modules")
    def modules():
        return "<!DOCTYPE html><html><head><title>工具箱</title></head><body>login</body></html>"

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["list"])
        assert result.exit_code != 0
        assert "服务器返回了 HTML 页面而不是 JSON" in result.output
        assert "factortester login" in result.output
        assert "<!DOCTYPE html>" not in result.output
        assert "<html" not in result.output


def test_backtest_error_wrapper_preserves_server_body() -> None:
    @click.command()
    @_backtest_errors
    def failing_backtest():
        raise HttpClientError(500, "http://server/run", "Traceback (most recent call last):\n  File \"strategy.py\", line 1")

    result = CliRunner().invoke(failing_backtest)

    assert result.exit_code != 0
    assert "Traceback (most recent call last)" in result.output
    assert "strategy.py" in result.output
