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
from tools.cli.modules.keys import public_module_key
from tools.cli.modules.registry import ControllerRegistry


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


def register_home_modules(app: Flask) -> None:
    @app.get("/static/config/modules.json")
    def home_modules():
        return jsonify(success=True, modules=[
            {"id": "single_factor_test", "title": "单因子测试", "path": "/single_factor_test"},
            {"id": "backtest", "title": "回测", "path": "/single_factor_test?module=backtest"},
            {"id": "products", "title": "产品管理", "path": "/products"},
            {"id": "custom_factors", "title": "因子管理", "path": "/custom-factors/editor"},
        ])


def test_click_describe_and_edit_flow_uses_remote_manifests(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

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
        if parent == "backtest":
            return jsonify(success=True, parent=parent, modules=[{"key": "backtest/risk", "label": "风险", "kind": "tab", "application": "group_test", "has_children": True}])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

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
        assert "[module] single_factor_test" in result.output
        assert "[module] products" in result.output
        assert "[module] custom_factors" in result.output
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
    register_home_modules(app)

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
    register_home_modules(app)

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
    register_home_modules(app)

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True}])
        if parent == "group_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test/time", "label": "时间范围", "kind": "tab", "has_children": True}])
        if parent == "backtest":
            return jsonify(success=True, parent=parent, modules=[{"key": "backtest/time", "label": "时间范围", "kind": "tab", "application": "group_test", "has_children": True}])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

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


def test_backtest_can_enter_from_home_with_factor_family_and_draft_options(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "allocation_mode": {
                "value": "equal_risk",
                "label": "分配方式",
                "control_template": "select",
                "tab_key": "risk",
            },
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "product_path_selection": {
                "value": None,
                "label": "产品路径",
                "serialization": {"shared_page_field": "product_path_selection"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
            "factor": {
                "value": "",
                "label": "因子",
                "serialization": {"shared_page_field": "factor"},
            },
        }
        if application == "single_factor_page":
            return jsonify(success=True, application=application, defaults=defaults)
        if application == "group_test":
            return jsonify(success=True, application=application, tab_lists={"local-settings": []}, defaults=defaults)
        return jsonify(success=False, error="unknown application"), 404

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘", "paths": ["Product/Futures/CNFutures/日盘"]}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{
            "factor_alias": "SgCCS|N:2m|$F:1m|$Rev",
            "factor_family_alias": request.args.get("factor_family_alias"),
            "product_group": request.args.get("product_group"),
        }])

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "backtest":
            return jsonify(success=True, parent=parent, modules=[{"key": "backtest/time", "label": "时间范围", "kind": "tab", "application": "group_test", "has_children": True}])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "--factor-family", "SgCCS",
            "--config-local-settings", "allocation_mode=equal_notional",
            "--time-range", "2026-01-01", "2026-01-31",
            "--add-group",
            "--name", "A1",
            "--split-count", "5",
            "--group-index", "1",
        ])
        assert result.exit_code == 0
        assert "因子家族: SgCCS" in result.output
        assert "allocation_mode: equal_notional" in result.output
        assert "start_date: 2026-01-01" in result.output
        assert "end_date: 2026-01-31" in result.output
        assert "A1 · 分组数=5 · 分组序号=1" in result.output
        assert "产品路径=中国期货日盘" in result.output
        assert "因子=SgCCS|N:2m|$F:1m|$Rev" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: backtest" in result.output
        assert "[tab] backtest/time" in result.output


def test_single_factor_test_backtest_add_group_reuses_factor_family_context(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "product_path_selection": {
                "value": None,
                "label": "产品路径",
                "serialization": {"shared_page_field": "product_path_selection"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
            "factor": {
                "value": "",
                "label": "因子",
                "serialization": {"shared_page_field": "factor"},
            },
        }
        return jsonify(success=True, application=application, defaults=defaults)

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        assert request.args.get("factor_family_alias") == "SgCCS"
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:2m"}])

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True}])
        if parent == "group_test":
            return jsonify(success=True, parent=parent, modules=[])
        return jsonify(success=True, modules=[])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "backtest"])
        assert result.exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "add-group",
            "--name", "A1",
            "--split-count", "5",
            "--group-index", "1",
        ])
        assert result.exit_code == 0
        assert "产品路径: 中国期货日盘" in result.output
        assert "因子: SgCCS|N:2m" in result.output


def test_products_and_custom_factors_expose_library_submodules_from_home(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0

        result = runner.invoke(cli, ["products"])
        assert result.exit_code == 0
        assert "产品管理" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: products" in result.output
        assert "[module] products/product-groups: 产品组库" in result.output

        result = runner.invoke(cli, ["home"])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["custom_factors"])
        assert result.exit_code == 0
        assert "因子管理" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: custom_factors" in result.output
        assert "[module] custom_factors/factor-library: 因子库" in result.output


def test_click_non_json_html_response_is_user_friendly(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)

    @app.get("/static/config/modules.json")
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


def test_cli_registry_only_adapts_controllers_not_module_metadata() -> None:
    registry = ControllerRegistry()
    backtest_adapter = registry.adapter_for_backend("group_test")

    assert public_module_key("group_test/time") == "backtest/time"
    assert backtest_adapter is not None
    assert backtest_adapter.public_key == "backtest"
    assert not hasattr(backtest_adapter, "label")
    assert not hasattr(backtest_adapter, "order")
