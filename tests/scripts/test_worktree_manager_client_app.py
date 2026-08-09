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
        / "scripts" / "worktree_manager_web" / "workbench" / "tests.js"
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


def test_unified_shell_loads_shared_test_workbench_components(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(base_url) as response:
            shell = response.read().decode("utf-8")
        scripts = {}
        for relative in (
            "workbench/test-settings.js", "workbench/test-factors.js",
            "workbench/test-templates.js", "workbench/tests.js",
        ):
            with urlopen(f"{base_url}/research-static/{relative}") as response:
                scripts[relative.rsplit("/", 1)[-1]] = response.read().decode("utf-8")
            assert f'/research-static/{relative}' in shell

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
        with urlopen(f"{base_url}/research-static/app/runtime.js") as response:
            runtime = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/shell.js") as response:
            shell_module = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/report-entry.js") as response:
            report_entry = response.read().decode("utf-8")
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
    assert "messageHandlers?.researchReference" in report_entry
    assert 'path.startsWith("/jobs/")' in tabs
    assert "context.tabSession" in tests


def test_web_opened_tab_icons_are_separate_from_labels_and_jobs_have_status_time_presentation() -> None:
    tabs = (ROOT / "scripts" / "worktree_manager_web" / "app" / "tabs.js").read_text(encoding="utf-8")
    jobs = (ROOT / "scripts" / "worktree_manager_web" / "jobs" / "jobs.js").read_text(encoding="utf-8")
    job_detail = (ROOT / "scripts" / "worktree_manager_web" / "jobs" / "detail.js").read_text(encoding="utf-8")
    styles = "\n".join(
        (
            ROOT / "scripts" / "worktree_manager_web" / relative
        ).read_text(encoding="utf-8")
        for relative in ("research.css", "styles/report.css")
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
    assert ".component > details > .section-bridge { margin-left: 20px; padding-left: 0; }" in styles
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
        with urlopen(f"{base_url}/research-static/report/component-view.js") as response:
            components = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/chapter-rail.js") as response:
            chapter_rail = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/report-renderer.js") as response:
            renderer = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research.js") as response:
            research = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/shell.js") as response:
            shell_module = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/report/report-entry.js") as response:
            report_entry = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research.css") as response:
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
    assert 'IntersectionObserver' in components
    assert 'sharedLazyObserver' in components
    assert 'context.lazyCallbacks' in components
    assert 'MAX_ESTIMATE_DEPTH' in components
    assert 'component-body-lazy' in components
    assert 'lazyRootMargin' in components
    assert '__ftLazyCleanup' in renderer + research
    assert '__ftChapterRailCleanup' in research
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
    assert '/index' in report_entry
    assert '/chapters/' in report_entry
    assert 'loadChapter' in report_entry
    assert 'chapterDescriptors' in renderer
    assert 'DEFAULT_CHAPTER_CACHE_LIMIT' in renderer
    assert 'writeCachedChapter' in renderer
    assert 'readCachedChapter' in renderer
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
        with urlopen(f"{base_url}/research-static/jobs/artifacts.js") as response:
            artifacts = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/jobs/progress.js") as response:
            progress = response.read().decode("utf-8")
        with urlopen(
            f"{base_url}/research-static/jobs/job-artifact-viewers.js"
        ) as response:
            viewers = response.read().decode("utf-8")

    assert "/stream" in progress
    assert "updateActiveTab" in job_detail
    assert "window.FTJobs.detail = detail" in job_detail
    assert 'method: "DELETE"' in artifacts
    assert "showDirectoryPicker" in artifacts
    assert "/artifacts/archive" not in artifacts
    assert "equity_curve" in artifacts
    assert "FTJobArtifactViewers.mount" in artifacts
    assert "priceChart" in viewers
    assert "dataTable" in viewers
    assert "artifact-image" in viewers
    assert "media_type" in viewers
    assert "/preview" in viewers


def test_web_auth_switches_between_login_and_registration_forms(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/research.html") as response:
            html = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research.js") as response:
            script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/app/auth.js") as response:
            auth_script = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research.css") as response:
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
        with urlopen(f"{base_url}/research-static/catalog/factors.js") as response:
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
        with urlopen(f"{base_url}/research-static/research.js") as response:
            shell = response.read().decode("utf-8")
        with urlopen(f"{base_url}/research-static/research/graph.js") as response:
            graph = response.read().decode("utf-8")

    assert '["local", "本地研究"]' in workspaces
    assert '["shared", "共享研究"]' in workspaces
    assert '["graph", "研究图"]' in workspaces
    assert "clientDownload(context" in workspaces
    assert "renderLocal(context, body, embedded)" in workspaces
    assert "renderShared(context, body, embedded)" in workspaces
    assert "FTResearchGraph.render(context, body)" in workspaces
    assert "window.FTResearchGraph" in graph
    assert "async function render(context, mount)" in graph
    assert 'get("presentation") === "embedded"' in workspaces
    assert 'context.toolbar.append(tabBar(context, selected))' in workspaces
    assert 'body.append(FTUI.loading(context.t("正在读取研究…")))' in workspaces
    assert 'context.content.replaceChildren(body)' in workspaces
    assert 'context.isRouteCurrent?.() === false' in workspaces
    assert 'context.isRouteCurrent?.() !== false' in graph
    assert "body.replaceChildren();" in workspaces
    assert 'context.content.append(body)' not in workspaces
    local_page = workspaces.split("async function renderLocal", 1)[1].split(
        "async function renderGraph", 1
    )[0]
    assert "clientDownload(context" in local_page
    assert "if (!embedded || !context.session) return" in local_page
    assert 'context.api("/api/client/research")' in local_page
    assert "embedded && context.session" in workspaces
    assert 'context.content.replaceChildren(...(embedded ? [] : [tabBar(context, selected)]))' not in workspaces
    assert "/api/public-research" in workspaces
    assert "workPackage" not in workspaces
    assert "research-graphs" not in shell
    assert 'parts[1] === "work"' not in shell
    assert 'tab.path.split("?", 1)[0] === location.pathname' in shell
    assert 'else if (!isPinnedPath(initial))' in shell


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

    assert '[["sources", "数据源"], ["products", "产品"], ["groups", "产品组"]]' in script
    assert 'if (!query)' in script
    assert 'sourceList' in script
    assert 'dataModesCell' in script
    assert 'frequencyCell' in script
    assert 'product_paths' in script
    assert 'default_category_id || ""' in script
    assert 'product-source-tabs' not in script
    assert '/api/product_categories' in script
    assert 'FTProductTree.render' in script


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


def test_local_product_groups_are_manager_owned_and_webview_readable(tmp_path, monkeypatch) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state.client_state,
        "local_product_groups",
        lambda principal: [{"group_ref": "product-group:local-one", "name": "本地组", "source": "local"}],
    )
    with running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/client/product-groups",
            headers={"Authorization": "Bearer user-token"},
        )
        with urlopen(request) as response:
            value = json.loads(response.read())
    assert value == {
        "success": True,
        "source": "local",
        "groups": [{"group_ref": "product-group:local-one", "name": "本地组", "source": "local"}],
    }


def test_product_tree_renderer_is_published_with_product_page(tmp_path) -> None:
    state = authenticated_state(tmp_path)
    with running_manager(state) as base_url:
        with urlopen(f"{base_url}/research-static/catalog/product-tree.js") as response:
            script = response.read().decode("utf-8")
    assert "window.FTProductTree" in script
    assert "contractTreePath" in script
    assert "日夜盘×行业" in script
    assert "分类维度" in script


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
