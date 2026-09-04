"""Contracts for the static Web renderer module manifest."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from server.manager.web import assets as research_static
from server.manager.web.assets import asset_revision, shell_bytes, static_file

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "server" / "manager" / "web"


def test_configuration_compiler_loads_only_for_preview_and_submission() -> None:
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8"))

    dependencies = manifest["group_dependencies"]
    assert "workbench-compiler" not in dependencies["workbench-backtest"]
    assert "workbench-compiler" not in dependencies["workbench-ic-controls"]
    assert "workbench-compiler" in dependencies["workbench-run-submit"]


def test_manifest_matches_html_script_order_and_files() -> None:
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8"))
    template = (WEB_ROOT / manifest["entry"]).read_text(encoding="utf-8")
    html = shell_bytes().decode("utf-8")
    static_html, content_type = static_file(manifest["entry"])

    assert manifest["schema_version"] == 1
    assert manifest["scripts"]
    architecture = manifest["architecture"]
    assert architecture["module_boundary_policy"] == "semantic"
    groups = manifest["groups"]
    assert set(item for files in groups.values() for item in files) == set(manifest["scripts"])
    assert sum(len(files) for files in groups.values()) == len(manifest["scripts"])
    assert manifest["external_styles"] == [
        "katex/katex.min.css", "vendor/highlight/github.min.css",
    ]
    assert manifest["route_groups"]["docs"] == ["docs"]
    assert "docs" not in manifest["initial_groups"]
    assert all(
        not script.startswith("docs/")
        for group in manifest["initial_groups"]
        for script in groups[group]
    )
    assert manifest["styles"] == [
        "styles/app.css", "styles/jobs/result-tabs.css", "styles/report.css",
        "styles/outputs/artifacts.css",
        "styles/outputs/backtest-results.css",
        "styles/workbench.css", "styles/workbench-settings.css",
        "styles/docs.css", "styles/strategy-library.css",
        "styles/task-inputs.css",
    ]
    assert "FT_STATIC_STYLES" in template
    assert "FT_STATIC_SCRIPTS" in template
    assert content_type == "text/html"
    assert static_html.decode("utf-8") == html
    for relative in [*manifest["scripts"], *manifest["styles"]]:
        assert (WEB_ROOT / relative).is_file(), relative

    script_paths = [
        line.split('src="/research-static/', 1)[1].split('"', 1)[0].split("?", 1)[0]
        for line in html.splitlines()
        if 'src="/research-static/' in line and line.endswith("</script>")
    ]
    style_paths = [
        line.split('href="/research-static/', 1)[1].split('"', 1)[0].split("?", 1)[0]
        for line in html.splitlines()
        if 'href="/research-static/' in line and 'stylesheet' in line
    ]
    initial_scripts = [
        *manifest.get("initial_external_scripts", manifest["external_scripts"]),
        *research_static._initial_scripts(manifest),
    ]
    assert script_paths == initial_scripts
    assert set(initial_scripts).issubset({
        *manifest["scripts"], *manifest["external_scripts"],
    })
    assert style_paths == [*manifest["external_styles"], *manifest["styles"]]

    discovered_scripts = {
        path.relative_to(WEB_ROOT).as_posix()
        for path in WEB_ROOT.rglob("*.js")
    }
    assert discovered_scripts == set(manifest["scripts"]), (
        "every production Web module must be listed exactly once in the manifest"
    )
    discovered_styles = {
        path.relative_to(WEB_ROOT).as_posix()
        for path in WEB_ROOT.rglob("*.css")
    }
    assert discovered_styles == set(manifest["styles"])
    # Production modules belong to a semantic group.  Keeping the entry HTML,
    # manifest and architecture notes at the root prevents a coordinator or a
    # stylesheet from silently becoming an unowned global again.
    assert not list(WEB_ROOT.glob("*.js"))
    assert not list(WEB_ROOT.glob("*.css"))


def test_route_script_groups_obey_the_initial_load_contract() -> None:
    manifest = json.loads(
        (WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8")
    )
    groups = manifest["groups"]
    dependencies = manifest["group_dependencies"]
    policy = manifest["architecture"]["route_load_policy"]
    default_budget = policy["default_max_first_party_script_bytes"]
    overrides = policy["first_party_script_overrides"]
    default_external_budget = policy["default_max_initial_external_scripts"]
    external_overrides = policy["external_script_overrides"]
    forbidden = set(policy["forbidden_route_groups"])

    referenced_groups = {
        group
        for values in dependencies.values()
        for group in values
    } | {
        group
        for values in manifest["route_groups"].values()
        for group in values
    }
    assert referenced_groups <= groups.keys(), (
        "every dependency and route group must resolve to a declared group"
    )
    assert overrides.keys() <= manifest["route_groups"].keys()
    assert external_overrides.keys() <= manifest["route_groups"].keys()

    def closure(requested: list[str]) -> set[str]:
        resolved: set[str] = set()

        def visit(group: str) -> None:
            if group in resolved:
                return
            resolved.add(group)
            for dependency in dependencies.get(group, []):
                visit(dependency)

        for group in requested:
            visit(group)
        return resolved

    for route, requested in manifest["route_groups"].items():
        loaded_groups = closure(requested)
        assert loaded_groups.isdisjoint(forbidden), (
            f"{route} must use focused lazy groups, not umbrella groups: "
            f"{sorted(loaded_groups & forbidden)}"
        )
        scripts = {
            script
            for group in loaded_groups
            for script in groups[group]
        }
        loaded_bytes = sum((WEB_ROOT / script).stat().st_size for script in scripts)
        budget = overrides.get(route, default_budget)
        assert loaded_bytes <= budget, (
            f"{route} initially loads {loaded_bytes} first-party script bytes; "
            f"budget is {budget}. "
            "Move non-visible tabs and heavy viewers into a lazy group."
        )
        external_scripts = {
            script
            for group in loaded_groups
            for script in manifest["group_external_scripts"].get(group, [])
        }
        external_budget = external_overrides.get(route, default_external_budget)
        assert len(external_scripts) <= external_budget, (
            f"{route} initially loads {len(external_scripts)} external runtimes; "
            f"budget is {external_budget}. Move optional viewers into a lazy group."
        )


def test_factor_series_entry_auto_mounts_factor_ref_before_run_preview() -> None:
    # factor-series entries arrive with ?factor_ref= but the referenced factor
    # used to mount only after the factor tab was opened.  Two guards keep the
    # execution path correct:
    #  - the workbench first render fires the lazy factor catalog load when a
    #    factorRef is present but not yet mounted (autoMountFactorRef);
    #  - the preview action mounts factor candidates before
    #    FTTestConfiguration.save compiles factor subjects, not after (the old
    #    runRequest placement was too late and preview reported no factor).
    tests_source = (WEB_ROOT / "workbench" / "tests.js").read_text(encoding="utf-8")
    assert "autoMountFactorRef(context, state)" in tests_source
    assert "function autoMountFactorRef(context, state)" in tests_source
    assert "ensureFactorsForExecution" in tests_source
    actions_source = (WEB_ROOT / "workbench" / "run-batch" / "actions.js").read_text(
        encoding="utf-8",
    )
    ensure_call = "await window.FTTests?.ensureFactorsForExecution?.(context, state);"
    assert ensure_call in actions_source
    assert actions_source.index(ensure_call) < actions_source.index(
        "await requestForPreview(context, state, group);",
    )


def test_factor_series_entry_auto_mounts_factor_ref_before_run_preview_sgchg() -> None:
    # The compiler must flatten a mounted candidate's nested dependencies into
    # RunSpec sibling records so the server resolver never sees an
    # unfrozen FactorParam reference (regression: SgChgDurDay -> SgChgPct).
    fixture = (ROOT / "tests" / "scripts" / "fixtures" / "test_configuration_compiler.js")
    assert "factor_dependencies" in fixture.read_text(encoding="utf-8")
    server_source = (
        ROOT / "server" / "modules" / "custom_factors" / "client_library.py"
    ).read_text(encoding="utf-8")
    assert "factor_dependencies" in server_source


def test_page_agent_drawer_uses_the_published_group_loader_api() -> None:
    source = (WEB_ROOT / "profile" / "page-agent-drawer.js").read_text(encoding="utf-8")
    assert 'FTStaticLoader?.loadGroups?.(["profile-agent-chat"])' in source
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8"))
    assert "profile-agent-chat" not in manifest["route_groups"]["profile"]
    assert "profile-agent-chat" in manifest["group_dependencies"]["profile-agent-session"]
    assert "profile/profile-directory.js" not in manifest["groups"]["profile-agent-chat"]
    assert "FTStaticLoader?.ensureGroup" not in source


def test_tab_view_restore_keeps_the_page_agent_trigger_visible() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "tab_view_state.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"

def test_federation_settings_separate_client_and_wireguard_surfaces() -> None:
    source = (WEB_ROOT / "settings" / "settings.js").read_text(encoding="utf-8")

    assert "http://10.77.0.2:17998/api/federation/register" in source
    assert "https://client-visible-host:7998" in source
    assert "WireGuard 17998/17997" in source
    assert "bootstrap_url" in source
    assert "register_url" not in source
    assert "引导服务器地址" in source
    assert "remote-host:7998/api/federation/register" not in source


def _write_test_web_root(root: Path, scripts: list[str]) -> None:
    (root / "research.html").write_text(
        '<html><head><meta name="robots" content="noindex,nofollow">'
        "<!-- FT_STATIC_STYLES --></head><body>"
        "<!-- FT_STATIC_SCRIPTS --></body></html>",
        encoding="utf-8",
    )
    for script in scripts:
        path = root / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"window.{path.stem} = true;", encoding="utf-8")
    (root / "module-manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "entry": "research.html",
        "external_styles": [],
        "styles": [],
        "groups": {"test": scripts},
        "external_scripts": [],
        "scripts": scripts,
    }), encoding="utf-8")


def test_manifest_refreshes_without_manager_restart(tmp_path, monkeypatch) -> None:
    _write_test_web_root(tmp_path, ["one.js"])
    monkeypatch.setattr(research_static, "WEB_ROOT", tmp_path)
    first = shell_bytes().decode("utf-8")

    _write_test_web_root(tmp_path, ["one.js", "two.js"])
    second = shell_bytes().decode("utf-8")

    assert "/research-static/one.js?" in first
    assert "/research-static/two.js?" not in first
    assert "/research-static/two.js?" in second
    assert first != second


def test_asset_revision_changes_when_owned_asset_changes(tmp_path, monkeypatch) -> None:
    _write_test_web_root(tmp_path, ["one.js"])
    monkeypatch.setattr(research_static, "WEB_ROOT", tmp_path)
    first = asset_revision()
    (tmp_path / "one.js").write_text("window.one = 'changed';", encoding="utf-8")

    assert asset_revision() != first


def test_runtime_rejects_undeclared_web_module_asset(tmp_path, monkeypatch) -> None:
    """An old module URL must not bypass the manifest at runtime."""
    unlisted = tmp_path / "stale-module.js"
    unlisted.write_text("window.stale = true;", encoding="utf-8")
    manifest = research_static._module_manifest()
    monkeypatch.setattr(research_static, "WEB_ROOT", tmp_path)
    monkeypatch.setattr(research_static, "_module_manifest", lambda: manifest)

    try:
        static_file("stale-module.js")
    except ValueError as error:
        assert str(error) == "web module asset is not declared in manifest"
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("undeclared Web module was served")


def test_navigation_route_classifier_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "navigation_routes.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_job_progress_is_monotonic_and_terminal() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "job_progress_state.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_help_popover_uses_click_bubble_and_overlay_modes() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "help_popover.js"
    popover = WEB_ROOT / "core" / "help-popover.js"
    field_help = WEB_ROOT / "workbench" / "test-field-help.js"
    result = subprocess.run(
        ["node", str(fixture), str(popover), str(field_help)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_product_category_detail_keeps_route_context_and_dynamic_tab_title() -> None:
    detail = (WEB_ROOT / "catalog" / "product-category-detail.js").read_text(
        encoding="utf-8",
    )

    assert detail.count("helpers.isCurrent(context)") >= 2
    assert "context.updateActiveTab?.({title})" in detail


def test_pinned_feature_and_detail_tabs_have_stable_ownership() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "product_tabs.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_tab_workspace_is_versioned_and_principal_scoped() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "tab_workspace.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_test_draft_clear_resets_only_local_authoring_state() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_draft_clear.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_product_category_composition_uses_all_available_sources() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "product_category_model.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_product_price_panel_uses_source_frequency_and_adjusted_controls() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "product_price_panel.js"
    module = WEB_ROOT / "catalog" / "product-price-panel.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_product_contract_rows_keep_no_data_navigation_and_adjustment_metadata() -> None:
    details = (WEB_ROOT / "catalog" / "details.js").read_text(encoding="utf-8")
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")

    assert "row.dataset.href = \"true\"" in details
    assert "contractRows[index].uid || contractRows[index].contract" in details
    assert "/products/product/${encodeURIComponent(target)}?${query}" in details
    assert "[...contracts.contracts].reverse()" in details
    assert "contract_has_data" in details
    assert "async function contractDetail" in details
    assert ".table-shell thead th" in styles
    assert 'if (!product) return referenceDetail(context, "product", target, helpers)' not in details
    assert "Do not fall back to the generic" in details
    assert "function unavailableContractDetail" in details
    assert "context.t(\"无此产品信息\")" in details
    assert "context.t(\"前复权乘法\")" in details
    assert "context.t(\"后复权乘法\")" in details
    assert "context.t(\"换月比值\")" in details
    assert "FTProductPricePanel.render" in details
    assert "context.api(`/api/report-references/validate" in details
    assert "servicePath(`/api/report-references/validate" not in details
    assert "query.get(\"has_data\") === \"0\"" in details
    assert "正在解析产品引用…" in details


def test_product_tree_selection_collapses_descendant_paths() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "product_tree_selection.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_test_configuration_compiler_separates_authoring_and_execution_state() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_configuration_compiler.js"
    compiler = WEB_ROOT / "workbench" / "test-configuration-compiler.js"
    configuration = WEB_ROOT / "workbench" / "test-configuration.js"
    result = subprocess.run(
        ["node", str(fixture), str(compiler), str(configuration)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_ic_template_actions_use_selected_configuration_group() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "template_actions_ic_group.js"
    source = WEB_ROOT / "workbench" / "templates" / "actions.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_grouped_ic_save_uses_group_owned_factor_and_product_scope() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_configuration_save.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_grouped_and_legacy_ic_configuration_state_restores_authoring_identity() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_configuration_state.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_ic_configuration_group_surface_uses_shared_shell_for_crud_flows() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_configuration_group_surface.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_run_inputs_are_kept_out_of_templates_and_attached_to_each_job() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_input_state.js"
    module = WEB_ROOT / "workbench" / "test-input-state.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_strategy_dependencies_compile_from_uploaded_text_files() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_source_upload.js"
    modules = [
        WEB_ROOT / "workbench" / "test-input-state.js",
        WEB_ROOT / "workbench" / "test-source-upload.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(item) for item in modules)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_run_input_panel_only_renders_backend_declared_controls() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_run_input_panel.js"
    modules = [
        WEB_ROOT / "catalog" / "shared" / "multi-select-filter.js",
        WEB_ROOT / "workbench" / "test-object-picker.js",
        WEB_ROOT / "workbench" / "test-source-upload.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(path) for path in modules)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_job_input_detail_uses_frozen_factor_params_and_valid_preview_paths() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "job_input_detail.js"
    module = WEB_ROOT / "jobs" / "input-detail.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_ic_horizon_and_delay_grids_are_distinct_frozen_settings() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_horizon_settings.js"
    module = WEB_ROOT / "workbench" / "ic-horizon-settings.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backend_registered_run_fields_compile_into_run_requests() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_run_fields.js"
    module = WEB_ROOT / "workbench" / "test-run-fields.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"

    settings = (WEB_ROOT / "settings" / "settings.js").read_text(encoding="utf-8")
    assert '/api/test-authoring/modules/group_test' in settings
    assert 'item?.key === "service_port"' in settings


def test_every_registered_test_setting_has_an_explicit_web_control(tmp_path) -> None:
    import subprocess

    from tools.testers.settings import backtest_setting_registry

    registered = sorted({
        field["value_descriptor"]["editor"]
        for application in backtest_setting_registry._applications
        for field in [
            *backtest_setting_registry.get(application).manifest(client="web")["defaults"].values(),
            *backtest_setting_registry.get(application).manifest(client="swift")["run_fields"],
        ]
    })
    expected = tmp_path / "registered-controls.json"
    expected.write_text(json.dumps(registered), encoding="utf-8")
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_setting_control_contract.js"
    modules = [
        WEB_ROOT / "workbench" / "test-setting-fields.js",
        WEB_ROOT / "workbench" / "test-settings.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(path) for path in modules), str(expected)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_every_backend_tab_adapter_is_registered_in_the_web_renderer(tmp_path) -> None:
    import subprocess

    from tools.testers.settings import backtest_setting_registry

    adapters = sorted({
        tab["content_adapter"]
        for application in backtest_setting_registry._applications
        for mount_tabs in backtest_setting_registry.get(application).manifest(
            client="web"
        )["tab_lists"].values()
        for tab in mount_tabs
    })
    expected = tmp_path / "registered-tab-adapters.json"
    expected.write_text(json.dumps(adapters), encoding="utf-8")
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_mount_adapter_contract.js"
    module = WEB_ROOT / "workbench" / "test-content-adapters.js"
    result = subprocess.run(
        ["node", str(fixture), str(module), str(expected)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_research_shell_defers_heavy_chart_runtime() -> None:
    shell = research_static.shell_bytes().decode("utf-8")
    loader = (WEB_ROOT / "core" / "module-loader.js").read_text(encoding="utf-8")
    coordinator = (WEB_ROOT / "app" / "coordinator.js").read_text(encoding="utf-8")
    tests_module = (WEB_ROOT / "workbench" / "tests.js").read_text(encoding="utf-8")
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8"))

    assert '/research-static/vendor/highcharts/highstock.min.js?v=' not in shell
    assert "const retryDelays = [0, 100, 250, 500, 1000]" in loader
    assert "attempt < retryDelays.length" in loader
    assert 'retry=${attempt}' in loader
    assert 'script.remove()' in loader

    assert "vendor/highcharts/highstock.min.js" in manifest["group_external_scripts"]["job-detail-previews"]
    assert "vendor/highcharts/highstock.min.js" in manifest["group_external_scripts"]["job-detail-ic"]
    assert "vendor/highcharts/highstock.min.js" in manifest["group_external_scripts"]["job-detail-backtest"]
    assert manifest["route_groups"]["jobs"] == ["jobs"]
    assert manifest["route_groups"]["job"] == ["job-detail-core"]
    assert manifest["route_groups"]["job-configuration"] == ["job-detail-core"]
    assert manifest["route_groups"]["job-input"] == ["job-detail-input"]
    assert manifest["route_groups"]["ic-test"] == [
        "workbench-test-ui", "workbench-ic-groups",
    ]
    assert manifest["route_groups"]["backtest"] == ["workbench-test-ui"]
    assert "workbench-backtest" not in manifest["route_groups"]["backtest"]
    assert '"workbench-backtest"' in tests_module
    assert "ensureBacktestCode" in tests_module
    assert manifest["route_groups"]["factor-evaluation"] == ["workbench-test-ui"]
    assert manifest["route_groups"]["factor-series"] == ["workbench-core"]
    assert manifest["route_groups"]["product-categories"] == [
        "catalog-product-categories"
    ]
    assert manifest["route_groups"]["report"] == ["report"]
    assert manifest["group_dependencies"]["research"] == ["research-graph"]
    assert manifest["group_dependencies"]["research-graph"] == [
        "core", "catalog-core"
    ]
    assert "report" not in manifest["group_dependencies"]["research"]
    workspaces = (WEB_ROOT / "research" / "workspaces.js").read_text(encoding="utf-8")
    assert 'loadGroups?.(["profile-directory"])' in workspaces
    assert set(manifest["groups"]["jobs"]) == {
        "jobs/list-format.js", "jobs/progress.js", "jobs/page-tabs.js",
        "jobs/test-types.js", "jobs/jobs.js",
    }
    assert "jobs/detail.js" in manifest["groups"]["job-detail-core"]
    assert "jobs/detail-tabs.js" in manifest["groups"]["job-detail-core"]
    assert "jobs/input-detail.js" in manifest["groups"]["job-detail-input"]
    assert "jobs/highcharts-viewers.js" in manifest["groups"]["job-detail-previews"]
    assert "jobs/job-artifact-viewers.js" in manifest["groups"]["job-detail-previews"]
    assert "jobs/ic-result-view.js" in manifest["groups"]["job-detail-ic"]
    assert "jobs/backtest-group-equity-chart.js" not in manifest["groups"]["job-detail-backtest"]
    assert "test-modules/backtest/results/view.js" in manifest["groups"]["job-detail-backtest"]
    assert "jobs/result-tabs.js" in manifest["groups"]["job-detail-core"]
    assert "test-modules/factor-evaluation/results/view.js" in manifest["groups"]["job-detail-factor-series"]
    assert manifest["group_dependencies"]["job-detail-previews"] == [
        "job-detail-core", "report", "charts",
    ]
    assert manifest["group_dependencies"]["job-detail-factor-series"] == [
        "job-detail-previews", "catalog-core",
    ]
    assert "job-detail-previews" in manifest["group_dependencies"]["job-detail-backtest"]
    assert "output-choice" in manifest["group_dependencies"]["job-detail-core"]
    core_detail = set(manifest["groups"]["job-detail-core"])
    assert "jobs/detail.js" in core_detail
    assert not core_detail.intersection({
        "jobs/highcharts-viewers.js", "jobs/job-artifact-viewers.js",
        "jobs/ic-result-view.js", "test-modules/backtest/results/view.js",
        "test-modules/factor-evaluation/results/view.js", "core/market-data.js",
    })
    artifacts = (WEB_ROOT / "jobs" / "artifacts.js").read_text(encoding="utf-8")
    detail = (WEB_ROOT / "jobs" / "detail.js").read_text(encoding="utf-8")
    result_viewers = (WEB_ROOT / "jobs" / "result-viewers.js").read_text(
        encoding="utf-8"
    )
    run_results = (WEB_ROOT / "workbench" / "test-run-results.js").read_text(encoding="utf-8")
    test_types = (WEB_ROOT / "core" / "test-type-registry.js").read_text(encoding="utf-8")
    assert 'loadGroups?.(["job-detail-previews"])' in artifacts
    assert 'loadGroups?.([name])' in result_viewers
    assert "FTJobResultViewers.loadGroup" in detail
    assert 'loadGroups?.(["job-detail"])' not in run_results
    assert "FTTestTypeRegistry" in run_results
    assert 'job-detail-ic' in test_types and 'job-detail-backtest' in test_types
    assert 'job-detail-factor-series' in test_types
    assert "FTTestRunProgress" in run_results
    assert "group_external_scripts" in loader
    assert manifest["initial_groups"] == ["core", "app"]
    initial = set(research_static._initial_scripts(manifest))
    assert not any(path.startswith("workbench/") for path in initial)
    assert not any(path.startswith("catalog/") for path in initial)
    assert 'link.rel = "preload"' not in loader
    assert "protectedRouteKinds" in coordinator
    state_loader = tests_module.split("async function loadState", 1)[1].split(
        "function lazyReady", 1
    )[0]
    assert 'loadGroup("workbench-factors")' not in state_loader
    assert "FTTestRunFields.initialValues" not in state_loader
    initial_render = tests_module.split("function render", 1)[1].split(
        "window.FTTests", 1
    )[0]
    assert "ensureSettingsCode(context, state" in initial_render
    assert "ensureRunCode(context, state" in initial_render
    assert "ensureRunBatchCode(context, state" in initial_render
    # A login-only deep link must not trigger feature code loading before the
    # existing route guard has rendered its login view.
    assert "if (!state.session && protectedRouteKinds.has(route.kind))" in coordinator


def test_lazy_loader_uses_one_ordered_script_path_for_webkit() -> None:
    loader = (WEB_ROOT / "core" / "module-loader.js").read_text(encoding="utf-8")
    assert 'link.rel = "preload"' not in loader
    assert "preloadScripts" not in loader
    assert "for (const relative of scripts) await loadScript(relative);" in loader


def test_lazy_loader_recovers_within_the_first_user_action() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "module_loader_retry.js"
    loader = WEB_ROOT / "core" / "module-loader.js"
    result = subprocess.run(
        ["node", str(fixture), str(loader)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_product_price_chart_is_interactive_ohlcv() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "interactive_price_chart.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
    panel = (WEB_ROOT / "catalog" / "product-price-panel.js").read_text(encoding="utf-8")
    chart = (WEB_ROOT / "core" / "price-chart.js").read_text(encoding="utf-8")
    assert "FTHighchartsRangeLoader?.attach" in chart
    assert "loadRange:" in panel
    assert "max_points:" in panel


def test_factor_series_result_restores_the_old_multi_panel_viewer() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_series_result.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_job_result_charts_use_interactive_highcharts_data() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "interactive_job_charts.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"

    styles = (WEB_ROOT / "styles" / "outputs" / "artifacts.css").read_text(encoding="utf-8")
    chart_rule = styles.split(
        ".interactive-artifact-chart-canvas", 1
    )[1].split("}", 1)[0]
    assert "height: clamp(520px" in chart_rule
    assert "min-height: 520px" in chart_rule


def test_ic_result_model_reconstructs_the_domain_result_surface() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_result_model.js"
    model = WEB_ROOT / "jobs" / "ic-result-model.js"
    result = subprocess.run(
        ["node", str(fixture), str(model)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_ic_domain_charts_preserve_the_old_result_interactions() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_result_charts.js"
    files = [
        WEB_ROOT / "jobs" / "highcharts-timeline.js",
        WEB_ROOT / "jobs" / "ic-result-model.js",
        WEB_ROOT / "jobs" / "ic-result-charts.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(path) for path in files)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_ic_charts_reuse_job_lazy_query_and_mount_infrastructure() -> None:
    view = (WEB_ROOT / "jobs" / "ic-result-view.js").read_text(encoding="utf-8")
    charts = (WEB_ROOT / "jobs" / "ic-result-charts.js").read_text(encoding="utf-8")
    shared = (WEB_ROOT / "jobs" / "highcharts-viewers.js").read_text(encoding="utf-8")

    assert "FTJobArtifactQuery.timeSource" in view
    assert '{mode: "series", maxPoints: 800}' in view
    assert "source.load({" in view
    assert "FTJobHighcharts.mountOptions" in view
    assert "function mount(" not in charts
    assert "function mountOptions" in shared
    assert "FTMultiSelectFilter.create" in view
    assert 'context.t("IC 类型")' in view
    assert 'context.t("前瞻收益期")' in view
    assert 'context.t("入场延迟")' in view
    assert 'if (tab === "decay") return {method: true, horizon: false' in view
    assert "state.loadToken += 1" in view
    assert "if (!target.isConnected) return" in view


def test_ic_job_results_load_the_shared_chart_timeline_first() -> None:
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text())

    assert manifest["group_dependencies"]["job-detail-ic"] == [
        "job-detail-previews", "catalog-core",
    ]
    assert "factor-catalog-core" in manifest["group_dependencies"]["catalog-core"]
    assert "catalog-selection-core" in manifest["group_dependencies"]["factor-catalog-core"]
    assert "catalog/shared/multi-select-filter.js" in manifest["groups"]["catalog-selection-core"]
    assert manifest["groups"]["job-detail-previews"].index(
        "jobs/highcharts-timeline.js",
    ) < len(manifest["groups"]["job-detail-previews"])


def test_ic_domain_result_view_only_claims_recognized_active_artifacts() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_result_view.js"
    view = WEB_ROOT / "jobs" / "ic-result-view.js"
    result = subprocess.run(
        ["node", str(fixture), str(view)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_test_settings_restore_user_mounted_tabs_and_scoped_reset() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_settings_mounts.js"
    files = [
        WEB_ROOT / "workbench" / "setting-rules.js",
        WEB_ROOT / "workbench" / "test-content-adapters.js",
        WEB_ROOT / "workbench" / "test-settings.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(path) for path in files)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_test_setting_chips_render_manifest_values_and_open_their_tab() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_setting_chips.js"
    source = WEB_ROOT / "workbench" / "test-setting-chips.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_test_settings_mount_live_chips_between_tabs_and_panel() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_setting_chips_integration.js"
    files = [
        WEB_ROOT / "workbench" / "setting-rules.js",
        WEB_ROOT / "workbench" / "test-setting-chips.js",
        WEB_ROOT / "workbench" / "tab-chip-content.js",
        WEB_ROOT / "workbench" / "test-content-adapters.js",
        WEB_ROOT / "catalog" / "shared" / "multi-select-filter.js",
        WEB_ROOT / "workbench" / "test-object-picker.js",
        WEB_ROOT / "workbench" / "test-field-row.js",
        WEB_ROOT / "workbench" / "test-setting-fields.js",
        WEB_ROOT / "workbench" / "test-settings.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(path) for path in files)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_editor_family_picker_uses_the_shared_source_control() -> None:
    source = (WEB_ROOT / "catalog" / "factor-editor.js").read_text(encoding="utf-8")

    assert "FTMultiSelectFilter.create" in source
    assert "function sharedPicker" in source
    assert "function familyPicker" in source
    assert "FTTestFieldRow.create" in source
    assert "function parameterEditor" in source
    assert "factor-editor-source-metadata" in source
    source_controls = source.split("function sourceControls", 1)[1].split(
        "function sourceMetadata", 1,
    )[0]
    assert "FTFactorDetailShared.summary" not in source_controls
    assert "const formulaSource = state.inspection || state.family || state.loaded" in source
    assert "topMount.append(window.FTFactorDetailShared.summary(context, {" in source
    assert "function normalizedInspection" in source
    assert "state.validationMessage" in source
    assert "state.validationError" in source
    assert 'params: state.parameterValues || {}' in source
    assert "FTUI.actionButton" in source
    assert "FTUI.codeEditor" in source
    assert 'loadSourceVersion(\n              context, state.family, "current"' in source
    assert 'loadSourceVersion(\n          context, selectedFamily, "current"' in source
    assert "factor-editor-upload-action" not in source
    assert "const title = document.createElement(\"h2\")" not in source
    assert "test-factor-family-row" not in source

    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")
    assert ".editable-code-editor textarea" in styles
    assert "background: transparent !important" in styles


def test_factor_family_delete_warns_and_backend_cascades_registered_factors() -> None:
    listing = (WEB_ROOT / "catalog" / "factor-catalog-list.js").read_text(
        encoding="utf-8",
    )
    routes = (
        ROOT / "server" / "modules" / "custom_factors" / "crud_routes.py"
    ).read_text(encoding="utf-8")

    assert "function confirmFamilyDeletion" in listing
    assert "factor-family-delete-warning" in listing
    assert "删除家族及因子" in listing
    assert "delete_factor_family_configs" in routes
    assert "cascade_deleted" in routes


def test_frozen_factor_chip_detail_uses_its_snapshot_without_port_resolution() -> None:
    chips = (WEB_ROOT / "workbench" / "test-setting-chips.js").read_text(
        encoding="utf-8",
    )
    overlay = (WEB_ROOT / "workbench" / "object-overlay.js").read_text(
        encoding="utf-8",
    )
    factors = (WEB_ROOT / "catalog" / "factors.js").read_text(encoding="utf-8")
    details = (WEB_ROOT / "catalog" / "factor-details.js").read_text(
        encoding="utf-8",
    )

    assert 'const snapshot = action.kind === "factor"' in chips
    assert "snapshot," in chips
    assert "testObjectSnapshot: options.snapshot === true" in overlay
    assert "context.testObjectTemporary || context.testObjectSnapshot" in factors
    assert "context.testObjectTemporary || context.testObjectSnapshot" in details


def test_factor_detail_modes_share_page_shell_and_family_only_has_version_picker() -> None:
    shared = (WEB_ROOT / "catalog" / "factor-detail-shared.js").read_text(
        encoding="utf-8",
    )
    details = (WEB_ROOT / "catalog" / "factor-details.js").read_text(
        encoding="utf-8",
    )
    editor = (WEB_ROOT / "catalog" / "factor-editor.js").read_text(
        encoding="utf-8",
    )
    factor_view = details.split("async function familyDetail", 1)[0]
    family_view = details.split("async function familyDetail", 1)[1].split(
        "async function withSource", 1,
    )[0]

    assert "function pageClass" in shared
    assert "resolved_math_expr" in shared
    assert "factor-family-formula-raw" in shared
    assert "FTFactorDetailShared.pageClass" in factor_view
    assert "FTFactorDetailShared.pageClass" in family_view
    assert "sourceVersionHistory" not in factor_view
    assert "sourceVersionHistory" in family_view
    assert "FTFactorDetailShared.versionPicker" in editor
    assert 'context.t("读取版本历史")' not in editor
    assert "/api/factor-library/family-sources/" in shared
    assert "/custom-factors/api/source-versions/" not in shared
    assert "/custom-factors/api/public-factor/" not in details
    assert "/custom-factors/api/get/" not in details
    assert "/custom-factors/api/public-factor/" not in editor
    assert "/custom-factors/api/get/" not in editor


def test_factor_object_detail_tabs_share_kind_and_mode_contract() -> None:
    import subprocess

    source = (
        WEB_ROOT / "catalog" / "shared" / "object-detail-tabs.js"
    ).read_text(encoding="utf-8")
    details = (WEB_ROOT / "catalog" / "factor-details.js").read_text(
        encoding="utf-8"
    )
    editor = (WEB_ROOT / "catalog" / "factor-editor.js").read_text(
        encoding="utf-8"
    )
    object_form = (WEB_ROOT / "catalog" / "factor-object-form.js").read_text(
        encoding="utf-8"
    )
    object_jobs = (
        WEB_ROOT / "catalog" / "shared" / "object-job-table.js"
    ).read_text(encoding="utf-8")

    assert 'family: [' in source
    assert 'factor: [' in source
    assert 'set: [' in source
    assert '"未保存"' in source
    assert '"只读"' in source
    assert "FTObjectDetailTabs.create" in details
    assert "FTObjectDetailTabs.create" in editor
    assert "FTObjectDetailTabs.create" in object_form
    assert editor.index("topMount") < editor.index("FTObjectDetailTabs.create")
    assert "FTUI.pagedTable" in object_jobs
    assert '"visible"' in object_jobs
    assert "object_kind" in object_jobs
    assert "context.navigate(`/jobs/${encodeURIComponent" in object_jobs

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "object_detail_tabs.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_object_jobs_are_lazy_and_use_visible_paginated_query() -> None:
    import subprocess

    fixture = (
        ROOT / "tests" / "scripts" / "fixtures" / "factor_object_job_table.js"
    )
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_catalog_lists_expose_shared_edit_actions() -> None:
    source = (WEB_ROOT / "catalog" / "factor-list.js").read_text(encoding="utf-8")
    catalog = (WEB_ROOT / "catalog" / "factor-catalog-list.js").read_text(
        encoding="utf-8",
    )

    assert "onEdit = null" in source
    assert "square.and.pencil" in source
    assert "onEdit: item => editItem" in catalog
    assert "?mode=edit" in catalog
    assert "/api/factor-library/factor-sets?target_ref=" in catalog
    assert "/custom-factors/api/client/factor-sets" not in catalog


def test_factor_candidate_sources_do_not_nest_field_rows_in_the_control_column() -> None:
    source = (WEB_ROOT / "workbench" / "test-factor-candidate-sources.js").read_text(
        encoding="utf-8",
    )
    roles = (WEB_ROOT / "workbench" / "factor-roles.js").read_text(encoding="utf-8")
    styles = (WEB_ROOT / "styles" / "workbench-settings.css").read_text(
        encoding="utf-8",
    )

    assert "test-factor-candidate-heading-row" in source
    assert "function candidateHeading" in source
    assert "function candidatePicker" in source
    assert "function innerPanel" in source
    assert "function scopedSourcePanel" in source
    assert "const scopedSourceStates = new WeakMap()" in source
    assert "owner.factorSourceState" not in source
    assert "sources_when_outer_unmounted" in (
        ROOT / "tools" / "testers" / "settings" / "strategy_editor.py"
    ).read_text(encoding="utf-8")
    assert "dependent.append(markInnerContent(next.overrideContent))" not in source
    assert "if (next.overrideContent) root.append(next.overrideContent)" in source
    assert "test-factor-candidate-sources-inner" in source
    assert "test-factor-candidate-source-row" not in source
    assert source.count("FTTestFieldRow.create(") >= 3
    candidate_index = source.index("function candidateHeading")
    assert candidate_index < source.index("FTTestFactorSets.control")
    assert candidate_index < source.index("FTTestFactorRoles.section")
    assert 'className: "factor-candidate-child-row"' in source
    assert 'direct.classList.add("factor-candidate-child-row")' in source
    assert "factor-candidate-child-section" in roles
    assert ".factor-candidate-child-row > span:first-child" in styles
    assert ".factor-candidate-child-section > .factor-role-section-heading" in styles
    assert 'className: "factor-role-child-row"' in roles
    assert ".factor-role-child-row > span:first-child" in styles
    assert ".factor-candidate-child-section .factor-role-child-row" in styles
    assert ".test-factor-candidate-heading-row { border-top:" not in styles
    assert (
        ".test-factor-candidate-sources > .test-factor-candidate-heading-row "
        "{ border-bottom: 0; }"
    ) not in styles
    assert ".test-setting-row:last-child { border-bottom: 0; }" not in styles
    assert ".test-setting-row {" in styles
    assert "border-bottom: 1px solid var(--line);" in styles


def test_scoped_factor_picker_refreshes_after_visible_catalog_load() -> None:
    fixture = (
        ROOT / "tests" / "scripts" / "fixtures" / "scoped_factor_catalog_refresh.js"
    )
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_restored_nested_editors_restart_idle_catalog_loads() -> None:
    backtest = (WEB_ROOT / "workbench" / "backtest-groups.js").read_text(
        encoding="utf-8",
    )
    ic = (
        WEB_ROOT / "workbench" / "configuration-groups" / "ic" / "adapter.js"
    ).read_text(encoding="utf-8")

    assert "const restoredEditor = state.backtestGroupEditor" in backtest
    assert "if (restoredFlow && editorCatalogsNeedLoad(state))" in backtest
    assert "if (state.icConfigurationGroupEditor && editorCatalogsNeedLoad(state))" in ic
    for source in (backtest, ic):
        assert 'state.lazy?.[key]?.status === "idle"' in source


def test_object_picker_places_create_action_beside_the_shared_control() -> None:
    shared = (WEB_ROOT / "catalog" / "shared" / "multi-select-filter.js").read_text(
        encoding="utf-8",
    )
    picker = (WEB_ROOT / "workbench" / "test-object-picker.js").read_text(
        encoding="utf-8",
    )
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")

    assert 'options.actionsPlacement === "trailing"' in shared
    assert 'controlRow.className = "ft-multi-select-control-row"' in shared
    assert '(actions.length ? "trailing" : undefined)' in picker
    assert "function lazyLoading" in picker
    assert 'status !== "ready" && status !== "error"' in picker
    assert ".ft-multi-select-control-row > .ft-multi-select-dropdown" in styles
    assert ".ft-multi-select-trailing-actions" in styles


def test_nested_strategy_editor_and_object_overlays_have_explicit_layout_contract() -> None:
    tabs = (WEB_ROOT / "workbench" / "strategy-editor-tabs.js").read_text(
        encoding="utf-8",
    )
    form = (WEB_ROOT / "workbench" / "backtest-group-form.js").read_text(
        encoding="utf-8",
    )
    pickers = (WEB_ROOT / "workbench" / "strategy-editor-pickers.js").read_text(
        encoding="utf-8",
    )
    styles = (WEB_ROOT / "styles" / "workbench.css").read_text(encoding="utf-8")

    assert "outer_pre_mounted_tabs" in tabs
    assert "includeEmpty: true" in tabs
    assert "FTTabChipContent.createSettings" in tabs
    assert "FTTabChipContent.createSettingsManager" in tabs
    assert 'rootClass: "backend-settings-shell test-settings-shell strategy-editor-tabs"' in tabs
    assert "includeRun: false" in tabs
    assert "FTTestFactorCandidateSources?.innerPanel" in form
    assert "FTTestFactorCandidateSources.candidatePicker" in form
    assert 'activeKey: editor.activeTabKey || ""' in form
    assert 'onActivate: key => { editor.activeTabKey = key || ""; }' in form
    assert 'activeKey: requestedActiveKey = ""' in tabs
    assert "let activeKey = requestedActiveKey" in tabs
    assert "factorPicker" not in pickers
    assert "compact: true" in (
        WEB_ROOT / "workbench" / "test-factor-candidate-sources.js"
    ).read_text(encoding="utf-8")
    assert ".strategy-editor-chip-row" not in styles
    assert ".backtest-group-shell > .backtest-group-form" in styles
    assert ".ft-object-overlay-dialog > .object-overlay-card" in styles
    assert ".ft-object-overlay-mount > .detail-stack" in styles


def test_dialog_cards_have_shared_viewport_scroll_fallback() -> None:
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")
    dialog_rule = styles.split(".dialog-card {", 1)[1].split("}", 1)[0]
    run_spec_rule = styles.split(".run-spec-dialog-card {", 1)[1].split("}", 1)[0]
    assert "max-height: calc(100dvh - 32px)" in dialog_rule
    assert "overflow-y: auto" in dialog_rule
    assert "overscroll-behavior: contain" in dialog_rule
    assert "overflow: hidden" not in run_spec_rule


def test_open_modal_dialog_freezes_document_and_contains_dropdown_scroll() -> None:
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")
    assert "html:has(dialog[open])" in styles
    assert "body:has(dialog[open])" in styles
    assert "overflow: hidden" in styles.split(
        "html:has(dialog[open])", 1
    )[1].split("}", 1)[0]
    options_rule = styles.split(".ft-multi-select-options {", 1)[1].split("}", 1)[0]
    assert "overscroll-behavior: contain" in options_rule
    assert "dialog[open]" in styles


def test_all_pages_share_responsive_inline_padding_without_width_caps() -> None:
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")
    root_rule = styles.split(":root {", 1)[1].split("}", 1)[0]
    content_rule = styles.split(".content {", 1)[1].split("}", 1)[0]
    assert "--page-inline-padding: 28px" in root_rule
    assert "padding: 28px var(--page-inline-padding)" in content_rule
    assert "max-width: none" in content_rule
    for selector in (
        ".job-detail", ".detail-stack", ".library-page",
        ".profile-directory", ".settings-content", ".manager-page",
        ".manager-access-section", ".manager-directory-section",
        ".test-workbench",
    ):
        rule = styles.split(f"{selector} {{", 1)[1].split("}", 1)[0]
        assert "width: 100%" in rule
        assert "max-width: none" in rule


def test_outer_inner_and_ic_settings_use_one_manager_contract() -> None:
    settings = (WEB_ROOT / "workbench" / "test-settings.js").read_text(
        encoding="utf-8",
    )
    tabs = (WEB_ROOT / "workbench" / "strategy-editor-tabs.js").read_text(
        encoding="utf-8",
    )
    shared = (WEB_ROOT / "workbench" / "tab-chip-content.js").read_text(
        encoding="utf-8",
    )

    assert "function createSettingsManager" in shared
    assert "FTTabChipContent.createSettingsManager" in settings
    assert "FTTabChipContent.createSettingsManager" in tabs
    assert 'className = "strategy-editor-tab-manager"' not in tabs
    assert 'className = "strategy-editor-tab-option"' not in tabs


def test_test_settings_paints_registered_rows_before_lazy_adapter_catalogs() -> None:
    source = (WEB_ROOT / "workbench" / "test-settings.js").read_text(encoding="utf-8")
    panel = source.split("function tabPanel", 1)[1].split(
        "function settingsManager", 1,
    )[0]

    assert panel.index('const lazyKey = FTTestContentAdapters.lazyKey(item.tab);') \
        < panel.index("if (!fields())")
    assert panel.index("if (item.fields.length) {") \
        < panel.index("const adapterReady")
    assert "正在读取此设置…" not in panel
    assert "options.ensureTab?.(item.tab)" in panel


def test_test_workbench_recovers_ready_settings_loader_before_first_paint() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_workbench_settings_bootstrap.js"
    source = WEB_ROOT / "workbench" / "tests.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_test_workbench_defers_catalog_data_until_needed() -> None:
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8"))
    source = (WEB_ROOT / "workbench" / "tests.js").read_text(encoding="utf-8")
    template_actions = (WEB_ROOT / "workbench" / "templates" / "actions.js").read_text(
        encoding="utf-8",
    )
    first_load = source.split(
        "const [manifest, workspaces, savedWorkspaceConfiguration]", 1
    )[1].split("]);", 1)[0]
    assert "/api/test-authoring/modules/${application}/summary" in first_load
    assert "/api/test-authoring/modules/${application}`" not in first_load
    for endpoint in (
        "/api/factor-library/families", "/api/factor-library/factors",
        "/api/product-library/product-groups",
        "/api/product-library/data-source-categories", "/api/test-authoring/configuration-templates",
        "/api/jobs/artifact-capabilities", "/api/client/profiles",
    ):
        assert endpoint not in first_load
    assert "/api/test-authoring/workspace-summaries" in first_load
    assert "workbench-settings" not in first_load
    assert "FTTestInputState.initialize" not in first_load
    assert "FTTestState.initializeInputState(state)" in source
    assert "/api/test-authoring/workspaces/${workspaceID}/configuration" in source
    assert "FTTestFactors.prepare(state)" in template_actions
    assert "function ensureLazyKey" in source
    assert "ensureProductsForExecution" in source
    assert "ensureOutputCapabilities" in source
    assert 'loadGroup("output-choice")' in source
    assert "ensureProfiles" in source
    assert "workbench-run" in manifest["groups"]
    assert manifest["group_dependencies"]["workbench-run"] == [
        "workbench-core", "workbench-settings-controls",
    ]
    assert manifest["group_dependencies"]["workbench-settings-fields"] == [
        "workbench-settings-controls",
    ]
    assert manifest["group_dependencies"]["workbench-settings-controls"] == [
        "workbench-core",
    ]
    assert manifest["group_dependencies"]["workbench-settings-chips"] == [
        "workbench-settings",
    ]
    assert manifest["group_dependencies"]["workbench-test-ui"] == [
        "workbench-settings", "workbench-settings-fields", "workbench-run",
    ]
    assert manifest["group_dependencies"]["workbench-input-state"] == [
        "workbench-core",
    ]
    assert manifest["group_dependencies"]["workbench-core"] == []
    assert "openObjectEditor" in (
        WEB_ROOT / "workbench" / "test-lazy-code.js"
    ).read_text(encoding="utf-8")
    assert "workbench/templates/actions.js" in manifest["groups"]["workbench-core"]
    assert "workbench/templates/actions.js" not in manifest["groups"]["workbench-templates"]
    assert "output-choice" not in manifest["group_dependencies"]["workbench-core"]

    assert manifest["group_dependencies"]["factor-catalog-editor"] == [
        "factor-catalog-core",
        "factor-catalog-enrichment",
        "object-overlay",
    ]
    assert manifest["group_dependencies"]["object-overlay"] == [
        "core", "workbench-object-picker",
    ]
    assert manifest["groups"]["object-overlay"] == [
        "workbench/object-overlay.js",
    ]
    assert "core/output-choices.js" not in research_static._initial_scripts(manifest)
    assert manifest["group_dependencies"]["workbench-compiler"] == ["core"]
    assert manifest["group_dependencies"]["workbench-run-batch"] == ["workbench-core"]
    assert manifest["group_dependencies"]["workbench-run-batch-actions"] == [
        "workbench-run-batch", "workbench-input-state", "workbench-run-submit",
    ]
    assert manifest["group_dependencies"]["workbench-run-results"] == [
        "workbench-run", "job-detail-core",
    ]
    assert set(manifest["groups"]["workbench-run"]) == {
        "workbench/test-run-fields.js",
    }
    assert manifest["groups"]["workbench-run-batch"] == [
        "workbench/run-batch/model.js",
        "workbench/test-run-summary.js",
        "workbench/test-run-batch.js",
    ]
    assert manifest["groups"]["workbench-run-batch-actions"] == [
        "workbench/run-batch/actions.js",
    ]
    assert manifest["groups"]["workbench-run-results"] == [
        "workbench/test-run-progress.js",
        "workbench/test-run-results.js",
    ]
    assert manifest["groups"]["workbench-run-submit"] == [
        "workbench/test-configuration.js",
    ]
    assert set(manifest["groups"]["workbench-settings"]) == {
        "workbench/tab-chip-content.js",
        "workbench/test-settings.js",
        "workbench/test-content-adapters.js",
    }
    assert manifest["groups"]["workbench-settings-chips"] == [
        "workbench/test-setting-chips.js",
    ]
    assert manifest["groups"]["workbench-settings-fields"] == [
        "workbench/test-control-loader.js",
        "workbench/test-settings-schema.js",
    ]
    assert manifest["groups"]["workbench-settings-controls"] == [
        "workbench/test-setting-fields.js",
    ]
    assert manifest["groups"]["workbench-input-state"] == [
        "workbench/test-input-state.js",
    ]
    assert manifest["groups"]["workbench-source-inputs"] == [
        "workbench/test-source-upload.js",
    ]
    assert manifest["group_dependencies"]["workbench-factors"] == [
        "workbench-core", "catalog-core", "workbench-source-inputs",
        "workbench-object-picker",
    ]
    assert manifest["group_dependencies"]["workbench-products"] == [
        "workbench-core", "catalog-core", "workbench-object-picker",
    ]
    assert manifest["groups"]["workbench-object-picker"] == [
        "workbench/test-object-picker.js",
    ]
    assert manifest["group_dependencies"]["workbench-source-inputs"] == [
        "workbench-input-state",
    ]
    assert "workbench/tab-list-chip.js" in manifest["groups"]["workbench-configuration-groups"]
    assert "workbench/tab-list-chip.js" not in research_static._initial_scripts(manifest)
    assert not set(manifest["groups"]["workbench-run"]) & set(
        research_static._initial_scripts(manifest)
    )
    assert not set(manifest["groups"]["workbench-run-batch"]) & set(
        research_static._initial_scripts(manifest)
    )
    assert not set(manifest["groups"]["workbench-run-batch-actions"]) & set(
        research_static._initial_scripts(manifest)
    )
    assert "workbench/factor-roles.js" not in manifest["groups"]["workbench-core"]
    assert "workbench/custom-product-overrides.js" not in manifest["groups"]["workbench-core"]
    assert manifest["control_groups"]["ic_horizon_grid"]["group"] == "workbench-ic-controls"
    assert manifest["control_groups"]["factor_role_bindings"]["group"] == "workbench-factor-controls"
    assert manifest["control_groups"]["custom_product_overrides"]["group"] == "workbench-product-controls"
    assert manifest["group_dependencies"]["workbench-run"] == [
        "workbench-core", "workbench-settings-controls",
    ]
    assert "workbench-ic-controls" not in manifest["group_dependencies"]["workbench-run"]
    assert manifest["group_dependencies"]["workbench-backtest"] == [
        "workbench-configuration-groups",
    ]
    assert manifest["group_dependencies"]["workbench-configuration-groups"] == [
        "workbench-settings", "workbench-settings-controls",
        "workbench-products", "workbench-factors",
    ]
    assert manifest["group_dependencies"]["workbench-run-submit"] == [
        "workbench-run", "workbench-compiler", "workbench-ic-controls",
    ]
    assert manifest["group_dependencies"]["workbench-ic-controls"] == [
        "workbench-core",
    ]
    assert manifest["groups"]["workbench-compiler"] == [
        "workbench/test-configuration-compiler.js",
    ]
    assert "workbench/test-configuration-compiler.js" not in manifest[
        "groups"]["workbench-core"]
    assert "workbench/test-input-state.js" not in manifest["groups"]["workbench-core"]
    assert manifest["group_dependencies"]["settings"] == ["core"]
    assert not set(manifest["groups"]["workbench-settings"]) & set(
        research_static._initial_scripts(manifest)
    )
    assert "ensureRunCode" in source
    assert "ensureRunBatchCode" in source
    assert "ensureBacktestCode" in source
    assert 'state, "backtestCode", "workbench-backtest"' in source
    assert 'deferredPanel(context, state, "分组策略"' not in source
    assert "ensureSettingsCode" in source
    assert "ensureSettingsChipsCode" in source
    assert "ensureRunSubmitCode" in source
    assert "workbench-run-submit" in source
    settings_source = (WEB_ROOT / "workbench" / "test-settings.js").read_text(
        encoding="utf-8",
    )
    assert "if (window.FTTestSettingChips)" in settings_source
    assert "ensureSettingsChipsCode" in source
    lazy_code = (WEB_ROOT / "workbench" / "test-lazy-code.js").read_text(
        encoding="utf-8",
    )
    assert '"workbench-run-batch"' in lazy_code
    assert '"workbench-run-batch-actions"' in lazy_code
    assert "ensureRunBatchActionsCode" in lazy_code
    assert "ensureGroupCode" in lazy_code
    run_batch = (WEB_ROOT / "workbench" / "test-run-batch.js").read_text(encoding="utf-8")
    run_actions = (WEB_ROOT / "workbench" / "run-batch" / "actions.js").read_text(
        encoding="utf-8",
    )
    assert 'loadGroups?.(["workbench-run-results"])' not in run_batch
    progress = (WEB_ROOT / "workbench" / "test-run-progress.js").read_text(
        encoding="utf-8",
    )
    assert "FTJobProgress.progressView" in progress
    assert "FTJobProgress.watchProgress" in progress
    assert "FTTestRunSummary?.planSummary" not in run_batch
    assert "ensureRunBatchActionsCode" in run_batch
    assert "context.api(" not in run_batch
    assert "FTTestInputState.requestBody" not in run_batch
    assert "FTTestConfiguration.save" not in run_batch
    assert "context.api(" in run_actions
    assert "FTTestInputState.requestBody" in run_actions
    assert "FTTestConfiguration.save" in run_actions
    assert 'loadGroups?.(["workbench-run-submit"])' not in run_actions
    assert 'run_inputs: "workbench-source-inputs"' in (
        WEB_ROOT / "workbench" / "test-lazy-code.js"
    ).read_text(encoding="utf-8")


def test_deferred_configuration_runtime_is_only_read_through_window() -> None:
    """Dynamic scripts must not rely on a browser-created bare global binding."""
    for relative in (
        "workbench/run-batch/actions.js",
        "workbench/templates/actions.js",
        "workbench/test-page-assistance.js",
    ):
        source = (WEB_ROOT / relative).read_text(encoding="utf-8")
        assert re.search(r"(?<![.\w])FTTestConfiguration\b", source) is None


def test_test_template_is_a_registered_tab_panel_with_icon_actions() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_template_panel.js"
    source = WEB_ROOT / "workbench" / "test-templates.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_ic_configuration_group_form_uses_registered_delay_and_return_basis() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_configuration_group_form.js"
    source = WEB_ROOT / "workbench" / "configuration-groups" / "ic" / "form.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_ic_configuration_group_model_enforces_single_scope_factor_and_delay() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_configuration_group_model.js"
    source = WEB_ROOT / "workbench" / "configuration-groups" / "ic" / "model.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_configuration_group_surface_is_shared_infrastructure() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "configuration_group_surface.js"
    source = WEB_ROOT / "workbench" / "configuration-groups" / "common" / "surface.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backtest_strategy_surfaces_follow_backend_adapter_and_selection_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_group_surfaces.js"
    source = WEB_ROOT / "workbench" / "backtest-groups.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_strategy_list_keeps_compact_batch_and_inline_name_interactions() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "strategy_list.js"
    source = WEB_ROOT / "workbench" / "strategy-list.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backtest_group_forms_mount_shared_picker_elements() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_group_form.js"
    source = WEB_ROOT / "workbench" / "backtest-group-form.js"
    pickers = WEB_ROOT / "workbench" / "strategy-editor-pickers.js"
    result = subprocess.run(
        ["node", str(fixture), str(source), str(pickers)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_nested_strategy_editor_respects_outer_scope_and_inner_mount_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "strategy_editor_scope.js"
    source = WEB_ROOT / "workbench" / "strategy-editor-scope.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backend_nested_scope_contract_is_renderable_by_web_resolver(tmp_path) -> None:
    import json
    import subprocess

    from tools.testers.settings import backtest_setting_registry

    manifest_path = tmp_path / "group-test-manifest.json"
    manifest_path.write_text(
        json.dumps(backtest_setting_registry.get("group_test").manifest()),
        encoding="utf-8",
    )
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "strategy_editor_scope.js"
    source = WEB_ROOT / "workbench" / "strategy-editor-scope.js"
    result = subprocess.run(
        ["node", str(fixture), str(source), str(manifest_path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_test_configuration_persists_mounted_tabs_with_authoring_state() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_configuration_mounts.js"
    source = WEB_ROOT / "workbench" / "test-configuration.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_test_templates_restore_inline_objects_without_catalog_rows() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_temporary_template_state.js"
    source = WEB_ROOT / "workbench" / "test-state.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backtest_result_model_reconstructs_persisted_domain_outputs() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_results" / "result_model.js"
    model = WEB_ROOT / "test-modules" / "backtest" / "results" / "model.js"
    runtime = WEB_ROOT / "test-modules" / "backtest" / "results" / "runtime-model.js"
    result = subprocess.run(
        ["node", str(fixture), str(model), str(runtime)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backtest_result_view_only_claims_recognized_active_artifacts() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_results" / "result_view.js"
    view = WEB_ROOT / "test-modules" / "backtest" / "results" / "view.js"
    result = subprocess.run(
        ["node", str(fixture), str(view)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backtest_strategy_selection_filters_by_stable_identity() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_results" / "strategy_selection.js"
    module = WEB_ROOT / "test-modules" / "backtest" / "results" / "strategy-selection.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backtest_result_group_loads_shared_multi_select_dependency() -> None:
    manifest = json.loads(
        (WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8")
    )

    dependencies = manifest["group_dependencies"]["job-detail-backtest"]
    assert "catalog-core" in dependencies
    assert (
        "factor-catalog-core" in manifest["group_dependencies"]["catalog-core"]
    )
    assert "catalog-selection-core" in manifest["group_dependencies"]["factor-catalog-core"]
    assert (
        "catalog/shared/multi-select-filter.js"
        in manifest["groups"]["catalog-selection-core"]
    )


def test_backtest_result_view_reports_initialization_errors() -> None:
    source = (
        WEB_ROOT / "test-modules" / "backtest" / "results" / "view.js"
    ).read_text(encoding="utf-8")

    assert "catch (error)" in source
    assert "回测结果初始化失败" in source


def test_backtest_analysis_api_uses_job_scoped_manager_routes() -> None:
    import subprocess

    module = WEB_ROOT / "test-modules" / "backtest" / "results" / "analysis" / "api.js"
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_results" / "analysis_api.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_factor_evaluation_has_a_direct_agent_assistance_document() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_evaluation_assistance.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_independent_page_headers_ignore_stale_route_updates() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "route_presentation.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_backtest_group_detail_restores_fee_rules_and_intraday_windows() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_results" / "group_detail_parts.js"
    base = WEB_ROOT / "test-modules" / "backtest" / "results" / "analysis"
    detail = (base / "group-detail.js").read_text(encoding="utf-8")
    assert "FTBacktestGroupDetailProducts" in detail
    modules = [
        WEB_ROOT / "jobs" / "highcharts-timeline.js",
        base / "group-products.js",
        base / "group-detail-parts.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(module) for module in modules)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_job_result_can_restore_workspace_and_prefill_current_group_editor() -> None:
    import subprocess

    cases = (
        (
            ROOT / "tests" / "scripts" / "fixtures" / "job_workspace_restore.js",
            WEB_ROOT / "jobs" / "actions.js",
        ),
        (
            ROOT / "tests" / "scripts" / "fixtures" / "backtest_derived_prefill.js",
            WEB_ROOT / "workbench" / "tests.js",
        ),
    )
    for fixture, module in cases:
        result = subprocess.run(
            ["node", str(fixture), str(module)], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        assert result.stdout.strip() == "ok"


def test_backtest_group_batch_builds_factor_by_quantile_cartesian_product() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_group_model.js"
    model = WEB_ROOT / "workbench" / "backtest-group-model.js"
    result = subprocess.run(
        ["node", str(fixture), str(model)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backtest_group_overrides_use_registered_sparse_settings() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_group_overrides.js"
    model = WEB_ROOT / "workbench" / "backtest-group-overrides.js"
    result = subprocess.run(
        ["node", str(fixture), str(model)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_shared_multi_select_enforces_exclusive_and_single_selection() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "multi_select_filter.js"
    source = WEB_ROOT / "catalog" / "shared" / "multi-select-filter.js"
    remote_source = WEB_ROOT / "catalog" / "shared" / "multi-select-filter-remote.js"
    result = subprocess.run(
        ["node", str(fixture), str(remote_source), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
    picker = source.read_text(encoding="utf-8")
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")
    factor_filter = (WEB_ROOT / "catalog" / "factor-group-filter.js").read_text(
        encoding="utf-8"
    )
    assert 'options.menuClass || ""' in picker
    assert "get hasSelection()" in picker
    assert "selectedFirst" not in picker
    assert "height: max-content" in styles
    assert ".ft-multi-select-options" in styles
    assert 'menuClass: "factor-product-group-filter-menu"' in factor_filter
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text())
    assert "catalog-selection-remote" in manifest["group_dependencies"][
        "workbench-strategy-bindings"
    ]
    assert str(remote_source.relative_to(WEB_ROOT)).replace("\\", "/") in manifest[
        "groups"]["catalog-selection-remote"]


def test_multi_select_object_rows_open_matching_view_overlays() -> None:
    import subprocess

    # Option rows that carry an object (factor, family, product group,
    # category, factor set, ...) must open the matching view overlay from
    # their "?" icon; plain text rows keep the text bubble.  Inside an open
    # overlay the opener must route through the frame stack so the view is a
    # nested child overlay, not a second top-level dialog.
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "multi_select_filter.js"
    source = WEB_ROOT / "catalog" / "shared" / "multi-select-filter.js"
    remote_source = WEB_ROOT / "catalog" / "shared" / "multi-select-filter-remote.js"
    result = subprocess.run(
        ["node", str(fixture), str(remote_source), str(source)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
    picker = source.read_text(encoding="utf-8")
    assert "function openItemView" in picker
    assert "function optionHelp" in picker
    assert "options.viewOf" in picker
    assert 'item?.view || null' in picker

    # The shared row-view helpers classify library vs test-local objects.
    helpers_fixture = ROOT / "tests" / "scripts" / "fixtures" / "row_view_helpers.js"
    shared = WEB_ROOT / "catalog" / "factor-detail-shared.js"
    helper_result = subprocess.run(
        ["node", str(helpers_fixture), str(shared)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert helper_result.returncode == 0, (
        helper_result.stderr or helper_result.stdout
    )
    assert helper_result.stdout.strip() == "ok"

    # Call sites must declare row views so the shared picker can open them.
    factor_editor = (WEB_ROOT / "catalog" / "factor-editor.js").read_text(
        encoding="utf-8"
    )
    factors_page = (WEB_ROOT / "catalog" / "factors.js").read_text(
        encoding="utf-8"
    )
    for candidate in [
        "workbench/test-factor-candidates.js",
        "workbench/test-factor-candidate-sources.js",
        "workbench/test-products.js",
        "workbench/test-categories.js",
        "workbench/factor-set-selection.js",
    ]:
        text = (WEB_ROOT / candidate).read_text(encoding="utf-8")
        assert "factorRowView" in text or "productGroupRowView" in text \
            or "categoryRowView" in text or "factorSetRowView" in text, candidate
    assert "familyRowView" in factor_editor
    assert "factorRowView" in factor_editor
    assert "factor_set_only === true" in shared.read_text(encoding="utf-8")
    assert "testObjectTemporary" in factors_page


def test_inline_strategy_creation_uses_shared_nested_object_overlay() -> None:
    panel = (WEB_ROOT / "workbench" / "strategy-binding-panel.js").read_text(
        encoding="utf-8",
    )
    overlay = (WEB_ROOT / "workbench" / "object-overlay.js").read_text(
        encoding="utf-8",
    )
    styles = (WEB_ROOT / "styles" / "strategy-library.css").read_text(
        encoding="utf-8",
    )

    assert 'kind: "strategy"' in panel
    assert "FTObjectOverlay.open" in panel
    assert "FTStrategyLibraryEditor.create" not in panel
    assert 'temporary: true' in panel
    assert "strategy-inline-dialog" not in panel
    assert 'strategy: {' in overlay
    assert 'load: "strategy-library-editor-core"' in overlay
    assert 'submitLabel || "保存"' in overlay
    assert "strategy-inline-dialog" not in styles
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text())
    assert "strategy-library-editor-core" not in manifest["group_dependencies"][
        "workbench-strategy-bindings"
    ]


def test_nested_object_overlay_mounts_one_toolbar_per_frame() -> None:
    overlay = (WEB_ROOT / "workbench" / "object-overlay.js").read_text(
        encoding="utf-8",
    )
    editor = (WEB_ROOT / "catalog" / "factor-editor.js").read_text(
        encoding="utf-8",
    )
    styles = (WEB_ROOT / "styles" / "workbench.css").read_text(encoding="utf-8")

    assert "frame.toolbar ||= document.createElement" in overlay
    assert "frameActions.replaceChildren(frame.toolbar)" in overlay
    assert "toolbar: frame.toolbar" in overlay
    assert "testObjectOverlay: true" in overlay
    assert 'context.testObjectOverlay === true' in editor
    assert '? "保存" : mode === "create" ? "提交"' in editor
    assert 'kind: "factor_family", mode: currentFamily ? "edit" : "create"' in editor
    assert 'onSaved: family => {' in editor
    assert "temporary: true" in editor
    assert ".ft-object-overlay-frame-actions" in styles
    assert ".ft-object-overlay-frame-toolbar" in styles


def test_registered_locked_fields_share_one_visual_and_picker_contract() -> None:
    fields = (WEB_ROOT / "workbench" / "test-setting-fields.js").read_text(
        encoding="utf-8"
    )
    rows = (WEB_ROOT / "workbench" / "test-field-row.js").read_text(
        encoding="utf-8"
    )
    picker = (WEB_ROOT / "catalog" / "shared" / "multi-select-filter.js").read_text(
        encoding="utf-8"
    )
    styles = (WEB_ROOT / "styles" / "workbench-settings.css").read_text(
        encoding="utf-8"
    )

    assert "FTSettingRules.lockingFields" in fields
    assert "disabledReason: options.disabledReason" in fields
    assert 'row.classList.add("is-locked")' in rows
    assert 'lock.className = "test-field-row-lock"' in rows
    assert 'lockIndicator.className = "ft-multi-select-lock-indicator"' in picker
    assert ".test-setting-row.is-locked" in styles


def test_settings_picker_can_escape_the_tab_content_boundary() -> None:
    settings_css = (WEB_ROOT / "styles" / "workbench-settings.css").read_text(
        encoding="utf-8"
    )
    task_css = (WEB_ROOT / "styles" / "task-inputs.css").read_text(
        encoding="utf-8"
    )
    picker = (WEB_ROOT / "catalog" / "shared" / "multi-select-filter.js").read_text(
        encoding="utf-8"
    )

    assert ".backend-settings-shell.has-open-multi-select" in settings_css
    assert ".test-workbench .test-settings-shell.has-open-multi-select" in task_css
    assert 'shell.classList.toggle("has-open-multi-select"' in picker


def test_backtest_group_form_uses_registered_override_editor() -> None:
    form = (WEB_ROOT / "workbench" / "backtest-group-form.js").read_text(
        encoding="utf-8"
    )

    assert "FTBacktestGroupOverrides.render" in form
    assert "FTStrategyEditorOverrides" in form
    assert "overrideEditor?.value?.()" in form
    assert "fallbackOverrides.value()" in form
    assert "parseObject(overrides.value" not in form


def test_json_details_use_a_bounded_code_container() -> None:
    shared_ui = (WEB_ROOT / "core" / "shared-ui.js").read_text(encoding="utf-8")
    factor_detail = (WEB_ROOT / "catalog" / "factor-detail-shared.js").read_text(
        encoding="utf-8"
    )
    report_view = (WEB_ROOT / "report" / "component-view.js").read_text(
        encoding="utf-8"
    )
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")

    assert '["json-code", "code-viewer", options.className || ""]' in shared_ui
    assert 'body.className = `language-${language}`' in shared_ui
    assert "window.hljs.highlightElement(body)" in shared_ui
    assert "FTUI.code(" in factor_detail
    assert 'language: sourceCode ? "python" : ""' in factor_detail
    assert 'document.createElement("pre")' not in factor_detail
    assert "function isJSONCode(component, content)" in report_view
    assert "JSON.parse(source)" in report_view
    assert 'isJSONCode(component, content) ? "json-code"' in report_view
    assert ".json-code" in styles
    assert "max-height:" in styles.split(".json-code", 1)[1].split("}", 1)[0]
    assert "overflow: auto" in styles.split(".json-code", 1)[1].split("}", 1)[0]
    assert ".code-viewer code.hljs" in styles


def test_highlight_js_is_pinned_and_loaded_with_the_shared_code_viewer() -> None:
    import hashlib

    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text())
    vendor = ROOT / "static" / "vendor" / "highlight"
    checksums = json.loads((vendor / "checksums.json").read_text())

    script = "vendor/highlight/highlight.min.js"
    style = "vendor/highlight/github.min.css"
    assert script not in manifest["initial_external_scripts"]
    assert script in manifest["external_scripts"]
    assert manifest["group_external_scripts"]["code-viewer"] == [script]
    assert "code-viewer" not in manifest["group_dependencies"]["product-catalog-core"]
    assert "code-viewer" in manifest["group_dependencies"]["report"]
    assert style in manifest["external_styles"]
    assert checksums["version"] == "11.11.1"
    for filename, expected in checksums["sha256"].items():
        assert hashlib.sha256((vendor / filename).read_bytes()).hexdigest() == expected


def test_shared_paged_table_keeps_pager_outside_scroll_container() -> None:
    shared_ui = (WEB_ROOT / "core" / "shared-ui.js").read_text(encoding="utf-8")
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")

    assert 'shell.className = "shared-paged-table"' in shared_ui
    assert "shell.append(view.shell, pagination)" in shared_ui
    assert "tableShell: view.shell" in shared_ui
    assert ".shared-paged-table > .table-shell" in styles
    pagination_rule = styles.split(".shared-table-pagination", 1)[1].split("}", 1)[0]
    assert "border-top: 0" in pagination_rule


def test_job_detail_uses_the_shared_run_spec_view() -> None:
    detail = (WEB_ROOT / "jobs" / "detail.js").read_text(encoding="utf-8")
    result_viewers = (WEB_ROOT / "jobs" / "result-viewers.js").read_text(
        encoding="utf-8"
    )
    detail_page, configuration_page = detail.split(
        "async function configuration", 1
    )

    assert 'context.t("在配置页面打开")' in detail_page
    assert "FTRunSpecView.open(context, runSpec.target, runSpec.serverID)" not in detail_page
    assert "FTRunSpecView.load(" in detail_page
    assert "FTRunSpecView.render(context, value)" in detail_page
    assert 'context.t("结果预览")' in result_viewers
    assert "FTJobDetailTabs.create" in detail_page
    assert 'context.t("查看运行配置")' not in detail_page
    assert "loadSelectedSection(detailTabs.current())" in detail_page
    assert 'id === "configuration"' in detail_page
    assert "FTReferencePage.render(context" in configuration_page
    assert 'kind: "run-spec"' in configuration_page
    assert 'context.t("结果预览")' not in configuration_page
    assert "FTJobArtifacts.lazyArtifactPreview" not in configuration_page
    assert "FTJobArtifacts.lazyArtifactPreview" in result_viewers


def test_job_detail_internal_tabs_preserve_the_selected_section() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "job_detail_tabs.js"
    module = WEB_ROOT / "jobs" / "detail-tabs.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_job_detail_supplemental_history_is_lazy_searchable_and_paged() -> None:
    detail = (WEB_ROOT / "jobs" / "detail.js").read_text(encoding="utf-8")
    supplemental = (WEB_ROOT / "jobs" / "supplementals.js").read_text(
        encoding="utf-8"
    )

    assert 'id === "supplementals"' in detail
    assert "supplementalView.load()" in detail
    assert "FTUI.pagedTable" in supplemental
    assert 'search.type = "search"' in supplemental
    assert 'remote: true' in supplemental
    assert "requestedSupplemental = job" in detail
    assert 'resultHost.dispatchEvent(new CustomEvent(' not in detail


def test_custom_analysis_tabs_are_shared_by_all_job_result_viewers() -> None:
    custom = (WEB_ROOT / "jobs" / "custom-analyses.js").read_text(
        encoding="utf-8"
    )
    backtest = (
        WEB_ROOT / "test-modules" / "backtest" / "results" / "view.js"
    ).read_text(encoding="utf-8")
    ic = (WEB_ROOT / "jobs" / "ic-result-view.js").read_text(encoding="utf-8")
    factor = (WEB_ROOT / "test-modules" / "factor-evaluation" / "results" / "view.js").read_text(
        encoding="utf-8"
    )

    assert "if (context.session)" in custom
    for source in (backtest, ic, factor):
        assert "customAnalyses?.tabs" in source
        assert 'key === "custom-analysis:new"' in source
        assert "customAnalyses.render" in source


def test_custom_analysis_tab_edit_and_close_do_not_compete_with_activation() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "job_custom_analysis_tabs.js"
    module = WEB_ROOT / "jobs" / "result-tabs.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_artifact_capabilities_never_forward_cookies_or_redirect_bearers() -> None:
    artifacts = (WEB_ROOT / "jobs" / "artifacts.js").read_text(
        encoding="utf-8"
    )

    assert 'credentials: "omit"' in artifacts
    assert 'redirect: "error"' in artifacts


def test_test_configuration_uses_a_tabbed_settings_page() -> None:
    settings = (WEB_ROOT / "workbench" / "test-settings.js").read_text(encoding="utf-8")
    run_fields = (WEB_ROOT / "workbench" / "test-run-fields.js").read_text(
        encoding="utf-8"
    )
    tab_content = (WEB_ROOT / "workbench" / "tab-chip-content.js").read_text(
        encoding="utf-8"
    )
    output_choices = (WEB_ROOT / "core" / "output-choices.js").read_text(
        encoding="utf-8"
    )
    generation = (WEB_ROOT / "jobs" / "generation.js").read_text(encoding="utf-8")
    tests = (WEB_ROOT / "workbench" / "tests.js").read_text(encoding="utf-8")
    run_batch = (WEB_ROOT / "workbench" / "test-run-batch.js").read_text(encoding="utf-8")
    groups = (WEB_ROOT / "workbench" / "backtest-groups.js").read_text(encoding="utf-8")
    group_surface = (WEB_ROOT / "workbench" / "configuration-groups" / "common" / "surface.js").read_text(
        encoding="utf-8"
    )

    assert "FTTabChipContent.createSettings" in settings
    assert "function createSettings(options = {})" in tab_content
    assert 'current.className = "test-settings-current"' in tab_content
    assert 'bar.className = options.barClass || "backend-settings-tab-bar"' in tab_content
    assert 'host.className = options.hostClass || "backend-settings-host"' in tab_content
    assert "options.onActivate?.(key)" in tab_content
    assert "FTTabChipContent.create" in settings
    assert 'groupBy: "tab"' in settings
    assert "FTTestSettingChips.render" in groups
    assert "onlyKeys" in groups
    assert "groupOverrideChips" in groups
    assert "content: groupChips" not in groups
    overrides = (WEB_ROOT / "workbench" / "backtest-group-overrides.js").read_text(
        encoding="utf-8"
    )
    assert "FTConfigurationGroupSurface.render" in groups
    assert "FTTabListChip.create" in group_surface
    assert "actionsFor: surfaceKey" in group_surface
    assert "FTTabChipContent.create" in overrides
    assert "backtest-group-tabs" not in groups
    assert "backtest-group-toolbar" not in groups
    assert "backtest-group-override-tabs" not in overrides
    assert 'key: "__manage__"' in settings
    assert 'label: context.t("+ 设置")' in settings
    assert "previewDefaultsForTab" in settings
    assert "includeRun: false" in settings
    assert "includeEmpty: true" in settings
    assert "按顺序完成配置" not in settings
    assert "选择要挂载到测试配置的设置" not in settings
    assert "test-setting-help" not in settings
    assert "test-setting-help" not in run_fields
    assert "诊断选项" not in run_fields
    assert "FTTestOutputs" not in run_fields
    assert "FTTestSettings.controlFor" in run_fields
    assert "tab-chip-description" not in tab_content
    assert "fieldValueSelector" in output_choices
    assert "FTMultiSelectFilter.create" in output_choices
    assert "FTOutputChoices.fieldValueSelector" in generation
    assert "activeTab: state.settingsTabKey" in tests
    assert 'settingsTabKey: null' in tests
    assert 'backtestGroupsOpen: kind === "backtest"' in tests
    assert "installRunToolbar" in tests
    assert "headerActions" in tests
    assert "FTTestRunBatch.render(" not in tests
    assert "产品路径任务" not in tests
    run_batch_model = (WEB_ROOT / "workbench" / "run-batch" / "model.js").read_text(
        encoding="utf-8",
    )
    assert "function jobPath(item)" in run_batch_model
    assert "function runSpecPath(item)" in run_batch_model
    assert "function runSpecTarget(item)" in run_batch_model
    assert 'context.t("查看运行配置")' in run_batch
    assert "FTRunSpecView.openMany" in run_batch
    assert 'invokeAction("runAll"' in run_batch
    assert 'context.t("查看 RunSpec")' not in run_batch
    assert 'context.t("运行")' in run_batch


def test_public_jobs_and_account_navigation_do_not_reuse_stale_page_state() -> None:
    jobs = (WEB_ROOT / "jobs" / "jobs.js").read_text(encoding="utf-8")
    auth = (WEB_ROOT / "app" / "auth.js").read_text(encoding="utf-8")
    coordinator = (WEB_ROOT / "app" / "coordinator.js").read_text(encoding="utf-8")

    assert 'context.navigate(`/jobs?scope=${encodeURIComponent(definition.id)}`)' in jobs
    assert 'new URLSearchParams(location.search).get("scope")' in jobs
    assert "pendingJobScope" not in jobs
    assert 'context.navigate("/settings/account")' in auth
    assert "if (routeToken !== activeRouteToken) return;" in coordinator
    assert 'api("/api/client-assets/revision")' in coordinator
    assert "location.reload();" in coordinator


def test_visitor_language_is_local_while_authenticated_language_is_synced() -> None:
    coordinator = (WEB_ROOT / "app" / "coordinator.js").read_text(
        encoding="utf-8",
    )
    settings = (WEB_ROOT / "settings" / "settings.js").read_text(
        encoding="utf-8",
    )
    catalog = (ROOT / "apple/Resources/Shared/Localizable.xcstrings").read_text(
        encoding="utf-8",
    )

    assert 'const requested = ["system", "zh-Hans", "en"].includes(language)' in coordinator
    assert 'if (state.session) {' in coordinator
    assert 'api("/api/client/preferences"' in coordinator
    assert "Visitor language is deliberately browser-local" in coordinator
    assert 'tabs?.discardView?.("home")' in coordinator
    assert "control.disabled = !context.session" not in settings
    assert "访客模式语言仅保存在当前浏览器，不同步用户账户" in settings
    assert "访客模式语言仅保存在当前浏览器，不同步用户账户" in catalog
    assert "Visitor language is saved only in this browser" in catalog


def test_web_shell_restores_an_http_only_manager_cookie_without_a_saved_token() -> None:
    coordinator = (WEB_ROOT / "app" / "coordinator.js").read_text(
        encoding="utf-8"
    )

    assert "state.token = savedToken();" in coordinator
    assert 'state.session = await api("/api/session")' in coordinator
    assert "if (!state.token) return;" not in coordinator
    assert "const hadSavedToken = Boolean(state.token);" in coordinator
    assert "if (hadSavedToken)" in coordinator


def test_home_renders_server_provided_network_addresses() -> None:
    coordinator = (WEB_ROOT / "app" / "coordinator.js").read_text(encoding="utf-8")

    assert "value.internal_server_addresses" in coordinator
    assert "value.public_server_addresses" in coordinator
    assert '"内网服务器 IP 地址"' in coordinator
    assert '"公网服务器 IP 地址"' in coordinator
    assert 't("无在线内网服务器")' in coordinator
    assert 't("无在线公网服务器")' in coordinator
    assert "value.manager_port" in coordinator
    assert "serverAddressWithPort" in coordinator
    assert "content.append(line)" in coordinator


def test_embedded_authentication_uses_the_native_session_store() -> None:
    auth = (WEB_ROOT / "app" / "auth.js").read_text(encoding="utf-8")
    coordinator = (WEB_ROOT / "app" / "coordinator.js").read_text(encoding="utf-8")
    tabs = (WEB_ROOT / "app" / "tabs.js").read_text(encoding="utf-8")

    assert "factorTesterAuthentication" in auth
    assert 'nativeAuthentication("logout")' in auth
    assert 'nativeAuthentication("session-updated")' in auth
    assert "context.refreshAfterSessionChange()" in auth
    assert "async function refreshAfterSessionChange()" in coordinator
    assert "tabs?.discardViews?.();" in coordinator
    assert "function discardViews()" in tabs
    assert '"home"' in tabs


def test_route_dispatch_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "route_dispatch.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_workbench_factor_selection_seam() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_selection.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_workbench_factor_family_picker_searches_public_and_local_catalogs() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_family_picker.js"
    module = (
        ROOT / "server" / "manager" / "web" / "workbench"
        / "factor-family-picker.js"
    )
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_output_selection_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "output_selection.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_test_run_batch_keeps_runspec_and_job_links_for_ic_and_backtest() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_run_batch.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
    tests_source = (
        ROOT / "server" / "manager" / "web" / "workbench" / "tests.js"
    ).read_text(encoding="utf-8")
    assert "FTTestRunBatch.renderSubmitted" in tests_source


def test_test_run_results_freezes_the_ic_evaluation_matrix() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_run_results.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"

    infrastructure = (
        ROOT / "server" / "manager" / "web" / "test-modules" / "README.md"
    ).read_text(encoding="utf-8")
    assert "tab-chip-content.js" in infrastructure
    assert "resultViewers" in infrastructure
    assert "job-detail-previews" in infrastructure

    batch_source = (
        ROOT / "server" / "manager" / "web" / "workbench" / "test-run-batch.js"
    ).read_text(encoding="utf-8")
    result_source = (
        ROOT / "server" / "manager" / "web" / "workbench" / "test-run-results.js"
    ).read_text(encoding="utf-8")
    assert "item.resultBridgePromise" in batch_source
    assert "item.resultViewerPromise" in result_source
    assert "item.resultCodePromise" not in batch_source
    assert "item.resultCodePromise" not in result_source


def test_test_run_progress_finishes_and_refreshes_terminal_results() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_run_progress.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"

    test_page = (
        ROOT / "server" / "manager" / "web" / "workbench" / "tests.js"
    ).read_text(encoding="utf-8")
    job_page = (
        ROOT / "server" / "manager" / "web" / "jobs" / "detail.js"
    ).read_text(encoding="utf-8")
    assert 'dataset.ftRerenderOnTabRestore = "true"' in test_page
    assert 'dataset.ftRerenderOnTabRestore = "true"' in job_page
    assert "FTTestRunProgress?.suspend" in test_page


def test_manifest_driven_setting_rules_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "setting_rules.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_library_model_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_library_model.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_library_navigation_uses_the_shared_header_switch() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_library_navigation.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_library_product_group_filter_is_searchable_and_not_a_select() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_group_filter.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_shared_action_button_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "shared_action_button.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_create_editors_use_shared_actions_and_personal_factor_scope() -> None:
    editor = (WEB_ROOT / "catalog" / "factor-editor.js").read_text(encoding="utf-8")
    object_form = (WEB_ROOT / "catalog" / "factor-object-form.js").read_text(
        encoding="utf-8",
    )
    set_editor = (WEB_ROOT / "catalog" / "factor-set-editor.js").read_text(
        encoding="utf-8",
    )

    assert 'context.t("上传因子源码")' in editor
    assert 'FTUI.actionButton(context.t("校验源码")' in editor
    assert "FTUI.codeEditor(state.sourceCode" in editor
    assert "registered = libraryValue.factors?.[0] || null" in editor
    assert "frozen Factor v2 identity" in editor
    assert "factor-editor-upload-action" not in editor
    assert 'FTUI.actionButton(context.t("取消编辑")' in editor
    assert 'mode === "create" ? "提交" : "保存"' in editor
    assert 'if (mode === "edit") context.toolbar.append(cancelEdit)' in editor
    assert 'context.toolbar.append(submit)' in editor
    assert 'source: {save_mode: "auto"}' in editor
    assert 'await validateSourceDraft()' in editor
    assert 'object-detail-tab-change' in editor
    assert "familyClassNameMatches(name.value, state.inspection)" in editor
    assert 'form.append(topMount, tabs.root, status)' in editor
    assert "FTUI.actionButton(" in object_form
    assert 'if (definition.mode === "edit") context.toolbar.append(cancelEdit)' in object_form
    assert 'form.append(tabs.root, status)' in object_form
    assert "familyScopes?.mine" in set_editor
    assert "mine?.factors" in set_editor
    assert 'context.api("/api/factor-library/factor-sets"' in set_editor
    assert "/custom-factors/api/client/factor-sets" not in set_editor
    assert "FTFactorSetAssistance" in set_editor


def test_factor_assistance_applies_documents_without_a_dom_event() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_assistance_apply.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_persistent_factor_save_refreshes_catalog_but_inline_save_does_not() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_persistence_refresh.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
    editor = (WEB_ROOT / "catalog" / "factor-editor.js").read_text(encoding="utf-8")
    assert "if (!state.familyMode)" in editor
    assert "params_list: [state.parameterValues]" in editor


def test_factor_object_editors_share_submit_assistance_and_reference_controls() -> None:
    object_form = (WEB_ROOT / "catalog" / "factor-object-form.js").read_text(
        encoding="utf-8",
    )
    set_editor = (WEB_ROOT / "catalog" / "factor-set-editor.js").read_text(
        encoding="utf-8",
    )
    editor = (WEB_ROOT / "catalog" / "factor-editor.js").read_text(
        encoding="utf-8",
    )
    parameter_editor = (WEB_ROOT / "catalog" / "factor-parameter-editor.js").read_text(
        encoding="utf-8",
    )
    detail_shared = (WEB_ROOT / "catalog" / "factor-detail-shared.js").read_text(
        encoding="utf-8",
    )
    app_css = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")

    assert "context.toolbar.append(save)" in object_form
    assert "submit: save" in object_form
    assert object_form.index("context.setHeading") < object_form.index(
        "context.toolbar.append(save)",
    )
    assert "editor.syncFromState()" in set_editor
    assert 'parameter.type === "FactorParam"' in parameter_editor
    assert '"新增因子家族"' in parameter_editor
    assert "factor-param-choice-disabled" not in parameter_editor
    assert "factor-param-reference-control" in parameter_editor
    assert 'input.placeholder = context.t("填写")' in parameter_editor
    # The parameter table is the shared single-grid component: the editor
    # container owns the tracks and header/rows subgrid them (one shared
    # column layout per table), with the parameter list shared via
    # createParameterList and the section shell shared via parameterSection.
    assert "FTFactorDetailShared.createParameterList" in parameter_editor
    assert "FTFactorDetailShared.parameterSection" in editor
    assert 'header.className = "factor-detail-parameter-header"' in detail_shared
    assert '["参数名", "参数类型", "默认值", "Value"]' in detail_shared
    assert 'context.t("Column")' in parameter_editor
    assert ".factor-detail-parameter-editor > .factor-detail-parameter-row" in app_css
    assert "grid-template-columns: subgrid" in app_css
    assert "grid-template-columns: minmax(70px, max-content)" in app_css
    assert ".factor-param-reference-control { display: grid; grid-template-columns: max-content" in app_css
    assert "font-family: ui-monospace, SFMono-Regular" in app_css
    assert "function numericConstant" in parameter_editor
    assert 'setValue(constant, "manual")' in parameter_editor
    assert "请输入有效的 ColumnRef 或因子 alias" in parameter_editor
    assert "onValidateFactorAlias" in parameter_editor
    assert "factor-param-column-" in parameter_editor
    assert "factor-param-factor-" in parameter_editor
    assert "factor-param-family-source" in parameter_editor
    assert "factor-param-nested-factor-mount" in parameter_editor
    assert "FTFactorDetailShared.parameterSection" in parameter_editor
    assert 'method: "POST"' in editor
    assert "resolve_factor_alias" in editor
    assert "onChange: nextValues =>" in editor
    assert "state.parameterValues = {...nextValues}" in editor
    assert "FTObjectOverlay.open" in editor
    assert "factor-source-mode" not in editor
    assert '"新增因子家族"' in editor
    assert 'state.family.source_kind === "transient"' in editor
    assert "factor-param-choice-family" not in parameter_editor
    assert "compact: true, multi: false" in parameter_editor
    assert "align-items: center" in app_css
    assert "min-height: 34px" in app_css
    assert "state.onInspected?.(state.inspection)" in editor
    assert "name.value = inspection.factor_name" not in editor
    assert "familyClassNameMatches(name.value, state.inspection)" in editor
    assert 'readOnly: mode === "edit"' in editor


def test_factor_parameter_picker_preserves_frozen_nested_factor_records() -> None:
    fixture = (
        ROOT / "tests" / "scripts" / "fixtures"
        / "factor_parameter_frozen_selection.js"
    )
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_factor_parameter_picker_enriches_nested_family_metadata_and_preview() -> None:
    fixture = (
        ROOT / "tests" / "scripts" / "fixtures"
        / "factor_nested_selection.js"
    )
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_family_drafts_materialize_recursively_without_library_write() -> None:
    fixture = (
        ROOT / "tests" / "scripts" / "fixtures"
        / "factor_family_draft_materialization.js"
    )
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_library_lists_original_class_name_and_description_columns() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_library_listing.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_factor_details_render_latex_and_factor_set_members_open() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_detail_links.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
    # Family view must render test-local families from their carried frozen
    # value: no catalog round-trip for current source, no server version
    # history picker.  (Family header "?" opens the family view overlay for
    # both library and freshly created families.)
    details = (WEB_ROOT / "catalog" / "factor-details.js").read_text(
        encoding="utf-8"
    )
    assert "testObjectInitialValue" in details
    assert "localView" in details
    assert "canSelectVersion" in details
    assert "withCurrentFamilySource" in details


def test_factor_detail_route_declares_katex_runtime_dependency() -> None:
    import json

    manifest = json.loads(
        (ROOT / "server" / "manager" / "web" / "module-manifest.json")
        .read_text(encoding="utf-8")
    )
    assert manifest["route_groups"]["factor-family"] == [
        "factor-catalog-detail-rendering",
    ]
    assert manifest["route_groups"]["factor"] == [
        "factor-catalog-detail-rendering",
    ]
    assert manifest["route_groups"]["factor-set"] == ["factor-catalog-detail"]
    assert manifest["group_dependencies"]["factor-catalog-detail"] == [
        "factor-catalog-core",
        "factor-catalog-enrichment",
    ]
    assert "factor-catalog-list" not in manifest["group_dependencies"][
        "factor-catalog-detail"
    ]
    assert "katex/katex.min.js" in manifest["group_external_scripts"][
        "factor-catalog-detail-rendering"
    ]
    assert "vendor/highlight/highlight.min.js" in manifest[
        "group_external_scripts"
    ]["factor-catalog-detail-rendering"]


def test_test_object_overlay_loads_the_detail_group_before_first_factor_chip() -> None:
    overlay = (
        ROOT / "server" / "manager" / "web" / "workbench"
        / "object-overlay.js"
    ).read_text(encoding="utf-8")
    factors = (
        ROOT / "server" / "manager" / "web" / "catalog" / "factors.js"
    ).read_text(encoding="utf-8")
    icons = (
        ROOT / "server" / "manager" / "web" / "core" / "icons.js"
    ).read_text(encoding="utf-8")

    assert 'load: "factor-catalog-detail-rendering"' in overlay
    assert 'load: "factor-catalog-detail"' in overlay
    assert "const loadedGroups = new Set()" in overlay
    assert "loadedGroups.has(frameDefinition.load)" in overlay
    assert "window.FTFactorDetails.factorDetail(" in factors
    assert "window.FTFactorDetails.familyDetail(" in factors
    assert "window.FTFactorDetails.setDetail(" in factors
    assert '"xmark":' in icons
    assert '"chevron.left":' in icons
    assert 'FTIcons?.node?.("xmark")' in overlay
    assert '"triangle.down" : "triangle.right"' in overlay
    assert '"triangle.right":' in icons


def test_factor_catalog_list_defers_auxiliary_catalogs_and_heavy_modules() -> None:
    import json

    manifest = json.loads(
        (ROOT / "server" / "manager" / "web" / "module-manifest.json")
        .read_text(encoding="utf-8")
    )
    factor_list = (
        ROOT / "server" / "manager" / "web" / "catalog" / "factor-list.js"
    ).read_text(encoding="utf-8")
    catalog_list = (
        ROOT / "server" / "manager" / "web" / "catalog"
        / "factor-catalog-list.js"
    ).read_text(encoding="utf-8")
    runtime = (
        ROOT / "server" / "manager" / "web" / "catalog"
        / "factor-catalog-runtime.js"
    ).read_text(encoding="utf-8")

    assert manifest["route_groups"]["factor-families"] == ["factor-catalog-list"]
    assert manifest["route_groups"]["factors"] == ["factor-catalog-list"]
    assert manifest["group_external_scripts"].get("factor-catalog-list", []) == []
    assert "core/highcharts-range-loader.js" not in manifest["groups"]["factor-catalog-list"]
    assert "catalog/products.js" not in manifest["groups"]["factor-catalog-list"]
    assert 'library: page !== "sets"' in catalog_list
    assert 'sets: page === "sets"' in catalog_list
    assert 'groups: true, library: page !== "sets"' in catalog_list
    assert "onOpen: () =>" in catalog_list
    assert "/api/product-library/product-groups" in runtime
    assert 'context.api("/api/factor-library/factor-sets")' in runtime
    sets_start = runtime.index("async function loadSets(context)")
    groups_start = runtime.index("async function loadGroups(context)")
    assert "loadLibrary(context)" not in runtime[sets_start:groups_start]
    assert "model().subjectGroups(data.groups)" in factor_list


def test_factor_catalog_runtime_loads_only_requested_sources() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_catalog_runtime.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_product_group_detail_never_uses_retired_business_route() -> None:
    detail = (
        WEB_ROOT / "catalog" / "product-group-detail.js"
    ).read_text(encoding="utf-8")

    assert '"/api/client/product-groups"' in detail
    assert '"/api/product-library/product-groups"' in detail
    assert '"/api/product-groups"' not in detail
