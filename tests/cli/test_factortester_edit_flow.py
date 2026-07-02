from __future__ import annotations

import threading
import contextlib
import io
from collections.abc import Iterator
from contextlib import contextmanager

import click
from click.testing import CliRunner
from flask import Flask, Response, jsonify, request
from werkzeug.serving import make_server

from tools.cli.app import _backtest_errors, cli
from tools.cli.http import HttpClientError
import tools.cli.modules.backtest.run_output as run_output
from tools.cli.modules.keys import public_module_key
from tools.cli.modules.backtest.run_output import BacktestRunRenderer
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
            return jsonify(success=True, parent=parent, modules=[
                {"key": "single_factor_page", "label": "因子家族测试设置", "kind": "module", "has_children": True},
                {"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True},
            ])
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

        result = runner.invoke(cli, ["single_factor_test", "list"])
        assert result.exit_code == 0
        assert "当前位置: single_factor_test" in result.output
        assert "[module] backtest" in result.output

        result = runner.invoke(cli, ["backtest"])
        assert result.exit_code == 0
        assert "回测" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: 首页" in result.output
        assert "[module] single_factor_test" in result.output

        result = runner.invoke(cli, ["back"])
        assert result.exit_code != 0
        assert "No such command" in result.output

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

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-1")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"])
        assert result.exit_code == 0
        assert "已登录: alice" in result.output
        assert "页面上下文: page-1" in result.output
        assert "欢迎使用 FactorTester CLI" in result.output
        assert "factortester list" in result.output


def test_single_factor_family_can_jump_directly_to_child_module(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[
                {"key": "single_factor_page", "label": "因子家族测试设置", "kind": "module", "has_children": True},
                {"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True},
            ])
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
        assert "--factor-family SgCCS" in result.output

        result = runner.invoke(cli, ["single_factor_test", "list"])
        assert result.exit_code == 0
        assert "当前位置: single_factor_test" in result.output
        assert "[module] backtest" in result.output


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

        result = runner.invoke(cli, ["backtest"])
        assert result.exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "local-settings",
            "allocation_mode=equal_notional",
            "--start-date", "2026-01-01",
            "--end-date", "2026-01-31",
        ])
        assert result.exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
        ])
        assert result.exit_code == 0
        assert "名称: A1" in result.output
        assert "分组数: 5" in result.output
        assert "分组序号: 1" in result.output

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "A1 · 分组数=5 · 分组序号=1" in result.output
        assert "产品路径=中国期货日盘" in result.output
        assert "因子=SgCCS|N:2m|$F:1m|$Rev" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: 首页" in result.output
        assert "[module] single_factor_test" in result.output


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
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
        ])
        assert result.exit_code == 0
        assert "产品路径: 中国期货日盘" in result.output
        assert "因子: SgCCS|N:2m" in result.output


def test_backtest_add_group_supports_inline_factor_and_product_paths(tmp_path, monkeypatch) -> None:
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
        return jsonify(success=True, factors=[])

    @app.get("/api/factor-library-configs/<factor_family>")
    def factor_library_configs(factor_family: str):
        assert factor_family == "SgCCS"
        assert request.args.get("product_group") == "现场路径"
        return jsonify(success=True, users=[{"editable": True, "config": {"params_list": []}}])

    @app.put("/api/factor-library-configs/<factor_family>")
    def save_factor_library_configs(factor_family: str):
        payload = request.get_json()
        assert payload["params_list"] == [{"N": "2m", "$Rev": "1"}]
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:2m|$Rev:1"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
            "--product-group", "add",
            "--name", "现场路径",
            "--path", "Product/Futures/CNFutures/日盘",
            "--path", "-Product/Futures/CNFutures/日盘/_products/BB.DCE",
            "--factor", "add",
            "--param", "N=2m",
            "--param", "$Rev=1",
        ])

        assert result.exit_code == 0
        assert "名称: A1" in result.output
        assert "分组数: 5" in result.output
        assert "分组序号: 1" in result.output
        assert "产品路径: 现场路径" in result.output
        assert "因子: SgCCS|N:2m|$Rev:1" in result.output


def test_backtest_add_group_can_import_local_factor_family_path(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)
    source_path = tmp_path / "LocalAlpha.py"
    source_path.write_text(
        "from tools.factors import FactorFamily\n\nclass LocalAlpha(FactorFamily):\n    pass\n",
        encoding="utf-8",
    )

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.post("/custom-factors/api/create")
    def create_custom_factor():
        payload = request.get_json() or {}
        assert "class LocalAlpha" in payload["source_code"]
        return jsonify(success=True, factor={"id": "LocalAlpha", "name": "LocalAlpha"})

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family",
            "--path",
            str(source_path),
            "--group-name",
            "LocalA1",
            "--split-count",
            "5",
            "--group-index",
            "1",
            "--product-group",
            "from-candidates",
            "--name",
            "中国期货日盘",
        ])

        assert result.exit_code != 0
        assert "新增分组缺少 factor" in result.output

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family",
            "--path",
            str(source_path),
            "--factor",
            "--alias",
            "LocalAlpha|N:2m",
            "--group-name",
            "LocalA1",
            "--split-count",
            "5",
            "--group-index",
            "1",
            "--product-group",
            "from-candidates",
            "--name",
            "中国期货日盘",
        ])

        assert result.exit_code == 0
        assert "名称: LocalA1" in result.output
        assert "因子: LocalAlpha|N:2m" in result.output

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "因子=LocalAlpha|N:2m" in result.output


def test_backtest_add_group_uses_backend_registered_candidate_field_commands(tmp_path, monkeypatch) -> None:
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
        return jsonify(success=True, groups=[])

    @app.get("/api/factor-library-configs/<factor_family>")
    def factor_library_configs(factor_family: str):
        return jsonify(success=True, users=[{"editable": True, "config": {"params_list": []}}])

    @app.put("/api/factor-library-configs/<factor_family>")
    def save_factor_library_configs(factor_family: str):
        payload = request.get_json()
        assert payload["product_group"] == "现场路径"
        assert payload["params_list"] == [{"N": "2m"}]
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:2m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--product-path-candidates", "add",
            "--name", "现场路径",
            "--path", "Product/Futures/CNFutures/日盘",
            "--factor-candidates", "add",
            "--param", "N=2m",
        ])

        assert result.exit_code == 0
        assert "产品路径: 现场路径" in result.output
        assert "因子: SgCCS|N:2m" in result.output


def test_backtest_add_group_selects_factor_and_product_group_from_candidates(tmp_path, monkeypatch) -> None:
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
        return jsonify(success=True, groups=[
            {"id": "pg-day", "name": "中国期货日盘"},
            {"id": "pg-night", "name": "中国期货夜盘"},
        ])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        assert request.args.get("factor_family_alias") == "SgCCS"
        assert request.args.get("product_group") == "中国期货夜盘"
        return jsonify(success=True, factors=[
            {"factor_alias": "SgCCS|N:1m"},
            {"factor_alias": "SgCCS|N:2m"},
        ])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A5",
            "--split-count", "5",
            "--group-index", "5",
            "--product-group", "from-candidates",
            "--name", "中国期货夜盘",
            "--factor", "from-candidates",
            "--product-group", "中国期货夜盘",
            "--index", "2",
        ])

        assert result.exit_code == 0
        assert "名称: A5" in result.output
        assert "分组数: 5" in result.output
        assert "分组序号: 5" in result.output
        assert "产品路径: 中国期货夜盘" in result.output
        assert "因子: SgCCS|N:2m" in result.output


def test_backtest_add_group_accepts_multiple_group_sections(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
            "--factor", "--alias", "SgCCS|N:1m",
            "--product-group", "--from-candidates", "--name", "中国期货日盘",
            "--add",
            "--group-name", "A5",
            "--split-count", "5",
            "--group-index", "5",
            "--factor", "--alias", "SgCCS|N:2m",
            "--product-group", "--from-candidates", "--name", "中国期货日盘",
        ])

        assert result.exit_code == 0
        assert "新增分组: 2" in result.output
        assert "名称: A1" in result.output
        assert "因子: SgCCS|N:1m" in result.output
        assert "名称: A5" in result.output
        assert "因子: SgCCS|N:2m" in result.output


def test_backtest_config_local_settings_is_sibling_action(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "allocation_mode": {
                "value": "equal_risk",
                "label": "分配方式",
                "tab_key": "allocation",
                "control_template": "select",
                "options": [{"value": "equal_risk"}, {"value": "equal_notional"}],
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "local-settings", "--allocation-mode", "equal_notional"])

        assert result.exit_code == 0
        assert "已更新 local-settings" in result.output
        assert "allocation_mode: equal_notional" in result.output


def test_backtest_add_group_context_help_prints_registered_visible_and_editable_fields(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "engine": {
                "value": "Native",
                "label": "执行引擎",
                "tab_key": "engine",
                "tab_label": "执行引擎",
                "control_template": "select",
                "options": [{"value": "Native", "label": "Native"}, {"value": "Backtrader", "label": "Backtrader"}],
                "order": 1,
            },
            "engine_mode": {
                "value": "basic",
                "label": "引擎模式",
                "tab_key": "engine",
                "tab_label": "执行引擎",
                "order": 2,
            },
            "warmup_mode": {
                "value": "auto",
                "label": "前摇模式",
                "tab_key": "factor_execution",
                "tab_label": "因子执行",
                "visible_when": {"engine_mode": ["auto"]},
                "editable_when": {"engine_mode": ["auto"]},
                "order": 1,
            },
            "readonly_probe": {
                "value": "locked",
                "label": "只读字段",
                "tab_key": "engine",
                "tab_label": "执行引擎",
                "editible_when": {"engine_mode": ["never"]},
                "order": 3,
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        }
        return jsonify(success=True, application=application, defaults=defaults)

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
            "--product-group", "from-candidates",
            "--name", "中国期货日盘",
            "--factor", "--alias", "SgCCS|N:1m",
            "--engine", "Native",
            "--engine-mode", "auto",
            "--help",
        ])

        assert result.exit_code == 0
        assert "回测设置上下文" in result.output
        assert "执行引擎" in result.output
        assert "字段" in result.output
        assert "名称" in result.output
        assert "状态" in result.output
        assert "--engine" in result.output
        assert "执行引擎" in result.output
        assert "可编辑" in result.output
        assert "Literal[Native, Backtrader]" in result.output
        assert "--engine-mode" in result.output
        assert "引擎模式" in result.output
        assert "因子执行" in result.output
        assert "--warmup-mode" in result.output
        assert "前摇模式" in result.output
        assert "--readonly-probe" in result.output
        assert "只读字段" in result.output
        assert "不可编辑" in result.output


def test_backtest_add_group_field_help_distinguishes_missing_value_from_context(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "split_count": {
                "value": 5,
                "label": "分组数",
                "tab_key": "group_strategy",
                "tab_label": "分组策略",
                "control_template": "number",
            },
            "engine": {
                "value": "Native",
                "label": "执行引擎",
                "tab_key": "engine",
                "tab_label": "执行引擎",
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["group", "--add", "--split-count", "--help"])
        assert result.exit_code == 0
        assert "--split-count 字段说明" in result.output
        assert "后端字段: split_count" in result.output
        assert "类型: number" in result.output
        assert "回测设置上下文" not in result.output

        result = runner.invoke(cli, ["group", "--add", "--split-count", "5", "--help"])
        assert result.exit_code == 0
        assert "回测设置上下文" in result.output
        assert "--split-count" in result.output
        assert "分组数" in result.output
        assert "执行引擎" in result.output


def test_cli_help_pages_explain_navigation_and_backtest_construction() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "FactorTester CLI" in result.output
    assert "factortester single_factor_test" in result.output
    assert "--factor-family SgCCS" in result.output
    assert "字段级帮助示例" in result.output

    result = runner.invoke(cli, ["single_factor_test", "--help"])
    assert result.exit_code == 0
    assert "进入单因子测试控制界面" in result.output
    assert "factortester single_factor_test" in result.output
    assert "backtest" in result.output

    result = runner.invoke(cli, ["backtest", "--help"])
    assert result.exit_code == 0
    assert "进入通用回测控制界面" in result.output
    assert "factortester backtest group" in result.output


def test_backtest_add_ls_can_reference_existing_groups_and_inline_group(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0
        assert runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
        ]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "long-short",
            "--add",
            "--name", "LS A1/A5",
            "--long-group", "A1",
            "--short-group",
            "--add",
            "--group-name", "A5",
            "--split-count", "5",
            "--group-index", "5",
            "--factor", "--alias", "SgCCS|N:2m",
            "--product-group", "from-candidates",
            "--name", "中国期货日盘",
        ])

        assert result.exit_code == 0
        assert "新增 Long-Short" in result.output
        assert "名称: LS A1/A5" in result.output
        assert "多头: A1" in result.output
        assert "空头: A5" in result.output


def test_backtest_group_actions_batch_edit_describe_list_and_run_use_login_page_uuid(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test-secret"
    register_home_modules(app)
    received_payloads: list[dict] = []

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-login-1")

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "allocation_mode": {
                "value": "equal_risk",
                "label": "分配方式",
                "tab_key": "allocation",
                "control_template": "select",
                "options": [{"value": "equal_risk"}, {"value": "equal_notional"}],
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    @app.post("/run_group_test_stream")
    def run_group_test_stream():
        received_payloads.append(request.get_json())
        body = "\n".join([
            "event: activity",
            'data: {"label": "准备运行"}',
            "",
            "event: complete",
            "data: {}",
            "",
        ])
        return Response(body, mimetype="text/event-stream")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        result = runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"])
        assert result.exit_code == 0
        assert "页面上下文: page-login-1" in result.output
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--batch",
            "--group-names", "A1", "A2",
            "--split-count", "2",
            "--product-group", "from-candidates",
            "--name", "中国期货日盘",
            "--factor", "--alias", "SgCCS|N:1m",
        ])
        assert result.exit_code == 0
        assert "新增分组: 2" in result.output
        assert "分组序号: 1" in result.output
        assert "分组序号: 2" in result.output

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "1. A1 · 分组数=2 · 分组序号=1" in result.output
        assert "2. A2 · 分组数=2 · 分组序号=2" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--group-name", "A1", "--derive", "--group-name", "A1a"])
        assert result.exit_code == 0
        assert "新增派生分组: 1" in result.output
        assert "名称: A1a" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--group-name", "A2", "--copy", "--group-name", "A2-copy"])
        assert result.exit_code == 0
        assert "新增复制分组: 1" in result.output
        assert "名称: A2-copy" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--group-name", "A1", "--describe"])
        assert result.exit_code == 0
        assert "名称: A1" in result.output

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--group-names", "A1", "A2",
            "--edit",
            "--allocation-mode", "equal_notional",
        ])
        assert result.exit_code == 0
        assert "已修改分组: 2" in result.output

        result = runner.invoke(cli, ["backtest", "long-short", "--add", "--ls-name", "LS A1/A2", "--long-group", "A1", "--short-group", "A2"])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["backtest", "long-short", "list"])
        assert result.exit_code == 0
        assert "LS A1/A2" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--group-names", "A1", "A2", "--run"])
        assert result.exit_code == 0
        assert "开始运行回测: groups=2, long-short=1" in result.output
        assert "策略信息:" in result.output
        assert "A1 · 分组数=2 · 分组序号=1" in result.output
        assert "产品路径=中国期货日盘" in result.output
        assert "当前: 准备运行" in result.output
        assert "回测完成" in result.output

    assert len(received_payloads) == 1
    payload = received_payloads[0]
    assert payload["page_uuid"] == "page-login-1"
    assert [group["name"] for group in payload["groups"]] == ["A1", "A2"]
    assert {group["factor_family_alias"] for group in payload["groups"]} == {"SgCCS"}
    assert all(group["allocation_mode"] == "equal_notional" for group in payload["groups"])
    assert payload["ls_configs"][0]["name"] == "LS A1/A2"


def test_backtest_run_renders_manifest_progress_and_verbose_events(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test-secret"
    register_home_modules(app)

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-login-1")

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
            "equity_compute_live": {"value": True},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    @app.post("/run_group_test_stream")
    def run_group_test_stream():
        body = "\n".join([
            "event: activity_manifest",
            'data: {"phases":[{"key":"pre_replay","label":"准备","flows":[{"flow_key":"market_data","flow_label":"加载行情","display_order":1}]},{"key":"event_replay","label":"事件回放","flows":[{"flow_key":"signal.target","flow_label":"合成目标","display_order":1,"event_kind":"SIGNAL"},{"flow_key":"notice.roll","flow_label":"换月通知","display_order":2,"event_kind":"ORDER_NOTICE"},{"flow_key":"order.fill","flow_label":"成交记账","display_order":3,"event_kind":"ORDER"}]},{"key":"post_replay","label":"整理","flows":[{"flow_key":"risk","flow_label":"计算风险指标","display_order":1}]}]}',
            "",
            "event: activity",
            'data: {"phase":"pre_replay","phase_label":"准备","flow_key":"market_data","flow_label":"加载行情","timestamp":"2026-01-02 09:00:00"}',
            "",
            "event: signal_progress",
            'data: {"completed":1,"total":4,"phase":"event_replay"}',
            "",
            "event: activity",
            'data: {"phase":"event_replay","phase_label":"事件回放","flow_key":"signal.target","flow_label":"合成目标","timestamp":"2026-01-02 09:01:00"}',
            "",
            "event: runtime_info",
            'data: {"type":"产品路径","status":"已移除","detail":"ER.CZC(早籼稻)"}',
            "",
            "event: activity",
            'data: {"phase":"post_replay","phase_label":"整理","flow_key":"risk","flow_label":"计算风险指标","timestamp":"2026-01-31 15:00:00"}',
            "",
            "event: result",
            'data: {"success":true,"product_path_selection_id":"pg-day","groups":[{"id":"g-a1","name":"A1","total_equity":[100000000,100200000,100100000,100500000],"timestamps":[1000,2000,3000,4000]},{"id":"ls-a1-a5","name":"LS A1/A5","is_ls":true,"total_equity":[100000000,99900000,100300000],"timestamps":[1000,2000,3000]}]}',
            "",
            "event: complete",
            "data: {}",
            "",
        ])
        return Response(body, mimetype="text/event-stream")

    @app.post("/get_group_snapshot")
    def group_snapshot():
        payload = request.get_json() or {}
        return jsonify(
            success=True,
            timestamp_ms=payload.get("timestamp_ms"),
            event_label="成交后账本",
            summary={"total_changed": 2, "total_prod_count": 5, "avg_turnover": 40.0},
            matrices=[{"label": "实际持仓 · 合约", "columns": [{"label": "A1"}], "rows": [{"name": "现金"}]}],
        )

    @app.post("/get_group_order_flow")
    def group_order_flow():
        payload = request.get_json() or {}
        return jsonify(
            success=True,
            record_count=2,
            groups=[{"group_id": payload.get("group_id") or "g-a1", "group_name": "A1", "records": [{"order_id": "o1"}, {"order_id": "o2"}]}],
        )

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0
        assert runner.invoke(cli, [
            "backtest", "group", "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--product-group", "from-candidates", "--name", "中国期货日盘",
            "--factor", "--alias", "SgCCS|N:1m",
        ]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "--run", "--verbose"])

    assert result.exit_code == 0
    assert "流程图:" not in result.output
    assert "总进度:" in result.output
    assert "准备: [################] 100.0%" in result.output
    assert "事件回放: [####------------]  25.0%" in result.output
    assert "整理: [################] 100.0%" in result.output
    assert "1/4" not in result.output
    assert "当前: 准备 · 2026-01-02 09:00:00 1/1 加载行情" in result.output
    assert "当前: 事件回放 · 2026-01-02 09:01:00 合成目标" in result.output
    assert "当前: 整理 · 2026-01-31 15:00:00 1/1 计算风险指标" in result.output
    assert "[activity] phase=event_replay flow=signal.target" in result.output
    assert "[progress] phase=event_replay" not in result.output
    assert "[运行信息] 产品路径: ER.CZC(早籼稻)" in result.output
    assert "[live] 刷新净值曲线" in result.output
    assert "净值曲线:" in result.output
    assert result.output.index("净值曲线:") < result.output.index("结果摘要:")
    assert "A1" in result.output
    assert "LS A1/A5 LS" in result.output
    assert "结果摘要:" in result.output
    summary_output = result.output.split("结果摘要:", 1)[1]
    summary_lines = [line for line in summary_output.splitlines() if "100500000.00" in line or "100300000.00" in line]
    assert len(summary_lines) == 2
    assert len({line.index("100") for line in summary_lines}) == 1
    assert "A1" in summary_lines[0]
    assert "100500000.00" in summary_lines[0]
    assert "0.50%" in summary_lines[0]
    assert "LS A1/A5 · LS" in summary_lines[1]
    assert "100300000.00" in summary_lines[1]
    assert "0.30%" in summary_lines[1]
    assert "回测完成" in result.output
    assert "结果查看:" in result.output
    assert "factortester backtest results summary" in result.output

    result = runner.invoke(cli, ["backtest", "results", "summary"])
    assert result.exit_code == 0
    assert "最近一次回测摘要" in result.output
    assert "最终权益" in result.output
    assert "A1" in result.output

    result = runner.invoke(cli, ["backtest", "results", "equity"])
    assert result.exit_code == 0
    assert "净值曲线:" in result.output

    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0
        result = runner.invoke(cli, ["backtest", "results", "snapshot", "--index", "2"])
        assert result.exit_code == 0
        assert "快照: timestamp_ms=2000" in result.output
        assert "成交后账本" in result.output

        result = runner.invoke(cli, ["backtest", "results", "order-flow", "--group-name", "A1"])
        assert result.exit_code == 0
        assert "订单流: records=2" in result.output
        assert "A1" in result.output


def test_backtest_tty_status_keeps_pre_and_post_current_flow() -> None:
    class TtyBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    renderer = BacktestRunRenderer(verbose=False)
    manifest = {
        "phases": [
            {"key": "pre_replay", "label": "回放准备", "flows": [
                {"flow_key": "pre.window", "flow_label": "解析运行时间窗口", "display_order": 1},
            ]},
            {"key": "event_replay", "label": "事件回放", "flows": [
                {"flow_key": "signal.target", "flow_label": "合成目标", "display_order": 1, "event_kind": "SIGNAL"},
            ]},
            {"key": "post_replay", "label": "结果整理", "flows": [
                {"flow_key": "post.risk", "flow_label": "计算风险指标", "display_order": 1},
            ]},
        ],
    }
    stream = TtyBuffer()
    with contextlib.redirect_stdout(stream):
        renderer.handle("activity_manifest", manifest)
        renderer.handle("activity", {
            "phase": "pre_replay",
            "phase_label": "回放准备",
            "flow_key": "pre.window",
            "flow_label": "解析运行时间窗口",
        })
        renderer.handle("progress", {"phase": "pre_replay", "percent": 5})
        renderer.handle("activity", {
            "phase": "post_replay",
            "phase_label": "结果整理",
            "flow_key": "post.risk",
            "flow_label": "计算风险指标",
        })
        renderer.handle("progress", {"phase": "post_replay", "percent": 95})

    raw = stream.getvalue()
    assert "当前: 回放准备 · 1/1 解析运行时间窗口" in raw
    assert "当前: 结果整理 · 1/1 计算风险指标" in raw
    assert "\n\n\n" not in raw


def test_backtest_verbose_event_activity_is_throttled(monkeypatch) -> None:
    timestamps = iter([0.0, 0.5, 2.2])
    monkeypatch.setattr(run_output.time, "monotonic", lambda: next(timestamps))
    renderer = BacktestRunRenderer(verbose=True)
    stream = io.StringIO()

    with contextlib.redirect_stdout(stream):
        for minute in ("09:01:00", "09:02:00", "09:03:00"):
            renderer.handle("activity", {
                "phase": "event_replay",
                "phase_label": "事件回放",
                "flow_key": "signal.target",
                "flow_label": "合成目标",
                "timestamp": f"2026-01-02 {minute}",
            })

    raw = stream.getvalue()
    assert raw.count("当前: 事件回放") == 2
    assert raw.count("[activity] phase=event_replay") == 2
    assert "2026-01-02 09:01:00" in raw
    assert "2026-01-02 09:02:00" not in raw
    assert "2026-01-02 09:03:00" in raw


def test_backtest_tty_event_activity_is_throttled_by_wall_clock(monkeypatch) -> None:
    class TtyBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    timestamps = iter([0.0, 0.5, 2.2])
    monkeypatch.setattr(run_output.time, "monotonic", lambda: next(timestamps))
    renderer = BacktestRunRenderer(verbose=False)
    stream = TtyBuffer()

    with contextlib.redirect_stdout(stream):
        for minute in ("09:01:00", "09:02:00", "09:03:00"):
            renderer.handle("activity", {
                "phase": "event_replay",
                "phase_label": "事件回放",
                "flow_key": "signal.target",
                "flow_label": "合成目标",
                "timestamp": f"2026-01-02 {minute}",
            })

    raw = stream.getvalue()
    assert "2026-01-02 09:01:00" in raw
    assert "2026-01-02 09:02:00" not in raw
    assert "2026-01-02 09:03:00" in raw


def test_backtest_group_add_help_and_batch_help_use_action_specific_text(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "group", "--add", "--help"])
        assert result.exit_code == 0
        assert "group --add 动作说明" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--add", "--batch", "--help"])
        assert result.exit_code == 0
        assert "group --add --batch 字段说明" in result.output


def test_single_factor_template_load_restores_backtest_state_and_clear_resets_draft(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    snapshot = {
        "factors": {
            "factor_candidates": [{"alias": "SgCCS|N:2m", "params": {"N": "2m"}}],
            "factor": "SgCCS|N:2m",
        },
        "local_settings": {"allocation_mode": "equal_notional"},
        "group_settings": {
            "groups": [{
                "id": "g1",
                "name": "A1",
                "splitCount": 5,
                "groupIndex": 1,
                "factorAlias": "SgCCS|N:2m",
                "product_path_selection": {"product_path_selection_id": "pg-day", "product_group": "中国期货日盘"},
            }],
            "lsConfigs": [{
                "id": "ls1",
                "name": "LS A1/A5",
                "longGroupId": "g1",
                "shortGroupId": "g5",
            }],
        },
    }

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[
                {"key": "single_factor_page", "label": "因子家族测试设置", "kind": "module", "has_children": True},
                {"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True},
            ])
        if parent == "group_test":
            return jsonify(success=True, parent=parent, modules=[])
        return jsonify(success=True, modules=[{"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True}])

    @app.get("/api/single_factor_setting_templates/<factor_family>")
    def templates(factor_family: str):
        assert factor_family == "SgCCS"
        return jsonify(success=True, templates=[{"id": "tpl-20260602", "name": "2026-06-02 07:20:47"}])

    @app.get("/api/single_factor_setting_templates/<factor_family>/<template_id>")
    def template_detail(factor_family: str, template_id: str):
        assert factor_family == "SgCCS"
        assert template_id == "tpl-20260602"
        return jsonify(success=True, template={"id": template_id, "name": "2026-06-02 07:20:47", "snapshot": snapshot})

    saved_templates: list[dict[str, object]] = []

    @app.post("/api/single_factor_setting_templates/<factor_family>")
    def save_template(factor_family: str):
        assert factor_family == "SgCCS"
        payload = request.get_json() or {}
        saved_templates.append(payload)
        return jsonify(success=True, id="tpl-cli")

    registered_factors: list[dict[str, object]] = []

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-template-1")

    @app.post("/add_factor_by_params")
    def add_factor_by_params():
        payload = request.get_json() or {}
        registered_factors.append(payload)
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        return jsonify(success=True, factor_alias=f"SgCCS|N:{params.get('N')}")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "template", "list"])
        assert result.exit_code == 0
        assert "2026-06-02 07:20:47 · id=tpl-20260602" in result.output

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "template", "help"])
        assert result.exit_code == 0
        assert "template 命令" in result.output
        assert "save [模板名]" in result.output

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "template", "load", "2026-06-02 07:20:47"])
        assert result.exit_code == 0
        assert "已加载模板: 2026-06-02 07:20:47" in result.output
        assert "groups: 1" in result.output
        assert "已注册因子: 1" in result.output
        assert registered_factors == [{
            "factor_family_alias": "SgCCS",
            "params": {"N": "2m"},
            "page_uuid": "page-template-1",
        }]

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "（空）" in result.output

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "backtest"])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["group", "list"])
        assert result.exit_code == 0
        assert "A1 · 分组数=5 · 分组序号=1" in result.output
        assert "产品路径=中国期货日盘" in result.output
        assert "因子=SgCCS|N:2m" in result.output

        result = runner.invoke(cli, ["long-short", "list"])
        assert result.exit_code == 0
        assert "LS A1/A5" in result.output
        assert "多头=g1" in result.output

        result = runner.invoke(cli, ["backtest", "template", "--from-module-template", "single_factor_test", "load", "2026-06-02 07:20:47"])
        assert result.exit_code == 0
        assert "来自 single_factor_test 模板" in result.output

        result = runner.invoke(cli, ["backtest", "template", "save", "CLI 草稿"])
        assert result.exit_code == 0
        assert "已保存模板: CLI 草稿" in result.output
        assert saved_templates[-1]["name"] == "CLI 草稿"
        assert saved_templates[-1]["ff_alias"] == "SgCCS"
        assert (saved_templates[-1]["snapshot"])["group_settings"]["groups"][0]["name"] == "A1"

        result = runner.invoke(cli, ["backtest", "template", "help"])
        assert result.exit_code == 0
        assert "backtest template 命令" in result.output
        assert "load <模板ID或名称>" in result.output

        result = runner.invoke(cli, ["backtest"])
        assert result.exit_code == 0
        assert "allocation_mode: equal_notional" in result.output

        result = runner.invoke(cli, ["backtest", "clear"])
        assert result.exit_code == 0
        assert "已清空 backtest 配置" in result.output

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "（空）" in result.output


def test_ic_test_cli_adds_config_and_runs_stream(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)
    app.secret_key = "test-secret"
    received_payloads: list[dict[str, object]] = []

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-ic-1")

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[
                {"key": "ic_test", "label": "IC 测试", "kind": "module", "has_children": True},
            ])
        if parent == "ic_test":
            return jsonify(success=True, parent=parent, modules=[])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
            {"key": "ic_test", "label": "IC 测试", "kind": "module", "application": "ic_test", "has_children": True},
        ])

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        base_defaults = {
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "control_template": "custom",
                "tab_key": "product_path_selection",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "control_template": "custom",
                "tab_key": "factor",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
        }
        if application == "single_factor_page":
            return jsonify(success=True, application=application, defaults=base_defaults)
        if application == "ic_test":
            defaults = {
                **base_defaults,
                "product_path_selections": {
                    "value": [],
                    "label": "产品路径选择",
                    "control_template": "custom",
                    "tab_key": "product_path_selection",
                },
                "factor_selections": {
                    "value": [],
                    "label": "因子选择",
                    "control_template": "custom",
                    "tab_key": "factor",
                },
                "ic_correlation": {
                    "value": "rank",
                    "label": "默认 IC",
                    "control_template": "select",
                    "tab_key": "ic_method",
                    "options": [
                        {"value": "rank", "label": "Rank IC"},
                        {"value": "pearson", "label": "Pearson IC"},
                        {"value": "both", "label": "Rank + Pearson"},
                    ],
                },
                "ic_lag": {
                    "value": 0,
                    "label": "IC Lag",
                    "control_template": "number",
                    "tab_key": "delay",
                },
                "ic_decay_lags": {
                    "value": 5,
                    "label": "IC 衰减阶数",
                    "control_template": "number",
                    "tab_key": "delay",
                },
                "group_adjust": {
                    "value": "off",
                    "label": "组内去均值",
                    "control_template": "select",
                    "tab_key": "cross_section",
                    "options": [{"value": "off"}, {"value": "on"}],
                },
                "by_group": {
                    "value": "off",
                    "label": "分组 IC",
                    "control_template": "select",
                    "tab_key": "cross_section",
                    "options": [{"value": "off"}, {"value": "on"}],
                },
                "rolling_window": {
                    "value": 20,
                    "label": "滚动窗口",
                    "control_template": "number",
                    "tab_key": "summary",
                },
            }
            return jsonify(success=True, application=application, defaults=defaults)
        return jsonify(success=False, error="unknown application"), 404

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘", "paths": ["Product/Futures/CNFutures/日盘"]}])

    @app.post("/run_ic_test_stream")
    def run_ic_test_stream():
        payload = request.get_json() or {}
        received_payloads.append(payload)

        def stream():
            yield 'event: start\ndata: {"total": 2, "groups": 1, "phase": "init"}\n\n'
            yield 'event: progress\ndata: {"completed": 1, "total": 2, "phase": "eval"}\n\n'
            yield (
                'event: result\ndata: '
                '{"success": true, "ic_stats": {"columns": ["index", "SgCCS|N:2m"], '
                '"rows": [{"index": "mean", "SgCCS|N:2m": 0.123456}, '
                '{"index": "ir", "SgCCS|N:2m": 1.5}]}, '
                '"factors": [{"alias": "SgCCS|N:2m", "ic_series": {"dates": [1,2,3], "values": [0.1, 0.2, -0.1]}, '
                '"rolling_ic": {"window": 3, "mean": [0.066], "ir": [0.4]}, '
                '"ic_decay": [{"lag": 1, "mean": 0.1, "ir": 0.5, "n": 3}, {"lag": 2, "mean": 0.2, "ir": 0.6, "n": 3}]}]}\n\n'
            )

        return Response(stream(), mimetype="text/event-stream")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "ic_test"])
        assert result.exit_code == 0
        assert "IC 测试" in result.output

        result = runner.invoke(cli, ["ic_test", "local-settings", "--help"])
        assert result.exit_code == 0
        assert "IC 设置上下文" in result.output
        assert "--ic-correlation" in result.output

        result = runner.invoke(cli, [
            "ic_test",
            "local-settings",
            "--ic-correlation", "both",
            "--ic-lag", "1",
            "--ic-decay-lags", "3",
            "--rolling-window", "3",
            "--group-adjust", "on",
            "--by-group", "on",
        ])
        assert result.exit_code == 0
        assert "已更新 IC local-settings" in result.output

        result = runner.invoke(cli, [
            "ic_test",
            "config",
            "--add",
            "--name",
            "日盘IC",
            "--factor-family",
            "SgCCS",
            "--product-group",
            "中国期货日盘",
            "--factor",
            "--alias",
            "SgCCS|N:2m",
        ])
        assert result.exit_code == 0
        assert "新增 IC 配置" in result.output
        assert "产品路径=中国期货日盘" in result.output

        result = runner.invoke(cli, ["ic_test", "--run", "--verbose"])
        assert result.exit_code == 0
        assert "开始运行 IC 测试: configs=1" in result.output
        assert "进度: eval 1/2" in result.output
        assert "IC 结果摘要" in result.output
        assert "指标" in result.output
        assert "因子" in result.output
        assert "mean" in result.output
        assert "SgCCS|N:2m" in result.output
        assert "0.123456" in result.output
        assert "IC 序列图" in result.output
        assert "Rolling IC" in result.output
        assert "IC 衰减" in result.output
        assert received_payloads
        assert received_payloads[-1]["page_uuid"] == "page-ic-1"
        assert received_payloads[-1]["factor_family_alias"] == "SgCCS"
        assert received_payloads[-1]["product_path_selection_id"] == "pg-day"
        assert received_payloads[-1]["factors"] == [{"alias": "SgCCS|N:2m"}]
        assert (received_payloads[-1]["settings"])["ic_correlation"] == "both"
        assert (received_payloads[-1]["settings"])["group_adjust"] == "on"
        assert (received_payloads[-1]["settings"])["by_group"] == "on"
        assert received_payloads[-1]["ic_correlation"] == "both"
        assert received_payloads[-1]["ic_lag"] == "1"
        assert received_payloads[-1]["ic_decay_lags"] == [1, 2, 3]
        assert received_payloads[-1]["rolling_window"] == "3"

        result = runner.invoke(cli, [
            "ic_test",
            "local-settings",
            "--ic-correlation", "pearson",
            "--ic-lag", "0",
            "--ic-decay-lags", "1",
            "--rolling-window", "2",
            "--group-adjust", "off",
            "--by-group", "off",
        ])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["ic_test", "--run"])
        assert result.exit_code == 0
        assert received_payloads[-1]["ic_correlation"] == "pearson"
        assert received_payloads[-1]["ic_lag"] == "0"
        assert received_payloads[-1]["ic_decay_lags"] == [1]
        assert received_payloads[-1]["rolling_window"] == "2"
        assert (received_payloads[-1]["settings"])["group_adjust"] == "off"
        assert (received_payloads[-1]["settings"])["by_group"] == "off"


def test_factor_evaluation_and_type_analysis_cli_run(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)
    app.secret_key = "test-secret"
    received: dict[str, dict[str, object]] = {}

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-analysis-1")

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[
                {"key": "factor_evaluation", "label": "因子评估", "kind": "module", "has_children": True},
                {"key": "factor_type_analysis", "label": "因子类型分析", "kind": "module", "has_children": True},
            ])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
        ])

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "control_template": "custom",
                "tab_key": "product",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "control_template": "custom",
                "tab_key": "factor",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
            "start_date": {"value": "", "label": "开始日期", "control_template": "date", "tab_key": "time"},
            "end_date": {"value": "", "label": "结束日期", "control_template": "date", "tab_key": "time"},
        }
        if application == "factor_type_analysis":
            defaults["correlation_method"] = {
                "value": "pearson",
                "label": "相关性方法",
                "control_template": "select",
                "tab_key": "method",
                "options": [
                    {"value": "pearson", "label": "Pearson"},
                    {"value": "spearman", "label": "Spearman"},
                ],
            }
        if application in {"single_factor_page", "factor_evaluation", "factor_type_analysis"}:
            return jsonify(success=True, application=application, defaults=defaults)
        return jsonify(success=False, error="unknown application"), 404

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{
            "id": "pg-day",
            "name": "中国期货日盘",
            "paths": ["Product/Futures/CNFutures/日盘/_products/AP.CZC"],
        }])

    @app.post("/api/factor_evaluation/evaluate")
    def factor_evaluation_endpoint():
        payload = request.get_json() or {}
        received["factor_evaluation"] = payload
        return jsonify(success=True, factor={"alias": payload.get("factor_alias")}, meta={"product_count": 1, "elapsed_ms": 12}, series=[
            {"product": "AP.CZC", "desc": "苹果", "dates": [1, 2], "values": [0.1, 0.2]},
        ])

    @app.post("/api/factor_type_analysis/analyze")
    def factor_type_endpoint():
        payload = request.get_json() or {}
        received["factor_type_analysis"] = payload
        return jsonify(success=True, best_match={"category_label": "趋势", "correlation": 0.81}, reference_factors=[
            {"key": "trend", "name": "趋势参照", "correlation": 0.81},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0

        result = runner.invoke(cli, [
            "factor_evaluation",
            "run",
            "--factor-family",
            "SgCCS",
            "--product-group",
            "中国期货日盘",
            "--factor",
            "--alias",
            "SgCCS|N:2m",
        ])
        assert result.exit_code == 0
        assert "开始因子评估" in result.output
        assert "产品" in result.output
        assert "描述" in result.output
        assert "点数" in result.output
        assert "AP.CZC" in result.output
        assert "苹果" in result.output
        assert received["factor_evaluation"]["page_uuid"] == "page-analysis-1"
        assert received["factor_evaluation"]["paths"] == ["Product/Futures/CNFutures/日盘/_products/AP.CZC"]

        result = runner.invoke(cli, ["factor_type_analysis", "local-settings", "--correlation-method", "spearman"])
        assert result.exit_code == 0

        result = runner.invoke(cli, [
            "factor_type_analysis",
            "run",
            "--factor-family",
            "SgCCS",
            "--product-group",
            "中国期货日盘",
            "--factor",
            "--alias",
            "SgCCS|N:2m",
        ])
        assert result.exit_code == 0
        assert "开始因子类型分析" in result.output
        assert "最佳类型" in result.output
        assert "类型" in result.output
        assert "相关性" in result.output
        assert "趋势" in result.output
        assert received["factor_type_analysis"]["settings"]["correlation_method"] == "spearman"


def test_custom_factor_workspace_cli_maps_web_workspace_actions(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)
    calls: list[tuple[str, dict]] = []

    @app.get("/custom-factors/api/source-root")
    def source_root():
        return jsonify(success=True, source_root="", resolved_root="/tmp/factor-workspace")

    @app.post("/custom-factors/api/source-root")
    def save_source_root():
        payload = request.get_json() or {}
        calls.append(("save-root", payload))
        return jsonify(success=True, source_root=payload.get("source_root"), resolved_root=payload.get("source_root"))

    @app.post("/custom-factors/api/workspace/build")
    def build_workspace():
        calls.append(("build", request.get_json() or {}))
        return jsonify(success=True, workspace_root="/tmp/factor-workspace", custom_factor_count=2, public_factor_count=1)

    @app.post("/custom-factors/api/workspace/sync")
    def sync_workspace():
        payload = request.get_json() or {}
        calls.append(("sync", payload))
        return jsonify(success=True, workspace_root="/tmp/factor-workspace", git_selected_branch=payload.get("branch_mode"), touched_files=["custom_factors/A.py"])

    @app.post("/custom-factors/api/workspace/push")
    def push_workspace():
        payload = request.get_json() or {}
        calls.append(("push", payload))
        return jsonify(success=True, workspace_root="/tmp/factor-workspace", git_selected_branch=payload.get("branch_mode"), updated_custom_count=1)

    @app.get("/custom-factors/api/workspace/git-settings")
    def git_settings():
        return jsonify(success=True, git_enabled=True, git_repo_root="/tmp/factor-workspace", git_current_branch="factor-upload", git_branches=["factor-upload"])

    @app.post("/custom-factors/api/workspace/git-settings")
    def save_git_settings():
        payload = request.get_json() or {}
        calls.append(("git-settings", payload))
        return jsonify(success=True, git_enabled=payload.get("git_enabled"), git_repo_root=payload.get("git_repo_root"), git_current_branch="factor-upload")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0

        result = runner.invoke(cli, ["custom_factors"])
        assert result.exit_code == 0
        assert "workspace show|root|build|sync|push" in result.output

        result = runner.invoke(cli, ["custom_factors", "list"])
        assert result.exit_code == 0
        assert "custom_factors/factor-library" in result.output
        assert "custom_factors/workspace" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "show"])
        assert result.exit_code == 0
        assert "实际目录: /tmp/factor-workspace" in result.output
        assert "当前分支: factor-upload" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "root", "/tmp/custom-root"])
        assert result.exit_code == 0
        assert "实际目录: /tmp/custom-root" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "build"])
        assert result.exit_code == 0
        assert "建立完成" in result.output
        assert "自定义因子: 2" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "sync", "--branch-mode", "force"])
        assert result.exit_code == 0
        assert "下载同步完成" in result.output
        assert "写入文件" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "push", "--branch-mode", "auto"])
        assert result.exit_code == 0
        assert "上传入库完成" in result.output
        assert "更新自定义因子: 1" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "git-settings", "--disable", "--repo-root", "/tmp/no-git"])
        assert result.exit_code == 0
        assert "启用: 否" in result.output

    assert calls == [
        ("save-root", {"source_root": "/tmp/custom-root"}),
        ("build", {}),
        ("sync", {"branch_mode": "force"}),
        ("push", {"branch_mode": "auto"}),
        ("git-settings", {"git_enabled": False, "git_repo_root": "/tmp/no-git"}),
    ]


def test_backtest_context_help_errors_on_unregistered_field(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "engine": {"value": "Native", "label": "执行引擎", "tab_key": "engine"},
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "local-settings", "--not-registered", "x", "--help"])

        assert result.exit_code != 0
        assert "local-settings 包含未注册字段: not_registered" in result.output


def test_backtest_context_help_errors_on_invalid_registered_value(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "engine": {
                "value": "Native",
                "label": "执行引擎",
                "tab_key": "engine",
                "control_template": "select",
                "options": [{"value": "Native", "label": "Native"}],
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "local-settings", "--engine", "Bad", "--help"])

        assert result.exit_code != 0
        assert "字段 engine 的值不合法" in result.output


def test_backtest_inline_product_path_rejects_duplicate_candidate_name(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:2m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0
        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--group-name", "A1",
            "--product-group", "add",
            "--name", "中国期货日盘",
            "--path", "Product/Futures/CNFutures/日盘",
        ])

        assert result.exit_code != 0
        assert "产品路径候选名称已存在: 中国期货日盘" in result.output


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

        result = runner.invoke(cli, ["products", "list"])
        assert result.exit_code == 0
        assert "当前位置: products" in result.output
        assert "[module] products/product-groups: 产品组库" in result.output

        result = runner.invoke(cli, ["custom_factors"])
        assert result.exit_code == 0
        assert "因子管理" in result.output

        result = runner.invoke(cli, ["custom_factors", "list"])
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
