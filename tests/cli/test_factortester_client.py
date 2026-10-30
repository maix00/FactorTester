from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from flask import Flask, Response, jsonify, request, session
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


def _authenticate_test_client(client: FactorTesterClient) -> None:
    """Establish a test-only cookie; production CLI has no password endpoint."""
    value = client.session.post("/test/keycloak-session", {})
    assert value["username"] == "alice"


@pytest.fixture()
def fake_server() -> Iterator[str]:
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.post("/test/keycloak-session")
    def establish_test_keycloak_session():
        session["username"] = "alice"
        return jsonify(success=True, username="alice")

    @app.post("/api/client/profiles/sync")
    def sync_profile():
        assert session.get("username") == "alice"
        payload = request.get_json()
        assert payload["profile"]["profile_id"] == "maxa"
        return jsonify(
            success=True,
            status="synced",
            synced=True,
            pending=False,
            profile={"profile_id": "maxa"},
        )

    @app.post("/auth/logout")
    def logout():
        session.clear()
        return jsonify(success=True)

    @app.post("/api/test-authoring/workspaces")
    def create_workspace():
        assert session.get("username") == "alice"
        return jsonify(success=True, workspace={
            "workspace_id": "workspace-1", "configuration": {"revision": 1},
        }), 201

    @app.get("/api/test-authoring/workspaces")
    def list_workspaces():
        assert session.get("username") == "alice"
        return jsonify(success=True, workspaces=[{"workspace_id": "workspace-1", "revision": 1}])

    @app.post("/api/runs")
    def submit_run():
        assert request.args.get("port") in {None, "8141"}
        payload = request.get_json()
        assert payload["workspace_id"] == "workspace-1"
        assert payload["configuration_revision"] == 1
        assert "trial_binding" not in payload
        assert payload["sample_use"] == {
            "schema_version": 1,
            "purpose": "validation",
            "protection": "open",
        }
        assert payload["run_input_dependencies"] == [{
            "path": "run-configs/options.json",
            "content": "{}\n",
            "purpose": "run_configuration",
            "analyses": ["ic"],
        }]
        return jsonify(success=True, run_id="run-1", jobs=[{"job_id": "job-1", "kind": "ic"}]), 202

    @app.post("/api/runs/preview")
    def preview_run():
        assert request.args.get("port") in {None, "8141"}
        payload = request.get_json()
        assert payload == {
            "workspace_id": "workspace-1",
            "configuration_revision": 1,
            "analyses": ["ic"],
            "retention_mode": "summary",
            "step_mode": False,
            "run_input_dependencies": [{
                "path": "run-configs/options.json",
                "content": "{}\n",
                "purpose": "run_configuration",
                "analyses": ["ic"],
            }],
        }
        return jsonify(
            success=True,
            run_spec_hash="a" * 64,
            run_spec_version=1,
            configuration_id="configuration-1",
            configuration_revision=1,
            configuration_fingerprint="b" * 64,
            analyses=["ic"],
            retention_mode="summary",
            step_mode=False,
        )

    @app.post("/api/external-factor-artifacts/validate")
    def validate_external_factor_artifact():
        payload = request.get_json()
        return jsonify(success=True, artifact={
            "artifact_id": "academic_mom:abc",
            "manifest_path": payload["manifest_path"],
            "factor_sha256": "abc",
            "execution": "next_bar",
        })

    @app.get("/api/jobs")
    def list_jobs():
        assert request.args.get("port") in {"all", "8141"}
        return jsonify(success=True, jobs=[{"job_id": "job-1", "status": "queued"}])

    artifact_values = {
        "equity_curve_report": (
            b"<svg><title>curve</title></svg>", "image/svg+xml",
        ),
        "order_audit": (
            (
                b'{"run_id":"run-1","strategies":{"A1":{"groups":['
                b'{"order_group_id":"G1"}]}}}'
            ),
            "application/json",
        ),
    }

    @app.post("/api/jobs/job-1/artifacts/<name>/access")
    def job_artifact_access(name: str):
        assert session.get("username") == "alice"
        raw, content_type = artifact_values[name]
        return jsonify(
            success=True,
            artifact={
                "name": name,
                "content_type": content_type,
                "content_hash": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            },
            access={
                "url": request.host_url.rstrip("/") + f"/data/{name}",
                "bearer": f"capability-{name}",
                "expected_size": len(raw),
            },
        )

    @app.get("/data/<name>")
    def job_artifact_data(name: str):
        assert not request.cookies
        assert request.headers["Authorization"] == f"Bearer capability-{name}"
        raw, content_type = artifact_values[name]
        return Response(
            raw,
            content_type=content_type,
        )

    @app.get("/api/admin/server-instances")
    def admin_server_instances():
        return jsonify(success=True, instances=[{
            "instance_id": "worktree-opaque",
            "kind": "factortester",
            "port": 8141,
            "running": True,
        }])

    @app.post("/api/admin/server-instances/<instance_id>/actions")
    def admin_server_action(instance_id: str):
        return jsonify(
            success=True,
            instance_id=instance_id,
            action=request.get_json()["action"],
        )

    @app.get("/api/admin/jobs")
    def admin_jobs():
        assert request.args["limit"] == "9"
        assert request.args["cursor"] == "cursor-1"
        return jsonify(
            success=True,
            jobs=[{"job_id": "global-job-1", "owner": "bob"}],
            has_more=False,
            next_cursor=None,
        )

    @app.get("/api/test-authoring/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_page":
            return jsonify(success=True, parent=parent, modules=[{"key": "single_factor_page/setting_template", "label": "模板", "kind": "tab"}])
        return jsonify(success=True, modules=[{"key": "single_factor_page", "label": "因子家族测试设置", "kind": "module", "has_children": True}])

    @app.get("/static/config/modules.json")
    def home_modules():
        return jsonify(success=True, modules=[{"id": "single_factor_test", "title": "单因子测试"}])

    @app.get("/api/test-authoring/modules/<application>")
    def settings(application: str):
        return jsonify(
            success=True,
            application=application,
            tab_lists={"local-settings": [{"key": "engine", "label": "执行引擎"}]},
            defaults={"engine_mode": {"value": "auto", "label": "执行模式", "editor": "select", "tab_key": "engine"}},
        )

    @app.get("/api/test-authoring/modules/<application>/tabs/<tab_key>")
    def tab(application: str, tab_key: str):
        return jsonify(
            success=True,
            application=application,
            tab={"key": tab_key, "label": "执行引擎"},
            settings=[{"key": "engine_mode", "label": "执行模式", "editor": "select", "default": "auto", "tab": tab_key}],
        )

    @app.get("/api/product-library/product-groups")
    def product_groups():
        assert request.args.get("view") == "summary"
        return jsonify(success=True, groups=[{"id": "pg-1", "name": "中国期货日盘"}])

    @app.get("/api/jobs/ports")
    def job_ports():
        return jsonify(success=True, ports=[8141, 8152], automatic_port=8141)

    @app.post("/api/data-availability")
    def data_availability():
        assert request.args.get("port") == "8141"
        payload = request.get_json()
        assert payload == {
            "products": ["A.DCE"],
            "sources": ["Local"],
            "frequencies": [],
            "probe": False,
            "expanded": False,
            "fields": [],
            "include_field_catalog": False,
            "include_historical_fields": False,
        }
        return jsonify(
            success=True,
            schema_version=1,
            profile_hash="sha256:availability",
            product_scope=["A.DCE"],
            entries=[],
        )

    @app.post("/api/product-liquidity")
    def product_liquidity():
        assert request.args.get("port") == "8141"
        payload = request.get_json()
        assert payload == {
            "products": ["A.DCE", "RB.SHF"],
            "source": "LocalCNFuturesDAY1",
            "as_of": "2024-12-31",
            "window_days": 365,
        }
        return jsonify(
            success=True,
            schema_version=1,
            evidence_kind="product_liquidity",
            evidence_hash="sha256:liquidity",
            entries=[],
        )

    @app.get("/api/data-capabilities")
    def data_capabilities():
        assert request.args.get("port") == "8141"
        return jsonify(success=True, catalog={"schema_version": 1})

    @app.get("/api/data-availability/profiles/<path:profile_ref>")
    def data_availability_profile(profile_ref):
        assert request.args.get("port") == "8141"
        assert profile_ref == "availability:v1:sample"
        return jsonify(success=True, profile_ref=profile_ref)

    @app.get("/api/factor-library/overview")
    def factor_library():
        return jsonify(success=True, factors=[{"alias": "SgCCS|N:2m"}])

    @app.get("/api/factor-library/families")
    def factor_families():
        return jsonify(
            success=True,
            schema_version=2,
            family_scopes={
                "mine": {
                    "families": [{"factor_family_alias": "SgCCS"}],
                },
            },
        )

    @app.get("/api/factor-library/factors")
    def factors():
        return jsonify(
            success=True,
            family_scopes={
                "mine": {"factors": [{"factor_alias": "SgCCS|N:2m"}]},
            },
        )

    @app.get("/api/factor-library/factor-sets")
    def factor_sets():
        assert request.args.get("query") == "momentum"
        return jsonify(
            success=True,
            item_scopes={
                "mine": [{"target_ref": "factor-set:momentum"}],
                "subordinates": [],
            },
        )

    @app.get("/api/factor-library/owners")
    def factor_library_sources():
        return jsonify(success=True, sources=[{
            "owner_ref": "alice/team",
            "owner_alias": "Alice",
            "factor_count": 2,
        }])

    @app.get(
        "/api/factor-library/owners/<path:owner_ref>/projection"
    )
    def factor_library_source_projection(owner_ref):
        assert owner_ref == "alice/team"
        return jsonify(
            success=True,
            projection={"owner_ref": owner_ref, "factors": []},
            projection_hash="a" * 64,
        )

    @app.post("/api/factor-library/factor-sets")
    def register_factor_set():
        descriptor = request.get_json()["descriptor"]
        return jsonify(success=True, factor_set={
            "target_ref": descriptor["target_ref"],
        })

    @app.delete("/api/factor-library/factor-sets")
    def unregister_factor_set():
        return jsonify(
            success=request.args.get("target_ref") == "factor-set:momentum",
        )

    @app.get("/api/product-library/products")
    def product_catalog():
        return jsonify(
            success=True,
            products=[{"name": "RB.SHF", "description": "螺纹钢"}],
        )

    @app.get("/api/product-library/data-sources")
    def product_sources():
        return jsonify(
            success=True,
            sources=[{"source_id": "LocalCNFutures", "frequency": "MIN1"}],
        )

    @app.get("/api/research/reports")
    def research_reports():
        assert session.get("username") == "alice"
        value = {
            "mine": {"title": "我的研究"},
            "subordinates": {"title": "下级研究"},
        }.get(request.args.get("scope"), {"title": "全部研究"})
        return jsonify(success=True, reports=[value], scope=request.args.get("scope"))

    @app.get("/api/client/profile-directory")
    def profile_directory():
        assert session.get("username") == "alice"
        assert request.args.get("scope") == "mine"
        assert request.args.get("page_size") == "20"
        return jsonify(success=True, items=[{"profile_id": "maxa"}], total=1)

    @app.get("/api/client/agent-models")
    def agent_models():
        assert session.get("username") == "alice"
        assert request.args.get("runtime_kind") == "server"
        return jsonify(
            success=True,
            providers=[{"provider_id": "codex", "runtime_kind": "server"}],
        )

    with running_server(app) as url:
        yield url


def test_client_uses_real_http_and_cookies(fake_server: str, tmp_path) -> None:
    client = FactorTesterClient(HttpSession(fake_server, cookies=tmp_path / "cookies.lwp"))

    _authenticate_test_client(client)
    assert client.sync_profile({
        "profile_id": "maxa",
        "display_name": "Max A",
    })["synced"] is True
    workspace = client.create_workspace(factor_families=[{"alias": "MmRet"}])
    assert workspace["workspace_id"] == "workspace-1"
    assert client.list_workspaces()[0]["workspace_id"] == "workspace-1"
    assert client.product_liquidity(
        products=["A.DCE", "RB.SHF"],
        source="LocalCNFuturesDAY1",
        as_of="2024-12-31",
    )["evidence_hash"] == "sha256:liquidity"
    assert client.data_capabilities()["schema_version"] == 1
    assert client.data_availability_profile("availability:v1:sample")[
        "profile_ref"
    ] == "availability:v1:sample"
    assert client.factor_catalog()["family_scopes"]["mine"]["families"][0][
        "factor_family_alias"
    ] == "SgCCS"
    assert client.factor_set_catalog(query="momentum")["item_scopes"]["mine"][0][
        "target_ref"
    ] == "factor-set:momentum"
    assert client.list_registered_factor_sets(query="momentum")[
        "item_scopes"
    ]["mine"][0]["target_ref"] == "factor-set:momentum"
    assert client.factor_library_sources()["sources"][0][
        "owner_ref"
    ] == "alice/team"
    assert client.factor_library_source_projection("alice/team")[
        "projection_hash"
    ] == "a" * 64
    assert client.register_factor_set({
        "target_ref": "factor-set:momentum",
    })["factor_set"]["target_ref"] == "factor-set:momentum"
    assert client.unregister_factor_set("factor-set:momentum")["success"] is True
    assert client.product_catalog()["products"][0]["name"] == "RB.SHF"
    assert client.product_source_catalog()["sources"][0]["source_id"] == (
        "LocalCNFutures"
    )
    assert client.research_report_catalog(scope="mine")["reports"][0][
        "title"
    ] == "我的研究"
    assert client.research_report_catalog(scope="subordinates")["reports"][0][
        "title"
    ] == "下级研究"
    assert client.profile_directory(scope="mine")["items"][0]["profile_id"] == (
        "maxa"
    )
    assert client.list_agent_models(runtime_kind="server")[0]["provider_id"] == (
        "codex"
    )
    assert client.submit_run(
        "workspace-1",
        1,
        analyses=["ic"],
        sample_use={
            "schema_version": 1,
            "purpose": "validation",
            "protection": "open",
        },
        run_input_dependencies=[{
            "path": "run-configs/options.json",
            "content": "{}\n",
            "purpose": "run_configuration",
            "analyses": ["ic"],
        }],
    )["run_id"] == "run-1"
    assert client.preview_run(
        "workspace-1",
        1,
        analyses=["ic"],
        run_input_dependencies=[{
            "path": "run-configs/options.json",
            "content": "{}\n",
            "purpose": "run_configuration",
            "analyses": ["ic"],
        }],
    )["run_spec_hash"] == "a" * 64
    assert client.validate_external_factor_artifact(
        "/research/gtht_handoff.json"
    )["artifact_id"] == "academic_mom:abc"
    assert client.list_jobs(workspace_id="workspace-1")[0]["job_id"] == "job-1"
    assert client.list_jobs(port=8141, all_ports=False)[0]["job_id"] == "job-1"
    artifact = client.job_artifact("job-1", "equity_curve_report")
    assert artifact.content == b"<svg><title>curve</title></svg>"
    assert artifact.content_type == "image/svg+xml"
    assert client.job_order_audit("job-1")["strategies"]["A1"]["groups"][0][
        "order_group_id"
    ] == "G1"
    assert client.list_modules()[0]["key"] == "single_factor_test"
    assert client.list_modules(parent="single_factor_page")[0]["kind"] == "tab"
    assert client.data_availability(
        products=["A.DCE"],
        sources=["Local"],
    )["profile_hash"] == "sha256:availability"
    assert client.list_server_instances()["instances"][0]["port"] == 8141
    assert client.run_server_instance_action(
        "worktree-opaque",
        "restart",
    )["action"] == "restart"
    assert client.list_global_jobs(
        limit=9,
        cursor="cursor-1",
    )["jobs"][0]["job_id"] == "global-job-1"


def test_data_services_require_a_manager_declared_automatic_port() -> None:
    class PortsOnlySession:
        def __init__(self):
            self.calls = []

        def get(self, path, *, query=None):
            self.calls.append((path, query))
            return {
                "success": True,
                "ports": [8141],
                "automatic_port": None,
            }

    client = FactorTesterClient(PortsOnlySession())
    with pytest.raises(RuntimeError, match="自动业务服务"):
        client.product_liquidity(
            products=["A.DCE"],
            source="LocalCNFuturesDAY1",
            as_of="2024-12-31",
        )
    assert client.session.calls == [("/api/jobs/ports", None)]


def test_run_routes_select_service_without_changing_http_origin() -> None:
    class RecordingSession:
        def __init__(self):
            self.calls = []

        def request(self, method, path, *, payload=None, query=None):
            self.calls.append((method, path, query))
            return {"success": True}

    client = FactorTesterClient(RecordingSession())
    client.submit_run("workspace-1", 1, analyses=["backtest"], service_port=8141)
    client.preview_run("workspace-1", 1, analyses=["backtest"], service_port=8141)

    assert client.session.calls == [
        ("POST", "/api/runs", {"port": 8141}),
        ("POST", "/api/runs/preview", {"port": 8141}),
    ]


def test_keycloak_session_persists_across_processes_and_logout_clears_cookie(
    fake_server: str, tmp_path,
) -> None:
    cookie_file = tmp_path / "cookies.lwp"
    first = FactorTesterClient(HttpSession(fake_server, cookies=cookie_file))
    _authenticate_test_client(first)

    second = FactorTesterClient(HttpSession(fake_server, cookies=cookie_file))
    assert second.list_workspaces()[0]["workspace_id"] == "workspace-1"

    assert second.logout()["success"] is True
    assert list(second.session.cookie_jar) == []
    third = FactorTesterClient(HttpSession(fake_server, cookies=cookie_file))
    assert list(third.session.cookie_jar) == []


def test_binary_artifact_download_enforces_size_limit(
    fake_server: str, tmp_path,
) -> None:
    client = FactorTesterClient(
        HttpSession(fake_server, cookies=tmp_path / "cookies.lwp")
    )
    _authenticate_test_client(client)

    with pytest.raises(ValueError, match="download limit"):
        client.job_artifact(
            "job-1", "equity_curve_report", maximum_bytes=8,
        )


def test_client_discards_corrupt_cookie_jar_without_traceback(fake_server: str, tmp_path) -> None:
    cookie_file = tmp_path / "cookies.lwp"
    cookie_file.write_text("not an LWP cookie jar\n", encoding="utf-8")

    client = FactorTesterClient(HttpSession(fake_server, cookies=cookie_file))

    assert client.list_modules()[0]["key"] == "single_factor_test"
    assert cookie_file.read_text(encoding="utf-8").startswith("#LWP-Cookies-2.0")


def test_client_fetches_settings_and_candidates(fake_server: str, tmp_path) -> None:
    client = FactorTesterClient(HttpSession(fake_server, cookies=tmp_path / "cookies.lwp"))
    _authenticate_test_client(client)

    assert client.manifest("group_test")["application"] == "group_test"
    assert client.tab_manifest("group_test", "engine")["tab"]["key"] == "engine"
    assert client.product_group_catalog()["groups"][0]["id"] == "pg-1"
    with pytest.raises(ValueError, match="暂不支持候选列表类型"):
        client.list_candidates("product_path_selection")
    assert client.list_candidates("factor_candidates")[0]["alias"] == "SgCCS|N:2m"


def test_client_detects_old_module_endpoint_when_parent_is_ignored(tmp_path) -> None:
    app = Flask(__name__)

    @app.get("/api/test-authoring/modules")
    def modules():
        return jsonify(success=True, modules=[{"key": "single_factor_family_test"}])

    with running_server(app) as url:
        client = FactorTesterClient(HttpSession(url, cookies=tmp_path / "cookies.lwp"))
        with pytest.raises(RuntimeError, match="分层导航版本"):
            client.list_modules(parent="single_factor_family_test")
