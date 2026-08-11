from __future__ import annotations

import inspect
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scripts import worktree_flask_manager as manager
from scripts.worktree_manager_test_authoring import (
    TestAuthoringResponse as _TestAuthoringResponse,
)


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


def test_test_configuration_writes_are_manager_owned_without_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    calls = []

    class Authoring:
        @staticmethod
        def handles(path, method):
            return path == "/api/workspaces/workspace-one/configuration" and method == "PUT"

        @staticmethod
        def write(method, path, *, owner, payload):
            calls.append({
                "method": method, "path": path, "owner": owner,
                "payload": payload,
            })
            return _TestAuthoringResponse({
                "success": True,
                "configuration": {"revision": 2},
            })

    state.test_authoring = Authoring()
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("authoring must not use a service gateway"),
    )
    monkeypatch.setattr(
        state, "service_ports",
        lambda: pytest.fail("authoring must not inspect service ports"),
    )
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

    assert value["configuration"]["revision"] == 2
    assert calls == [{
        "method": "PUT",
        "path": "/api/workspaces/workspace-one/configuration",
        "owner": "user@1",
        "payload": {"expected_revision": 1, "payload": {}},
    }]


def test_test_settings_are_available_without_execution_service(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("settings must not use a service gateway"),
    )
    monkeypatch.setattr(
        state, "service_ports",
        lambda: pytest.fail("settings must not inspect service ports"),
    )
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/backtest/settings/ic_test?port=8141",
            headers=headers,
        )) as response:
            settings = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/jobs/artifact-capabilities?port=8141",
            headers=headers,
        )) as response:
            outputs = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/data_source_categories?port=8141",
            headers=headers,
        )) as response:
            categories = json.loads(response.read())

    assert settings["success"] is True
    assert settings["application"] == "ic_test"
    assert settings["executable_modules"]
    assert settings["run_fields"][0]["key"] == "service_port"
    assert settings["run_fields"][0]["freeze_target"] == "job.server_context.port"
    assert outputs["outputs"]
    assert isinstance(categories["categories"], list)


def test_test_workbench_first_load_is_concurrent_and_service_port_free(
    tmp_path, monkeypatch,
) -> None:
    """The Manager must survive the real Promise.all first-page load.

    These endpoints import overlapping FactorTester packages.  Running them
    on separate request threads used to expose partially initialized modules
    or Python module-lock deadlocks on the first visit only.
    """
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.gateway, "request",
        lambda **_values: pytest.fail("authoring must not use a service gateway"),
    )
    monkeypatch.setattr(
        state, "service_ports",
        lambda: pytest.fail("authoring must not inspect service ports"),
    )
    paths = (
        "/api/backtest/settings/ic_test",
        "/api/catalog/factors",
        "/api/catalog/product-groups",
        "/api/workspaces",
        "/api/configuration-templates",
        "/api/jobs/artifact-capabilities",
        "/api/data_source_categories",
    )

    with running_manager(state) as base_url:
        def fetch(path: str) -> tuple[int, dict]:
            with urlopen(Request(
                f"{base_url}{path}",
                headers={"Authorization": "Bearer user-token"},
            ), timeout=15) as response:
                return response.status, json.loads(response.read())

        with ThreadPoolExecutor(max_workers=len(paths)) as pool:
            responses = list(pool.map(fetch, paths))

    assert [status for status, _payload in responses] == [200] * len(paths)
    assert all(payload.get("success") is not False for _status, payload in responses)


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


def test_job_output_generation_uses_job_port_and_forwards_body(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"artifacts":[]}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    body = b'{"output_requests":["ic_statistics"]}'
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/jobs/job-one/artifacts/generate?port=8141",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())
        with pytest.raises(HTTPError) as rejected:
            urlopen(Request(
                f"{base_url}/api/jobs/job-one/artifacts/result?port=8141",
                data=body,
                method="POST",
                headers={
                    "Authorization": "Bearer user-token",
                    "Content-Type": "application/json",
                },
            ))

    assert value["success"] is True
    assert rejected.value.code == 404
    assert calls == [{
        "port": 8141,
        "path": "/api/jobs/job-one/artifacts/generate",
        "principal": "user@1",
        "method": "POST",
        "body": body,
        "content_type": "application/json",
    }]


@pytest.mark.parametrize(
    ("path", "body"),
    (
        ("/api/jobs/job-one/approve", b"{}"),
        ("/api/jobs/job-one/cancel", b"{}"),
        ("/api/jobs/job-one/continue", b'{"action":"continue"}'),
        ("/api/jobs/job-one/retry", b"{}"),
        ("/api/runs/run-one/clone-workspace", b"{}"),
    ),
)
def test_job_lifecycle_writes_use_selected_service_port(
    tmp_path, monkeypatch, path: str, body: bytes,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"job_id":"job-two"}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}{path}?port=8141",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )) as response:
            value = json.loads(response.read())

    assert value["success"] is True
    assert calls == [{
        "port": 8141,
        "path": path,
        "principal": "user@1",
        "method": "POST",
        "body": body,
        "content_type": "application/json",
    }]


def test_test_workbench_compiles_only_execution_settings_into_analysis() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts" / "worktree_manager_web" / "workbench"
        / "test-configuration.js"
    ).read_text(encoding="utf-8")

    assert "FTTestConfigurationCompiler.executionSettings" in source
    assert "FTTestConfigurationCompiler.authoringSettings" in source
    assert "const settings = structuredClone(state.values);" not in source


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
    i18n = ROOT / "scripts" / "worktree_manager_web" / "core" / "i18n.js"
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

    shell = (ROOT / "scripts" / "worktree_manager_web" / "app" / "shell.js").read_text()
    assert "FTI18n.choosePreference(" in shell
    assert "FTI18n.rememberPreference(preference)" in shell


def test_local_catalog_capability_requires_the_native_swift_bridge() -> None:
    runtime = ROOT / "scripts" / "worktree_manager_web" / "app" / "runtime.js"
    program = f"""
global.window = globalThis;
eval(require("fs").readFileSync({json.dumps(str(runtime))}, "utf8"));
const browser = FTAppRuntime.hasLocalCatalog();
global.webkit = {{messageHandlers: {{factorTesterLocalCatalog: {{
  postMessage: () => ({{}}),
}}}}}};
const swift = FTAppRuntime.hasLocalCatalog();
console.log(JSON.stringify({{browser, swift}}));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )

    assert json.loads(result.stdout) == {"browser": False, "swift": True}


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


def test_web_shell_allows_authenticated_blob_image_previews(tmp_path) -> None:
    """Artifact previews use object URLs after the authenticated fetch."""
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            assert response.headers["Content-Security-Policy"] == (
                "default-src 'self'; img-src 'self' blob: data: https:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'"
            )
            assert response.headers["Cache-Control"] == "no-store"


def test_web_shell_exposes_public_asset_revision(tmp_path) -> None:
    state = manager.ManagerState(tmp_path, "python")
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/api/client-assets/revision") as response:
            value = json.loads(response.read())
            assert response.headers["Cache-Control"] == "no-store"

    revision = value["revision"]
    assert value["success"] is True
    assert len(revision) == 64
    assert f'name="ft-client-assets-revision" content="{revision}"' in shell
    assert f"?v={revision}" in shell


def test_unified_shell_loads_shared_test_workbench_components(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        scripts = {}
        for relative in (
            "workbench/test-settings.js", "workbench/test-factors.js",
            "workbench/test-configuration-compiler.js",
            "workbench/product-group-creator.js",
            "workbench/test-products.js",
            "workbench/test-categories.js",
            "workbench/backtest-group-model.js",
            "workbench/backtest-group-form.js",
            "workbench/backtest-groups.js",
            "workbench/test-configuration.js",
            "workbench/test-templates.js", "workbench/test-run-results.js",
            "workbench/test-run-batch.js",
            "workbench/tests.js",
        ):
            with urlopen(f"{base_url}/research-static/{relative}") as response:
                scripts[relative.rsplit("/", 1)[-1]] = response.read().decode("utf-8")
            assert f'/research-static/{relative}' in shell

    assert "/api/backtest/settings/" in scripts["tests.js"]
    assert "servicePath(`/api/backtest/settings/" not in scripts["tests.js"]
    assert "/api/workspaces" in scripts["tests.js"]
    assert 'servicePath("/api/workspaces")' not in scripts["tests.js"]
    assert "/api/runs/preview" in scripts["test-run-batch.js"]
    assert 'analyses: [state.kind]' in scripts["test-run-batch.js"]
    assert "/api/runs" in scripts["test-run-batch.js"]
    assert 'servicePath("/api/runs/preview")' in scripts["test-run-batch.js"]
    assert 'servicePath("/api/runs")' in scripts["test-run-batch.js"]
    assert "FTICResults?.section" in scripts["test-run-results.js"]
    assert "FTBacktestResults?.section" in scripts["test-run-results.js"]
    assert "window.FTJobs.loadDetail" in scripts["test-run-results.js"]
    assert "local-settings" in scripts["test-settings.js"]
    assert "options.externalTabs" in scripts["test-settings.js"]
    assert 'typeof selected.external === "function"' in scripts["test-settings.js"]
    assert 'nativeList("owners")' in scripts["test-factors.js"]
    assert 'nativeList("revisions"' in scripts["test-factors.js"]
    assert 'nativeList("families"' in scripts["test-factors.js"]
    assert 'nativeRequest("instantiate"' in scripts["test-factors.js"]
    assert "restoreFrozenSelections(state)" in scripts["test-factors.js"]
    assert "selectedProjections" in scripts["test-products.js"]
    assert "FTProductGroupCreator.open" in scripts["test-products.js"]
    creator = scripts["product-group-creator.js"]
    assert '"/api/catalog/product-groups"' in creator
    assert '"/api/client/product_tree"' in creator
    assert '"/api/catalog/tree"' in creator
    assert "FTProductTree.render" in creator
    assert "textarea" not in creator
    assert "/api/data_source_categories" in scripts["test-categories.js"]
    assert "window.FTTestConfiguration" in scripts["test-configuration.js"]
    assert "window.FTTestConfigurationCompiler" in scripts[
        "test-configuration-compiler.js"
    ]
    assert "window.FTBacktestGroupModel" in scripts["backtest-group-model.js"]
    assert "window.FTBacktestGroupForm" in scripts["backtest-group-form.js"]
    assert "window.FTBacktestGroups" in scripts["backtest-groups.js"]
    assert "state.manifest.flows" in scripts["backtest-groups.js"]
    assert 'root.className = "backtest-groups"' in scripts["backtest-groups.js"]
    assert 'state.backtestGroupTab || "groups"' in scripts["backtest-groups.js"]
    assert 'context.t("分组列表")' in scripts["backtest-groups.js"]
    assert 'context.t("Long-Short 组合")' in scripts["backtest-groups.js"]
    assert "FTBacktestGroups.render" in scripts["tests.js"]
    assert "externalTabs" in scripts["tests.js"]
    assert "selectionPanel" not in scripts["tests.js"]
    assert "factor_owner_ref" in scripts["test-factors.js"]
    assert "factor_git_commit" in scripts["test-factors.js"]
    assert "factor_family_ref" in scripts["test-factors.js"]
    assert "factor_params" in scripts["test-factors.js"]
    assert "state.manifest.defaults?.setting_template" in scripts["tests.js"]
    assert "/test-templates/" in scripts["test-templates.js"]
    assert "handlers.overwrite(item)" in scripts["test-templates.js"]
    assert "handlers.delete(item)" in scripts["test-templates.js"]
    assert 'method: "PUT"' in scripts["tests.js"]
    assert 'method: "DELETE"' in scripts["tests.js"]


def test_web_shell_has_swift_style_opened_tabs_and_per_tab_test_state(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/coordinator.js") as response:
            research = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/runtime.js") as response:
            runtime = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/shell.js") as response:
            shell_module = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/report-entry.js") as response:
            report_entry = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/source.js") as response:
            report_source = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/rich-text.js") as response:
            rich_text = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/tabs.js") as response:
            tabs = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/workbench/tests.js") as response:
            tests = response.read().decode("utf-8")

    assert 'id="opened-tabs"' in shell
    assert 'id="opened-caption"' in shell
    assert "function closeTab" in tabs
    assert "function renderOpenedTabs" in tabs
    assert "forceNew: true" in tabs
    assert "window.FTAppRuntime" in runtime
    assert "Object.freeze" in runtime
    assert "FTAppRuntime.create()" in research
    assert "window.FTAppShell" in shell_module
    assert "FTAppShell.create({state, api, t, tabs})" in research
    assert "activeRouteToken" in research
    assert "isRouteCurrent" in research
    assert "const isCurrent = () => context.isRouteCurrent?.() !== false;" in report_entry
    assert "error?.status !== 404" in report_source
    assert "FTReportSource.create" in report_entry
    assert "error.status = response.status" in runtime
    assert "messageHandlers?.researchReference" in report_entry
    assert "nativeReference" in report_entry
    assert "labelOverride" in report_entry
    assert "component_id" in report_entry
    assert "detail_fields" in report_entry
    assert "jobPrefix" in report_entry
    assert 'type === "profile"' in report_entry
    assert "context.nativeReference" in rich_text
    assert "context?.openReference?.(target, label)" in rich_text
    assert 'path.startsWith("/jobs/")' in tabs
    assert "context.tabSession" in tests


def test_swift_research_shell_keeps_section_switches_in_the_pinned_tab() -> None:
    source = (
        ROOT / "apple" / "Sources" / "Navigation" / "ClientTabView.swift"
    ).read_text(encoding="utf-8")
    block_start = source.index("case .research:")
    block_end = source.index("case .jobs:", block_start)
    block = source[block_start:block_end]
    assert "openResearchPath: openEmbeddedNavigation" in block
    assert "open(.researchReport(path:" not in block


def test_web_opened_tab_icons_are_separate_from_labels_and_jobs_have_status_time_presentation() -> None:
    tabs = (ROOT / "scripts" / "worktree_manager_web" / "app" / "tabs.js").read_text(encoding="utf-8")
    jobs = (ROOT / "scripts" / "worktree_manager_web" / "jobs" / "jobs.js").read_text(encoding="utf-8")
    job_detail = (ROOT / "scripts" / "worktree_manager_web" / "jobs" / "detail.js").read_text(encoding="utf-8")
    styles = "\n".join(
        (
            ROOT / "scripts" / "worktree_manager_web" / relative
        ).read_text(encoding="utf-8")
        for relative in ("styles/app.css", "styles/report.css")
    )

    assert "row.append(button, close)" in tabs
    assert "button.append(close)" not in tabs
    assert 'button.title = document.body.classList.contains("sidebar-collapsed") ? "" : tab.title;' in tabs
    assert "statusPill(job.status, context)" in jobs
    assert "context.isRouteCurrent?.() !== false" in jobs
    assert "context.isRouteCurrent?.() !== false" in job_detail
    assert "payload.public === false" in jobs
    assert "未登录时仅显示服务器公开任务（最多 20 个）" in jobs
    assert "function fieldValue(context, key, value)" in job_detail
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in job_detail
    assert ".job-status.succeeded" in styles
    assert ".job-status.failed" in styles
    assert ".job-status.running" in styles
    assert ".job-status.submitted" in styles
    assert "body.sidebar-collapsed .tab-label" in styles
    assert "body.sidebar-collapsed .nav-button,\nbody.sidebar-collapsed .opened-tab" in styles
    assert ".opened-tabs" in styles
    assert "scrollbar-gutter: stable" not in styles
    assert "body.sidebar-collapsed #opened-tabs" in styles
    assert "scrollbar-width: none" in styles
    assert "body.sidebar-collapsed:not(.embedded-presentation) .chapter-rail" in styles
    assert ".component > details > .component-children { margin-left: 20px; padding-left: 0; }" in styles
    assert ".artifact-image { display: block; width: 100%; max-width: 100%; height: auto;" in styles


def test_web_shell_uses_swift_symbol_registry_for_modules_and_references(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/core/icons.js") as response:
            icons = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/rich-text.js") as response:
            rich_text = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/rich-text-blocks.js") as response:
            rich_text_blocks = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/table-view.js") as response:
            table_view = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/lazy-runtime.js") as response:
            lazy_runtime = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/component-view.js") as response:
            components = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/chapter-rail.js") as response:
            chapter_rail = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/report-renderer.js") as response:
            renderer = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/coordinator.js") as response:
            research = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/shell.js") as response:
            shell_module = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/report-entry.js") as response:
            report_entry = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/source.js") as response:
            report_source = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/styles/app.css") as response:
            styles = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/styles/report.css") as response:
            styles += "\n" + response.read().decode("utf-8")

    assert '/research-static/core/icons.js' in shell
    assert 'window.FTIcons' in icons
    assert 'chart.xyaxis.line' in icons
    assert 'person.crop.rectangle.stack' in icons
    assert 'FTIcons.reference' in rich_text
    assert 'factortester-local://' in rich_text
    assert '(?:file)' in rich_text
    assert 'return "file"' in rich_text
    assert 'FTIcons.section' in components
    assert 'window.FTReportChapterRail' in chapter_rail
    assert '__ftChapterRailCleanup' in chapter_rail
    assert 'markerCentersDirty' in chapter_rail
    assert 'Math.floor((low + high) / 2)' in chapter_rail
    assert 'rail.addEventListener("scroll", invalidateMarkerCenters' in chapter_rail
    assert 'FTReportComponents' in renderer
    assert 'IntersectionObserver' in lazy_runtime
    assert 'window.FTReportLazyRuntime' in lazy_runtime
    assert 'context.lazyCallbacks' in lazy_runtime
    assert 'function reset(context)' in lazy_runtime
    assert 'lazyRootMargin' in lazy_runtime
    assert 'FTReportLazyRuntime.observe' in components
    assert 'sharedLazyObserver' not in components
    assert 'MAX_ESTIMATE_DEPTH' in components
    assert 'component-body-lazy' in components
    assert 'content_available' in components
    assert 'context.loadComponent' in components
    assert '__ftLazyCleanup' in renderer + research
    assert '__ftChapterRailCleanup' in chapter_rail
    assert '__ftChapterRailCleanup' not in report_entry
    assert '__ftChapterRailCleanup' not in research
    assert 'renderMath' in rich_text
    assert 'renderDisplayMath' in rich_text_blocks
    assert 'FTReportTables.render' in rich_text_blocks
    assert 'window.FTReportTables' in table_view
    assert 'CHUNK_SIZE' in table_view
    assert 'function markdownLinkAt' in rich_text
    assert 'function isFactorAliasToken' in rich_text
    assert 'const parseTableCells = line =>' in rich_text_blocks
    assert '/^:?-+:?$/' in rich_text_blocks
    assert 'cells.length <= count' in rich_text_blocks
    assert 'factorAliasPipe' in rich_text_blocks
    assert 'split(/\\s*\\|\\s*/)' not in rich_text_blocks
    assert 'asset_ref' in components
    assert 'section-bridge' in components
    assert 'captureScrollPosition' in research
    assert 'FTReportEntry' in report_entry
    assert '/index' in report_source
    assert '/chapters/' in report_source
    assert 'loadChapter' in report_source
    assert 'loadComponent' in report_source
    assert 'metadata=1' in report_source
    assert 'chapterDescriptors' in renderer
    assert 'DEFAULT_CHAPTER_CACHE_LIMIT' in renderer
    assert 'FTReportChapterCache' in renderer
    assert 'chapterCache.set' in renderer
    assert 'chapterLoadToken' in renderer
    assert 'dataset.componentKind' in components
    assert 'overflow-x: auto; overflow-y: auto' in styles
    assert 'id="sidebar-toggle"' in shell
    assert 'id="sidebar-resize-handle"' in shell
    assert 'initializeSidebarLayout' in research
    assert 'ft-sidebar-width' in shell_module
    assert 'sidebar-collapsed' in shell_module
    assert 'item.homeOnly' in shell_module
    assert '"manager", "server_operations"' in shell_module
    assert 'max-height: calc(100vh - 180px)' in styles
    assert 'overflow-x: hidden' in styles
    assert '.component > details > .section-bridge' in styles
    assert 'localResourcePath' in rich_text + report_entry
    assert '/assets/' in report_source
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


def test_manager_module_manifest_is_public_and_keeps_manager_only_entries(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/static/config/modules.json") as response:
            manifest = json.loads(response.read())

    modules = {item["id"]: item for item in manifest["modules"]}
    assert modules["sqlite_web"]["title"] == "数据库"
    assert modules["sqlite_web"]["managerOnly"] is True
    assert modules["sqlite_web"]["homeOnly"] is True
    assert modules["docs"]["managerOnly"] is True
    assert modules["docs"]["homeOnly"] is True
    assert modules["server_operations"]["managerOnly"] is True
    assert modules["server_operations"]["homeOnly"] is True


def test_manager_home_only_modules_use_distinct_symbols(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/core/icons.js") as response:
            icons = response.read().decode("utf-8")
        with urlopen(f"{base_url}/api/modules") as response:
            modules = {item["id"]: item for item in json.loads(response.read())["modules"]}

    assert modules["sqlite_web"]["sfSymbol"] == "cylinder.split.1x2"
    assert modules["docs"]["sfSymbol"] == "book"
    assert 'docs: "book"' in icons
    assert 'sqlite_web: "cylinder.split.1x2"' in icons
    assert '"book":' in icons
    assert '"cylinder.split.1x2":' in icons


def test_manager_proxies_docs_and_public_assets_without_a_service_login(
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
            body=b"<html>docs</html>",
            content_type="text/html",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/docs?presentation=embedded") as response:
            assert response.read() == b"<html>docs</html>"

    assert calls == [{
        "port": 8141,
        "path": "/docs?presentation=embedded",
        "principal": "__public_docs__",
    }]


def test_sqlite_web_requires_login_but_accepts_manager_cookie(tmp_path, monkeypatch) -> None:
    state = authenticated_state(tmp_path)
    gateway_calls = []
    sqlite_calls = []

    def gateway_request(**values):
        gateway_calls.append(values)
        raise AssertionError("SQLite Web must not use a business service port")

    def sqlite_request(**values):
        sqlite_calls.append(values)
        return manager.ManagerSQLiteResponse(
            status=200,
            body=b"<html>sqlite</html>",
            content_type="text/html",
        )

    monkeypatch.setattr(state.gateway, "request", gateway_request)
    monkeypatch.setattr(state.sqlite_web, "request", sqlite_request)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/sqlite-web/") as response:
            shell = response.read()
            assert response.status == 200
        assert b"<html" in shell
        with urlopen(f"{base_url}/sqlite-web/?presentation=embedded") as response:
            embedded_shell = response.read()
            assert response.status == 200
        assert b"<html" in embedded_shell
        request_value = Request(
            f"{base_url}/sqlite-web/?presentation=embedded",
            headers={"Cookie": "ft-manager-session=user-token"},
        )
        with urlopen(request_value) as response:
            assert response.read() == b"<html>sqlite</html>"

    assert gateway_calls == []
    assert len(sqlite_calls) == 1
    assert {
        key: sqlite_calls[0][key]
        for key in ("method", "path", "query", "principal")
    } == {
        "method": "GET",
        "path": "/sqlite-web/",
        "query": "presentation=embedded",
        "principal": "user@1",
    }
    assert sqlite_calls[0]["body"] == b""


def test_manager_client_restores_all_native_service_controls(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/settings/manager.js") as response:
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
        with urlopen(f"{base_url}/research-static/jobs/jobs.js") as response:
            jobs = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/detail.js") as response:
            job_detail = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/actions.js") as response:
            actions = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/artifacts.js") as response:
            artifacts = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/progress.js") as response:
            progress = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/generation.js") as response:
            generation = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/jobs/job-artifact-viewers.js"
        ) as response:
            viewers = response.read().decode("utf-8")

    assert "/stream" in progress
    assert "updateActiveTab" in job_detail
    assert "window.FTJobs.detail = detail" in job_detail
    assert "window.FTJobs.configuration = configuration" in job_detail
    assert "查看测试配置" in job_detail
    assert "查看 RunSpec" in job_detail
    assert "/configuration" in job_detail
    assert "FTReferencePage.routeFor" in job_detail
    assert "runspec:sha256:" in job_detail
    assert "FTJobActions.install" in job_detail
    assert "window.FTJobActions" in actions
    assert 'job.status === "awaiting_confirmation"' in actions
    assert 'add("下一步", "continue"' in actions
    assert 'add("运行到底", "continue"' in actions
    assert 'add("取消任务", "cancel"' in actions
    assert 'add("按冻结配置重试", "retry"' in actions
    assert 'method: "DELETE"' in artifacts
    assert "showDirectoryPicker" in artifacts
    assert "/artifacts/archive" not in artifacts
    assert "equity_curve" in artifacts
    assert "FTJobArtifactViewers.mount" in artifacts
    assert "priceChart" in viewers
    assert "dataTable" in viewers
    assert "tableModel" in viewers
    assert "column_presentations" in viewers
    assert "FTReportTables.render" in viewers
    assert "artifact-image" in viewers
    assert "media_type" in viewers
    assert "/preview" in viewers
    assert "/api/jobs/artifact-capabilities" in generation
    assert "/artifacts/generate" in generation
    assert "output_requests" in generation


def test_web_auth_switches_between_login_and_registration_forms(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/research.html") as response:
            html = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/coordinator.js") as response:
            script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/auth.js") as response:
            auth_script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/styles/app.css") as response:
            styles = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/styles/report.css") as response:
            styles += "\n" + response.read().decode("utf-8")

    assert 'id="login-form"' in html
    assert 'id="register-form" hidden' in html
    assert "FTAuth.bind" in script
    assert 'showAuthForm("register")' in auth_script
    assert 'showAuthForm("login")' in auth_script
    assert "form[hidden]" in styles


def test_web_factor_library_reads_product_group_owned_subject_relations(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        scripts = {}
        for name in ["factor-model", "factor-list", "factor-details", "factors"]:
            with urlopen(
                f"{base_url}/research-static/catalog/{name}.js"
            ) as response:
                scripts[name] = response.read().decode("utf-8")

    model = scripts["factor-model"]
    listing = scripts["factor-list"]
    details = scripts["factor-details"]
    coordinator = scripts["factors"]
    assert "group.factor_refs" in model
    assert "group.factor_set_refs" in model
    assert "value.product_group_refs" not in model
    assert "item.value.target_ref, item.value.set_ref" in model
    assert 'context.api("/api/catalog/factors")' in coordinator
    assert 'context.api("/api/catalog/factor-sets")' in coordinator
    assert "/api/catalog/factor-sets/detail" in details
    assert "servicePath" not in coordinator
    assert "/api/entities/factor-sets" not in coordinator
    assert "/api/catalog/product-groups" in coordinator
    assert "factorTesterLocalFactorSets" in coordinator
    assert "mergeFactorSets" in coordinator
    assert 'visibility: "local"' in model
    assert 'context.t("因子家族")' in listing
    assert 'context.t("因子")' in listing
    assert 'context.t("因子集合")' in listing
    assert '"/factors/sets"' in listing
    assert "decodeFrozenFactorRef" in details


def test_test_workbench_reads_factor_candidates_from_manager_catalog(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        scripts = {}
        for name in (
            "tests", "test-factors", "factor-selection", "test-configuration",
            "test-configuration-compiler",
        ):
            with urlopen(
                f"{base_url}/research-static/workbench/{name}.js"
            ) as response:
                scripts[name] = response.read().decode("utf-8")

    script = scripts["tests"]
    assert 'context.api("/api/catalog/factors")' in script
    assert 'context.api("/api/catalog/product-groups"' in script
    assert '/custom-factors/api/client/factor-library' not in script
    assert 'servicePath("/api/product-groups")' not in script
    assert "return_freq" not in scripts["test-configuration-compiler"]
    assert "test-factor-return-frequency" not in scripts["test-factors"]
    assert "setReturnFrequency" not in scripts["factor-selection"]
    assert 'control.className = "json-code json-editor"' in (
        ROOT / "scripts" / "worktree_manager_web" / "workbench" / "test-settings.js"
    ).read_text(encoding="utf-8")


def test_ic_product_group_selection_preserves_every_selected_path() -> None:
    product_selection = (
        ROOT / "scripts" / "worktree_manager_web" / "workbench" / "test-products.js"
    )
    program = f"""
global.window = globalThis;
eval(require("fs").readFileSync({json.dumps(str(product_selection))}, "utf8"));
const state = {{
  kind: "ic",
  groups: [
    {{id: "day", name: "日盘", paths: ["day-path"]}},
    {{id: "night", name: "夜盘", paths: ["night-path"]}},
  ],
  values: {{product_path_selections: []}},
  groupRef: "",
  groupRefs: FTTestProducts.restoreReferences(
    {{product_path_selections: [{{product_path_selection_id: "night"}}]}},
    {{product_group_refs: ["day", "night"]}},
  ),
}};
FTTestProducts.synchronize(state);
const before = FTTestProducts.selectedProjections(state);
FTTestProducts.setSelected(state, state.groups[1], false);
console.log(JSON.stringify({{
  restored: before.map(item => item.product_path_selection_id),
  paths: before.map(item => item.selected_paths),
  remaining: state.values.product_path_selections.map(
    item => item.product_path_selection_id,
  ),
}}));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == {
        "restored": ["day", "night"],
        "paths": [["day-path"], ["night-path"]],
        "remaining": ["day"],
    }


def test_ic_category_selection_preserves_candidates_and_default() -> None:
    category_selection = (
        ROOT / "scripts" / "worktree_manager_web" / "workbench" / "test-categories.js"
    )
    program = f"""
global.window = globalThis;
eval(require("fs").readFileSync({json.dumps(str(category_selection))}, "utf8"));
const state = {{
  kind: "ic",
  values: {{
    category: "行业",
    category_candidates: [
      {{name: "行业", enabled: true}},
      {{name: "日夜盘", enabled: true}},
    ],
  }},
}};
FTTestCategories.setEnabled(state, state.values.category_candidates[0], false);
FTTestCategories.setCategory(state, state.values.category_candidates[1]);
console.log(JSON.stringify({{
  selected: state.values.category,
  enabled: FTTestCategories.candidates(state).map(item => item.enabled),
}}));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == {
        "selected": "日夜盘",
        "enabled": [False, True],
    }


def test_backtest_group_model_preserves_hierarchy_and_combinations() -> None:
    group_model = (
        ROOT / "scripts" / "worktree_manager_web" / "workbench"
        / "backtest-group-model.js"
    )
    program = f"""
global.window = globalThis;
global.FTTestProducts = {{
  groupID: value => value?.id || value?.product_path_selection_id || "",
  groupLabel: value => value?.name || value?.label || value?.id || "",
  projection: value => ({{
    product_path_selection_id: value.id,
    label: value.name,
    selected_paths: value.paths || [],
  }}),
}};
eval(require("fs").readFileSync({json.dumps(str(group_model))}, "utf8"));
const state = {{analysis: {{groups: [], ls_configs: []}}}};
const roots = FTBacktestGroupModel.addBaseBatch(state, {{
  product_path_selection: {{id: "day", name: "日盘", paths: ["day-path"]}},
  factorAlias: "FactorA", splitCount: 3, groupIndex: 1, allGroups: true,
}});
const child = FTBacktestGroupModel.addDerived(state, roots[0].id, {{
  name: "硅派生组", productMask: ["SI.GFE"],
  overrides: {{position_policy: "buy_and_hold"}},
}});
const combination = FTBacktestGroupModel.addLongShort(
  state, child.id, roots[2].id, "硅多空",
);
const before = {{
  rootAliases: roots.map(group => group.shortAlias),
  childParent: child.parentId,
  childMask: child.productMask,
  childOverride: child.position_policy,
  combination: [combination.longGroupId, combination.shortGroupId],
}};
state.selectedBacktestGroupIDs = [roots[0].id];
FTBacktestGroupModel.removeSelected(state);
console.log(JSON.stringify({{
  before,
  remainingAliases: state.analysis.groups.map(group => group.shortAlias),
  remainingCombinations: state.analysis.ls_configs.length,
}}));
"""
    result = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True,
    )
    value = json.loads(result.stdout)
    assert value["before"]["rootAliases"] == ["A1", "A2", "A3"]
    assert value["before"]["childParent"].startswith("bg_")
    assert value["before"]["childMask"] == {"SI.GFE": True}
    assert value["before"]["childOverride"] == "buy_and_hold"
    assert value["before"]["combination"][0].startswith("dg_")
    assert value["before"]["combination"][1].startswith("bg_")
    assert value["remainingAliases"] == ["A2", "A3"]
    assert value["remainingCombinations"] == 0


def test_backtest_configuration_freezes_groups_products_and_all_factors() -> None:
    source = (
        ROOT / "scripts" / "worktree_manager_web" / "workbench"
        / "test-configuration.js"
    ).read_text(encoding="utf-8")

    assert "state.analysis?.groups" in source
    assert "product_selections: productSelections" in source
    assert "ls_configs: prior.ls_configs || []" in source


def test_manager_factor_catalog_does_not_select_a_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.client_state, "factor_library",
        lambda principal: {
            "principal": principal,
            "factors": [{"factor_ref": "factor:one"}],
            "families": [{"family_ref": "factor-family:one"}],
        },
    )
    monkeypatch.setattr(
        state.client_state, "factor_sets",
        lambda principal, query="": [{
            "target_ref": "factor-set:one",
            "owner_username": principal,
            "query": query,
        }],
    )
    monkeypatch.setattr(
        state.client_state, "factor_set_detail",
        lambda principal, target_ref, **_values: {
            "target_ref": target_ref, "owner_username": principal,
        },
    )

    def reject_service(*_args, **_values):
        raise AssertionError("Manager factor catalog must not use a service port")

    monkeypatch.setattr(state.gateway, "request", reject_service)
    monkeypatch.setattr(state, "preferred_service_port", reject_service)
    monkeypatch.setattr(state, "service_ports", reject_service)
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/catalog/factors", headers=headers,
        )) as response:
            library = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/catalog/factor-sets?query=momentum",
            headers=headers,
        )) as response:
            sets = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/catalog/factor-sets/detail?target_ref=factor-set%3Aone",
            headers=headers,
        )) as response:
            detail = json.loads(response.read())

    assert library["principal"] == "user@1"
    assert library["factors"][0]["factor_ref"] == "factor:one"
    assert sets["items"][0]["query"] == "momentum"
    assert detail["factor_set"]["target_ref"] == "factor-set:one"


def test_web_catalog_profile_and_settings_ignore_stale_async_responses(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        paths = {
            "catalog": "/research-static/catalog/products.js",
            "catalog_details": "/research-static/catalog/details.js",
            "factors": "/research-static/catalog/factors.js",
            "profiles": "/research-static/profile/profiles.js",
            "settings": "/research-static/settings/settings.js",
        }
        scripts = {}
        for name, path in paths.items():
            with urlopen(f"{base_url}{path}") as response:
                scripts[name] = response.read().decode("utf-8")

    for script in scripts.values():
        assert "context.isRouteCurrent?.() !== false" in script
    assert "const payload = await context.api(\"/api/client/profiles\")" in scripts["profiles"]
    assert "const payload = await context.api(\"/api/client/workspace\")" in scripts["settings"]
    assert "if (!current(context)) return;" in scripts["catalog_details"]


def test_web_research_exposes_local_download_shared_and_graph_pages(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(
            f"{base_url}/research-static/research/workspaces.js"
        ) as response:
            workspaces = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/research/local.js"
        ) as response:
            local_page = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/research/shared.js"
        ) as response:
            shared_page = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/coordinator.js") as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research/graph.js") as response:
            graph = response.read().decode("utf-8")

    assert '["local", "本地研究"]' in workspaces
    assert '["shared", "共享研究"]' in workspaces
    assert '["graph", "研究图"]' in workspaces
    assert "FTResearchLocal.render(context, body, embedded)" in workspaces
    assert "FTResearchShared.render(context, body, embedded)" in workspaces
    assert "FTResearchGraph.render(context, body)" in workspaces
    assert "window.FTResearchLocal" in local_page
    assert "clientDownload(context" in local_page
    assert "window.FTResearchShared" in shared_page
    assert "resolvePublicationSource(item, localByReportID, embedded)" in shared_page
    assert "window.FTResearchGraph" in graph
    assert "async function render(context, mount)" in graph
    assert 'get("presentation") === "embedded"' in workspaces
    assert 'context.toolbar.append(tabBar(context, selected, embedded))' in workspaces
    assert 'messageHandlers.researchNavigation.postMessage' in workspaces
    assert 'path: `/research?section=${encodeURIComponent(id)}`' in workspaces
    assert 'body.append(FTUI.loading(context.t("正在读取研究…")))' in workspaces
    assert 'context.content.replaceChildren(body)' in workspaces
    assert 'context.isRouteCurrent?.() === false' in local_page
    assert 'context.isRouteCurrent?.() === false' in shared_page
    assert 'context.isRouteCurrent?.() !== false' in graph
    assert "body.replaceChildren();" in workspaces
    assert 'context.content.append(body)' not in workspaces
    assert "clientDownload(context" in local_page
    assert "if (!embedded || !context.session) return" in local_page
    assert 'context.api("/api/client/research")' in local_page
    assert "embedded && context.session" in shared_page
    assert "item?.is_owned !== true" in shared_page
    assert "local_source: true" in shared_page
    assert 'context.content.replaceChildren(...(embedded ? [] : [tabBar(context, selected)]))' not in workspaces
    assert "/api/public-research" in shared_page
    assert "workPackage" not in workspaces
    assert "research-graphs" not in shell
    assert 'parts[1] === "work"' not in shell
    assert "const pinnedModule = isPinnedPath(initial) ? moduleForPath(initial) : null" in shell
    assert "!tab.closable && tab.id === pinnedModule.id" in shell
    assert 'else if (!isPinnedPath(initial))' in shell


def test_research_workspace_source_resolution_fixture() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "research_publication_source.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_anonymous_web_research_can_proxy_graph_read_only(tmp_path, monkeypatch) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"versions":[]}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    with running_manager(state) as base_url:
        with urlopen(
            f"{base_url}/api/research-graphs/factor-research/versions"
        ) as response:
            assert response.status == 200
            value = json.loads(response.read())

    assert value["success"] is True
    assert calls == [{
        "port": 8141,
        "path": "/api/research-graphs/factor-research/versions",
        "principal": "__public_graph__",
    }]


def test_product_library_uses_header_switch_and_tree(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/catalog/products.js") as response:
            script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/source-list.js") as response:
            source_script = response.read().decode("utf-8")

    assert '[["sources", "数据源"], ["products", "产品"], ["groups", "产品组"]]' in script
    assert 'if (!query)' in script
    assert 'sourceList' in script
    assert 'FTProductSources.list' in script
    assert 'dataModesCell' in source_script
    assert 'frequencyCell' in source_script
    assert 'product_paths' in source_script
    assert 'product-source-page' in source_script
    assert '/api/catalog/sources' in source_script
    assert 'if (localCatalogAvailable())' in source_script
    assert '/api/client/product_sources' in source_script
    assert 'Web 端只能访问服务器提供的数据源' in source_script
    assert 'hasLocalCatalog' in script
    assert 'Manager 提供的产品、合约与行情目录' not in source_script
    assert 'categoryPayload.default_category_id' not in script
    assert 'localStorage.getItem(categoryStorageKey) || ""' in script
    assert 'product-source-tabs' not in script
    assert '/api/catalog/categories' in script
    assert 'servicePath("/api/product_tree")' not in script
    assert '`/api/catalog/tree?${query}`' in script
    assert 'FTProductCategoryModel.availableSourceIDs' in script
    assert 'selectedSources.forEach' in script
    assert 'FTProductTree.render' in script


def test_manager_product_catalog_does_not_select_a_service_port(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.client_state, "product_sources",
        lambda: [{"id": "Local", "source_kind": "server"}],
    )
    monkeypatch.setattr(
        state.client_state, "product_tree",
        lambda category, source_ids: [{
            "title": category or "Product",
            "source_ids": list(source_ids),
            "origin": "server",
        }],
    )
    monkeypatch.setattr(
        state.client_state, "product_contracts",
        lambda name, **_values: {"success": True, "product": name},
    )
    monkeypatch.setattr(
        state.client_state, "product_price_series",
        lambda payload: {"success": True, "product": payload["product_name"]},
    )
    monkeypatch.setattr(
        state.client_state, "product_groups",
        lambda principal: [{
            "name": "候选组", "principal": principal, "catalog_origin": "server",
        }],
    )
    monkeypatch.setattr(
        state.client_state, "create_product_group",
        lambda principal, name, paths: {
            "group_ref": "product-group:created",
            "name": name,
            "paths": paths,
            "principal": principal,
        },
    )

    def reject_gateway(**_values):
        raise AssertionError("Manager catalog must not use a service port")

    def reject_service_port(*_args, **_values):
        raise AssertionError("Manager catalog must not inspect service ports")

    monkeypatch.setattr(state.gateway, "request", reject_gateway)
    monkeypatch.setattr(state, "preferred_service_port", reject_service_port)
    monkeypatch.setattr(state, "service_ports", reject_service_port)
    headers = {"Authorization": "Bearer user-token"}
    with running_manager(state) as base_url:
        with urlopen(Request(f"{base_url}/api/catalog/sources", headers=headers)) as response:
            sources = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/catalog/tree?category=sector", headers=headers,
        )) as response:
            tree = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/catalog/tree", headers=headers,
        )) as response:
            uncategorized_tree = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/catalog/contracts?product=JNI.OSE",
            headers=headers,
        )) as response:
            contracts = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/catalog/prices",
            data=json.dumps({"product_name": "JNI.OSE"}).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )) as response:
            prices = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/catalog/product-groups", headers=headers,
        )) as response:
            groups = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/catalog/product-groups",
            data=json.dumps({
                "name": "新建组", "paths": ["China Futures/Day"],
            }).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )) as response:
            created = json.loads(response.read())

    assert sources["sources"] == [{"id": "Local", "source_kind": "server"}]
    assert tree["category_id"] == "sector"
    assert tree["tree"][0]["title"] == "sector"
    assert tree["tree"][0]["source_ids"] == tree["source_ids"]
    assert tree["tree"][0]["origin"] == "server"
    assert uncategorized_tree["category_id"] == ""
    assert uncategorized_tree["tree"][0]["title"] == "Product"
    assert contracts["product"] == "JNI.OSE"
    assert prices["product"] == "JNI.OSE"
    assert groups["groups"] == [{
        "name": "候选组", "principal": "user@1", "catalog_origin": "server",
    }]
    assert created["group"] == {
        "group_ref": "product-group:created",
        "name": "新建组",
        "paths": ["China Futures/Day"],
        "principal": "user@1",
    }
    product_reads = (
        "/api/list_product_names",
        "/api/product_categories",
        "/api/product_tree",
        "/api/product_fields",
        "/api/contract_tree",
        "/api/get_contracts",
    )
    assert all(
        not any(path.startswith(prefix) for prefix in manager._SERVICE_GET_PREFIXES)
        for path in product_reads
    )
    assert r"/api/get_price_data" not in manager._SERVICE_WRITE_PATTERNS["POST"]


def test_server_catalog_has_no_client_local_projection_contract() -> None:
    from server.services.product_catalog_projection import (
        catalog_product_records,
        product_source_descriptors,
    )

    server_ids = {
        item["id"] for item in product_source_descriptors()
    }
    assert "Tiger" not in server_ids
    assert all(
        item["name"] != "JNI.OSE"
        for item in catalog_product_records()
    )
    assert "origin" not in inspect.signature(product_source_descriptors).parameters
    assert "origin" not in inspect.signature(catalog_product_records).parameters


def test_catalog_exposes_only_base_category_dimensions() -> None:
    from server.modules.shared.price_services import available_product_categories

    categories = available_product_categories()
    assert {item["id"] for item in categories} == {"day_night", "sector"}


def test_product_tree_source_filter_prunes_unavailable_branches(monkeypatch) -> None:
    from server.services import product_catalog_projection as projection

    class Product:
        def __init__(self, name):
            self.name = name

    class Source:
        def supports_product(self, product):
            return product.name == "available"

    monkeypatch.setattr(
        projection,
        "_visible_source_index",
        lambda: {"Selected": Source()},
    )
    value = projection.filter_product_tree({
        "Root": {
            "Available": {"$OBJECTS$": [Product("available")]},
            "Unavailable": {"$OBJECTS$": [Product("missing")]},
        },
    }, ["Selected"])

    assert "Available" in value["Root"]
    assert "Unavailable" not in value["Root"]


def test_local_bundle_filters_real_product_tree_without_a_service_port() -> None:
    from scripts.worktree_manager_client_state import ClientStateService
    from server.services.product_catalog_projection import available_source_ids

    source_ids = available_source_ids()
    assert "Local" in source_ids
    tree = ClientStateService.product_tree(
        "day_night_x_sector", ("Local",),
    )

    assert tree
    assert tree[0]["title"] == "Product"


def test_product_detail_renderer_is_loaded_as_a_separate_catalog_module(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/catalog/details.js") as response:
            details = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/products.js") as response:
            products = response.read().decode("utf-8")

    assert "window.FTProductDetails" in details
    assert "detailHelpers" in products
    assert "async function productDetail(context, target)" in products
    assert 'context.servicePath("/api/get_price_data")' not in details
    assert '"/api/catalog/prices"' in details
    assert '"/api/catalog/contracts"' in details


@pytest.mark.parametrize(
    "path",
    [
        "/api/client/product_sources",
        "/api/client/product_names?data_source=Tiger",
        "/api/client/product_tree?data_source=Tiger",
        "/api/client/product-groups",
    ],
)
def test_client_local_catalog_is_not_served_by_manager(
    tmp_path,
    path: str,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        request = Request(
            f"{base_url}{path}",
            headers={"Authorization": "Bearer user-token"},
        )
        with pytest.raises(HTTPError) as captured:
            urlopen(request)
    assert captured.value.code == 404


def test_product_group_ui_explains_creator_research_and_unavailable_members(
    tmp_path,
) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/catalog/products.js") as response:
            products = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/details.js") as response:
            details = response.read().decode("utf-8")

    assert "creator_kind" in products
    assert "research_bindings" in products
    assert 'context.t("未绑定研究")' in products
    assert "unavailableProductDetail" in details
    assert "非服务器提供，无法展示相关信息" in details
    assert 'context.t("是否为研究创建")' in details


def test_product_tree_renderer_is_published_with_product_page(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/catalog/product-tree.js") as response:
            script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/catalog/product-category-overlay.js") as response:
            overlay = response.read().decode("utf-8")
    assert "window.FTProductTree" in script
    assert "contractTreePath" in script
    assert "创建乘积分类" in script
    assert "应用分类" in script
    assert "product-category-actions" in script
    assert "产品 Category" not in script
    assert "应用 Category" not in script
    assert "创建乘积 Category" not in script
    assert "FTProductCategoryModel.multiply" in script
    assert "FTProductCategoryOverlay.choose" in script
    assert "FTProductCategoryModel.treeNodeInitiallyOpen" in script
    assert "window.FTProductCategoryOverlay" in overlay
    assert "创建乘积分类" in overlay
    assert "选择两个已有分类" in overlay
    assert "创建乘积 Category" not in overlay
    assert "选择两个已有 Category" not in overlay
    assert 'input.type = "checkbox"' in overlay
    assert "showModal" in overlay
    assert "day_night_x_sector" not in script


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


def test_report_snapshot_reference_reuses_reference_presentation_seam() -> None:
    root = ROOT / "scripts" / "worktree_manager_web"
    reference = (root / "research" / "reference.js").read_text(encoding="utf-8")
    report_entry = (root / "report" / "report-entry.js").read_text(encoding="utf-8")
    assert "headerFor" in reference
    assert "FTReferencePage?.headerFor" in report_entry
    assert "reference-tone-${presentation.tone}" in report_entry
