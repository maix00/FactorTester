from __future__ import annotations

import json
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from scripts import worktree_flask_manager as manager


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def running_manager(state):
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


def authenticated_state(tmp_path):
    state = manager.ManagerState(tmp_path, "python")
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "user", float("inf"),
    )
    return state


def test_client_business_api_keeps_service_path_and_manager_selects_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"items":[]}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    with running_manager(state) as base_url:
        request_value = Request(
            f"{base_url}/api/profile-research?lifecycle=active&limit=200",
            headers={"Authorization": "Bearer user-token"},
        )
        with urlopen(request_value) as response:
            value = json.loads(response.read())

    assert value["port"] == 8141
    assert calls == [{
        "port": 8141,
        "path": "/api/profile-research?lifecycle=active&limit=200",
        "principal": "user@1",
    }]


def test_research_lifecycle_patch_uses_same_manager_gateway(tmp_path, monkeypatch) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"lifecycle":"archived"}',
            content_type="application/json",
            etag='"revision-8"',
        )

    monkeypatch.setattr(state.gateway, "request", request)
    body = b'{"target":"archived","expected_revision":7}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/profile-research/work-package%3Aone/lifecycle?port=8141",
            data=body,
            method="PATCH",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["lifecycle"] == "archived"
    assert response.headers["ETag"] == '"revision-8"'
    assert calls == [{
        "port": 8141,
        "path": "/api/profile-research/work-package%3Aone/lifecycle",
        "principal": "user@1",
        "method": "PATCH",
        "body": body,
        "content_type": "application/json",
    }]


def test_test_configuration_writes_use_same_manager_gateway(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"revision":2}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    body = b'{"expected_revision":1,"payload":{}}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/workspaces/workspace-one/configuration?port=8141",
            data=body,
            method="PUT",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["revision"] == 2
    assert value["port"] == 8141
    assert calls == [{
        "port": 8141,
        "path": "/api/workspaces/workspace-one/configuration",
        "principal": "user@1",
        "method": "PUT",
        "body": body,
        "content_type": "application/json",
    }]


def test_product_group_creation_uses_same_manager_gateway(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=201,
            body=b'{"success":true,"group":{"id":"group-one"}}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    body = b'{"name":"Group One","paths":["Products/Futures/CNFutures/_products/A.DCE"]}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/product-groups?port=8141",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["group"]["id"] == "group-one"
    assert calls == [{
        "port": 8141,
        "path": "/api/product-groups",
        "principal": "user@1",
        "method": "POST",
        "body": body,
        "content_type": "application/json",
    }]


def test_test_workbench_promotes_settings_into_execution_payload() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts" / "worktree_manager_web" / "tests.js"
    ).read_text(encoding="utf-8")

    assert "const settings = structuredClone(state.values);" in source
    assert source.count("...settings,") >= 2
    assert "local_settings: settings" in source


def test_job_progress_stream_is_relayed_through_manager(tmp_path, monkeypatch) -> None:
    captured = {}

    class StreamHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            captured["path"] = self.path
            captured["principal"] = self.headers.get("X-FactorTester-Principal")
            captured["capability"] = self.headers.get("X-FactorTester-Manager")
            body = b"event: progress\ndata: {\"completed\":1}\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), StreamHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    port = upstream.server_address[1]
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "service_ports", lambda: [port])
    try:
        with running_manager(state) as base_url:
            with urlopen(Request(
                f"{base_url}/api/jobs/job-one/stream?port={port}",
                headers={"Authorization": "Bearer user-token"},
            )) as response:
                body = response.read().decode("utf-8")
                routed_port = response.headers["X-FactorTester-Service-Port"]
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

    assert routed_port == str(port)
    assert "event: progress" in body
    assert captured["path"] == "/api/jobs/job-one/stream"
    assert captured["principal"] == "user@1"
    assert captured["capability"] == state.capability_token()


def test_profiles_and_workspace_are_local_manager_projections(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.client_state, "profiles",
        lambda principal: [{"profile_id": "maxa", "principal": principal}],
    )
    monkeypatch.setattr(
        state.client_state, "workspace",
        lambda principal: {"principal_ref": principal, "schema_version": 1},
    )
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/client/profiles", headers=headers,
        )) as response:
            profiles = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/client/workspace", headers=headers,
        )) as response:
            workspace = json.loads(response.read())

    assert profiles["profiles"][0]["profile_id"] == "maxa"
    assert profiles["profiles"][0]["principal"] == "user@1"
    assert workspace["workspace"]["principal_ref"] == "user@1"


def test_language_preference_is_scoped_to_the_authenticated_user(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    headers = {
        "Authorization": "Bearer user-token",
        "Content-Type": "application/json",
    }
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/client/preferences",
            data=b'{"language":"en"}',
            headers=headers,
            method="POST",
        )) as response:
            updated = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/client/preferences",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            restored = json.loads(response.read())

    assert updated["preferences"]["language"] == "en"
    assert restored["preferences"]["language"] == "en"
    assert state.user_preferences.read("other-user")["language"] == "system"


def test_web_language_precedence_keeps_explicit_and_cached_user_preferences() -> None:
    i18n = ROOT / "scripts" / "worktree_manager_web" / "i18n.js"
    program = f"""
global.window = globalThis;
const values = new Map();
global.localStorage = {{
  getItem: key => values.get(key) || null,
  setItem: (key, value) => values.set(key, value),
}};
eval(require("fs").readFileSync({json.dumps(str(i18n))}, "utf8"));
FTI18n.rememberPreference("zh-Hans");
console.log(JSON.stringify([
  FTI18n.choosePreference("zh-Hans", "en", "en"),
  FTI18n.choosePreference("", "zh-Hans", "en"),
  FTI18n.choosePreference("", "", FTI18n.storedPreference()),
]));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == ["zh-Hans", "zh-Hans", "zh-Hans"]

    shell = (ROOT / "scripts" / "worktree_manager_web" / "research.js").read_text()
    assert "FTI18n.choosePreference(" in shell
    assert "FTI18n.rememberPreference(preference)" in shell


def test_web_localization_is_projected_from_the_apple_catalog(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/api/localizations/en") as response:
            value = json.loads(response.read())

    assert value["locale"] == "en"
    assert value["strings"]["本地研究"] == "Local research"


def test_every_client_page_and_detail_route_uses_the_unified_shell(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    paths = [
        "/", "/research", "/research/report-publication",
        "/jobs", "/jobs/8141/job-one", "/factors",
        "/factors/families", "/factors/factor/factor-one",
        "/factors/family/family-one", "/factors/set/set-one",
        "/products", "/products/groups", "/products/product/SI.GFE",
        "/products/group/day", "/profiles", "/profiles/maxa",
        "/ic-test", "/backtest", "/test-templates/template-one",
        "/settings", "/settings/workspace", "/manager",
    ]
    with running_manager(state) as base_url:
        for path in paths:
            with urlopen(f"{base_url}{path}") as response:
                body = response.read().decode("utf-8")
            assert response.status == 200
            assert "<title>FTClient</title>" in body


def test_unified_shell_loads_shared_test_workbench_components(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        scripts = {}
        for name in (
            "test-settings.js", "test-factors.js", "test-templates.js", "tests.js",
        ):
            with urlopen(f"{base_url}/research-static/{name}") as response:
                scripts[name] = response.read().decode("utf-8")

    for name in scripts:
        assert f'/research-static/{name}' in shell
    assert "/api/backtest/settings/" in scripts["tests.js"]
    assert "/api/workspaces" in scripts["tests.js"]
    assert "/api/runs/preview" in scripts["tests.js"]
    assert "/api/runs" in scripts["tests.js"]
    assert "local-settings" in scripts["test-settings.js"]
    assert 'nativeList("owners")' in scripts["test-factors.js"]
    assert 'nativeList("revisions"' in scripts["test-factors.js"]
    assert 'nativeList("families"' in scripts["test-factors.js"]
    assert 'nativeRequest("instantiate"' in scripts["test-factors.js"]
    assert "restoreFrozenSelections(state)" in scripts["test-factors.js"]
    assert "factor_owner_ref" in scripts["test-factors.js"]
    assert "factor_git_commit" in scripts["test-factors.js"]
    assert "factor_family_ref" in scripts["test-factors.js"]
    assert "factor_params" in scripts["test-factors.js"]
    assert "state.manifest.defaults?.setting_template" in scripts["tests.js"]
    assert "/test-templates/" in scripts["test-templates.js"]


def test_web_shell_has_swift_style_opened_tabs_and_per_tab_test_state(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research.js") as response:
            research = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/tests.js") as response:
            tests = response.read().decode("utf-8")

    assert 'id="opened-tabs"' in shell
    assert 'id="opened-caption"' in shell
    assert "function closeTab" in research
    assert "function renderOpenedTabs" in research
    assert "forceNew: true" in research
    assert "context.tabSession" in tests
    assert "sessions.tests[kind]" in tests


def test_web_shell_uses_swift_symbol_registry_for_modules_and_references(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/icons.js") as response:
            icons = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/rich-text.js") as response:
            rich_text = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report-renderer.js") as response:
            renderer = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research.js") as response:
            research = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research.css") as response:
            styles = response.read().decode("utf-8")

    assert '/research-static/icons.js' in shell
    assert 'window.FTIcons' in icons
    assert 'chart.xyaxis.line' in icons
    assert 'person.crop.rectangle.stack' in icons
    assert 'FTIcons.reference' in rich_text
    assert 'FTIcons.section' in renderer
    assert 'renderDisplayMath' in rich_text
    assert 'asset_ref' in renderer
    assert 'section-bridge' in renderer
    assert 'captureScrollPosition' in research
    assert 'dataset.componentKind' in renderer
    assert 'overflow-x: auto; overflow-y: auto' in styles
    assert 'Generation ${value.generation}' not in research


def test_client_module_catalog_uses_top_level_ic_and_backtest_entries(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/api/modules") as response:
            value = json.loads(response.read())

    modules = {item["id"]: item for item in value["modules"]}
    assert modules["ic-test"]["title_key"] == "IC 测试"
    assert modules["backtest"]["title_key"] == "回测"
    assert modules["ic-test"]["sfSymbol"] == "chart.xyaxis.line"
    assert modules["backtest"]["sfSymbol"] == "chart.line.uptrend.xyaxis"
    assert modules["jobs"]["sfSymbol"] == "checklist"
    assert "single_factor_test" not in modules


def test_manager_client_restores_all_native_service_controls(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/manager.js") as response:
            script = response.read().decode("utf-8")

    for expected in (
        "/start", "/stop", "/restart-api", "/restart-bundle",
        "/force-stop", "/vibe/start", "/vibe/stop",
        "本机打开", "局域网打开",
    ):
        assert expected in script


def test_web_job_detail_keeps_typed_artifact_and_live_progress_features(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/jobs.js") as response:
            jobs = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/job-artifact-viewers.js"
        ) as response:
            viewers = response.read().decode("utf-8")

    assert "/stream" in jobs
    assert 'method: "DELETE"' in jobs
    assert "showDirectoryPicker" in jobs
    assert "/artifacts/archive" not in jobs
    assert "FTJobArtifactViewers.mount" in jobs
    assert "priceChart" in viewers
    assert "dataTable" in viewers
    assert "artifact-image" in viewers


def test_web_factor_library_reads_product_group_owned_subject_relations(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/factors.js") as response:
            script = response.read().decode("utf-8")

    assert "group.factor_refs" in script
    assert "group.factor_set_refs" in script
    assert "value.product_group_refs" not in script
    assert "/custom-factors/api/client/factor-sets" in script
    assert "/api/entities/factor-sets" not in script
    assert "factorTesterLocalFactorSets" in script
    assert "mergeFactorSets" in script
    assert 'visibility: "local"' in script
    assert 'context.t("因子家族")' in script
    assert 'context.t("因子")' in script


def test_web_research_exposes_only_download_and_shared_reports(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(
            f"{base_url}/research-static/research-workspaces.js"
        ) as response:
            workspaces = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research.js") as response:
            shell = response.read().decode("utf-8")

    assert "下载 FTClient" in workspaces
    assert "/api/public-research" in workspaces
    assert "workPackage" not in workspaces
    assert "research-graphs" not in shell
    assert 'parts[1] === "work"' not in shell


def test_product_library_is_split_and_search_only(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/products.js") as response:
            script = response.read().decode("utf-8")

    assert '["products", context.t("产品"), "/products"]' in script
    assert '["groups", context.t("产品组"), "/products/groups"]' in script
    assert 'if (!query)' in script
    assert 'context.t("输入关键词开始检索")' in script


def test_job_port_metadata_includes_automatic_selection(tmp_path, monkeypatch) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "service_ports", lambda: [8141, 8152])
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    with running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/jobs/ports",
            headers={"Authorization": "Bearer user-token"},
        )
        with urlopen(request) as response:
            value = json.loads(response.read())

    assert value == {"ports": [8141, 8152], "automatic_port": 8141}
