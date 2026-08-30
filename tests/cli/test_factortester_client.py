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


@pytest.fixture()
def fake_server() -> Iterator[str]:
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.post("/auth/login")
    def login():
        data = request.get_json()
        if data == {"username": "alice", "password": "pw"}:
            session["username"] = "alice"
            return jsonify(success=True, username="alice")
        return jsonify(success=False, error="bad login"), 401

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

    @app.post("/api/workspaces")
    def create_workspace():
        assert session.get("username") == "alice"
        return jsonify(success=True, workspace={
            "workspace_id": "workspace-1", "configuration": {"revision": 1},
        }), 201

    @app.get("/api/workspaces")
    def list_workspaces():
        assert session.get("username") == "alice"
        return jsonify(success=True, workspaces=[{"workspace_id": "workspace-1", "revision": 1}])

    @app.post("/api/runs")
    def submit_run():
        payload = request.get_json()
        assert payload["workspace_id"] == "workspace-1"
        assert payload["configuration_revision"] == 1
        assert payload["trial_binding"] == {
            "instance_id": "instance-1",
            "branch_id": "branch-1",
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

    @app.get("/api/profile-research")
    def profile_research():
        assert session.get("username") == "alice"
        assert request.args["workspace_ref"] == "workspace:workspace-1"
        assert request.args["limit"] == "7"
        assert request.args["after"] == "research-cursor"
        return jsonify(
            success=True,
            schema_version=1,
            workspace_ref="workspace:workspace-1",
            items=[{
                "research_ref": "graph-branch:instance-1:branch-1",
                "current_node": "statistical_robustness",
            }],
            next_cursor="next-research-cursor",
            etag="sha256:list",
        )

    @app.get("/api/profile-research/<research_ref>")
    def profile_research_detail(research_ref: str):
        assert session.get("username") == "alice"
        assert research_ref == "graph-branch:instance-1:branch-1"
        return jsonify(
            success=True,
            schema_version=1,
            research_ref=research_ref,
            timeline_href=f"/api/profile-research/{research_ref}/timeline",
            refresh={"mode": "conditional_etag", "terminal": False},
            etag="sha256:detail",
        )

    @app.get("/api/profile-research/<research_ref>/timeline")
    def profile_research_timeline(research_ref: str):
        assert session.get("username") == "alice"
        assert research_ref == "graph-branch:instance-1:branch-1"
        assert request.args["limit"] == "11"
        assert request.args["after"] == "timeline-cursor"
        return jsonify(
            success=True,
            schema_version=1,
            research_ref=research_ref,
            items=[{"step_ref": "trace:trace-1"}],
            next_cursor=None,
            etag="sha256:timeline",
        )

    @app.get(
        "/api/profile-research/<work_package_ref>/branches/<branch_id>/"
        "checkpoints/<trace_id>/report-carrier"
    )
    def profile_research_report_carrier(
        work_package_ref: str,
        branch_id: str,
        trace_id: str,
    ):
        assert session.get("username") == "alice"
        assert work_package_ref == "work-package:instance-1"
        assert branch_id == "branch-1"
        assert trace_id == "trace-1"
        return jsonify(
            success=True,
            schema_version=2,
            work_package_ref=work_package_ref,
            branch_ref="graph-branch:instance-1:branch-1",
            checkpoint_ref="trace:trace-1",
        )

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
            defaults={"engine_mode": {"value": "auto", "label": "执行模式", "editor": "select", "tab_key": "engine"}},
        )

    @app.get("/api/backtest/settings/<application>/tabs/<tab_key>")
    def tab(application: str, tab_key: str):
        return jsonify(
            success=True,
            application=application,
            tab={"key": tab_key, "label": "执行引擎"},
            settings=[{"key": "engine_mode", "label": "执行模式", "editor": "select", "default": "auto", "tab": tab_key}],
        )

    @app.get("/api/catalog/product-groups")
    def product_groups():
        assert request.args.get("view") == "summary"
        return jsonify(success=True, groups=[{"id": "pg-1", "name": "中国期货日盘"}])

    @app.post("/api/data-availability")
    def data_availability():
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

    @app.get("/api/factor-library-overview")
    def factor_library():
        return jsonify(success=True, factors=[{"alias": "SgCCS|N:2m"}])

    @app.get("/api/catalog/factors")
    def factor_catalog():
        return jsonify(
            success=True,
            schema_version=2,
            family_scopes={
                "mine": {
                    "families": [{"factor_family_alias": "SgCCS"}],
                    "factors": [{"factor_alias": "SgCCS|N:2m"}],
                },
            },
        )

    @app.get("/api/catalog/factor-sets")
    def factor_sets():
        assert request.args.get("query") == "momentum"
        return jsonify(
            success=True,
            item_scopes={
                "mine": [{"target_ref": "factor-set:momentum"}],
                "subordinates": [],
            },
        )

    @app.get("/api/catalog/factor-library-sources")
    def factor_library_sources():
        return jsonify(success=True, sources=[{
            "owner_ref": "alice/team",
            "owner_alias": "Alice",
            "factor_count": 2,
        }])

    @app.get(
        "/api/catalog/factor-library-sources/<path:owner_ref>/projection"
    )
    def factor_library_source_projection(owner_ref):
        assert owner_ref == "alice/team"
        return jsonify(
            success=True,
            projection={"owner_ref": owner_ref, "factors": []},
            projection_hash="a" * 64,
        )

    @app.get("/api/catalog/factor-sources/manifest")
    def factor_source_manifest():
        assert request.args.get("include_subordinates") == "0"
        return jsonify(
            success=True, server_id="public-main", principal="alice", items=[],
        )

    @app.post("/api/catalog/research-graphs/versions")
    def publish_research_graph():
        graph = request.get_json()["graph"]
        return jsonify(success=True, graph=graph), 201

    @app.get("/api/catalog/research-graphs/<graph_id>/versions")
    def research_graph_versions(graph_id):
        return jsonify(success=True, versions=[{
            "graph_id": graph_id, "version": 1,
        }])

    @app.get("/api/catalog/research-graphs/<graph_id>/active")
    def active_research_graph(graph_id):
        return jsonify(success=True, graph={
            "graph_id": graph_id, "version": 1,
        })

    @app.get(
        "/api/catalog/research-graphs/<graph_id>/versions/<int:version>/yaml"
    )
    def research_graph_yaml(graph_id, version):
        assert request.args.get("locale") == "en"
        return Response(
            f"graph_id: {graph_id}\nversion: {version}\n",
            content_type="application/yaml",
        )

    @app.post(
        "/api/catalog/research-graphs/<graph_id>/versions/"
        "<int:version>/activate"
    )
    def activate_research_graph(graph_id, version):
        return jsonify(success=True, graph={
            "graph_id": graph_id, "version": version,
        }), 201

    @app.post("/api/catalog/factor-sets")
    def register_factor_set():
        descriptor = request.get_json()["descriptor"]
        return jsonify(success=True, factor_set={
            "target_ref": descriptor["target_ref"],
        })

    @app.delete("/api/catalog/factor-sets")
    def unregister_factor_set():
        return jsonify(
            success=request.args.get("target_ref") == "factor-set:momentum",
        )

    @app.get("/api/catalog/products")
    def product_catalog():
        return jsonify(
            success=True,
            products=[{"name": "RB.SHF", "description": "螺纹钢"}],
        )

    @app.get("/api/catalog/sources")
    def product_sources():
        return jsonify(
            success=True,
            sources=[{"source_id": "LocalCNFutures", "frequency": "MIN1"}],
        )

    @app.get("/api/research-publications/settings")
    def research_publications():
        assert session.get("username") == "alice"
        return jsonify(success=True, reports=[{"title": "我的研究"}])

    @app.get("/api/public-research")
    def public_research():
        assert request.args.get("scope") == "subordinates"
        return jsonify(success=True, reports=[{"title": "下级研究"}])

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

    assert client.login("alice", "pw")["username"] == "alice"
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
    assert client.factor_source_sync_manifest(
        include_subordinates=False,
    )["server_id"] == "public-main"
    graph = {"graph_id": "factor-research", "version": 1}
    assert client.publish_research_graph(graph)["graph_id"] == "factor-research"
    assert client.list_research_graph_versions("factor-research")[0][
        "version"
    ] == 1
    assert client.get_active_research_graph("factor-research")[
        "graph_id"
    ] == "factor-research"
    assert b"graph_id: factor-research" in client.download_research_graph_yaml(
        "factor-research", 1, locale="en",
    )
    assert client.activate_research_graph("factor-research", 1)[
        "version"
    ] == 1
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
        trial_binding={
            "instance_id": "instance-1",
            "branch_id": "branch-1",
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
    artifact = client.job_artifact("job-1", "equity_curve_report")
    assert artifact.content == b"<svg><title>curve</title></svg>"
    assert artifact.content_type == "image/svg+xml"
    assert client.job_order_audit("job-1")["strategies"]["A1"]["groups"][0][
        "order_group_id"
    ] == "G1"
    research = client.list_profile_research(
        workspace_ref="workspace:workspace-1",
        limit=7,
        after="research-cursor",
    )
    assert research["items"][0]["research_ref"] == (
        "graph-branch:instance-1:branch-1"
    )
    research_ref = research["items"][0]["research_ref"]
    assert client.get_profile_research(research_ref)["refresh"]["mode"] == (
        "conditional_etag"
    )
    assert client.list_profile_research_timeline(
        research_ref,
        limit=11,
        after="timeline-cursor",
    )["items"] == [{"step_ref": "trace:trace-1"}]
    assert client.get_profile_research_report_carrier(
        "work-package:instance-1",
        "branch-1",
        "trace-1",
    )["checkpoint_ref"] == "trace:trace-1"
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


def test_client_login_persists_across_processes_and_logout_clears_cookie(
    fake_server: str, tmp_path,
) -> None:
    cookie_file = tmp_path / "cookies.lwp"
    first = FactorTesterClient(HttpSession(fake_server, cookies=cookie_file))
    first.login("alice", "pw")

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
    client.login("alice", "pw")

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
    client.login("alice", "pw")

    assert client.manifest("group_test")["application"] == "group_test"
    assert client.tab_manifest("group_test", "engine")["tab"]["key"] == "engine"
    assert client.product_group_catalog()["groups"][0]["id"] == "pg-1"
    with pytest.raises(ValueError, match="暂不支持候选列表类型"):
        client.list_candidates("product_path_selection")
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
