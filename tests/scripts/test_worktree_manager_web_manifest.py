"""Contracts for the static Web renderer module manifest."""

from __future__ import annotations

import json
from pathlib import Path

from server.manager.web import assets as research_static
from server.manager.web.assets import asset_revision, shell_bytes, static_file


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "server" / "manager" / "web"


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
    assert manifest["external_styles"] == ["katex/katex.min.css"]
    assert manifest["styles"] == [
        "styles/app.css", "styles/report.css", "styles/outputs/artifacts.css",
        "styles/outputs/backtest-results.css",
        "styles/workbench.css", "styles/workbench-settings.css",
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
    assert set(initial_scripts).issubset(set(manifest["scripts"]))
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
    result = subprocess.run(
        ["node", str(fixture), str(compiler)], cwd=ROOT,
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


def test_factor_set_selection_freezes_descriptor_and_local_sources() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_set_selection.js"
    modules = [
        WEB_ROOT / "catalog" / "factor-model.js",
        WEB_ROOT / "workbench" / "factor-selection.js",
        WEB_ROOT / "workbench" / "factor-set-selection.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(item) for item in modules)], cwd=ROOT,
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
    assert '/api/backtest/settings/group_test' in settings
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

    assert "vendor/highcharts/highstock.min.js" in manifest["group_external_scripts"]["job-detail-previews"]
    assert "vendor/highcharts/highstock.min.js" in manifest["group_external_scripts"]["job-detail-ic"]
    assert "vendor/highcharts/highstock.min.js" in manifest["group_external_scripts"]["job-detail-backtest"]
    assert manifest["route_groups"]["jobs"] == ["jobs"]
    assert manifest["route_groups"]["job"] == ["job-detail-core"]
    assert manifest["route_groups"]["job-configuration"] == ["job-detail-core"]
    assert manifest["route_groups"]["job-input"] == ["job-detail-input"]
    assert manifest["route_groups"]["ic-test"] == ["workbench-test-ui"]
    assert manifest["route_groups"]["backtest"] == [
        "workbench-test-ui", "workbench-backtest",
    ]
    assert manifest["route_groups"]["factor-evaluation"] == ["workbench-test-ui"]
    assert manifest["route_groups"]["factor-series"] == ["workbench-core"]
    assert manifest["route_groups"]["product-categories"] == ["catalog"]
    assert manifest["group_dependencies"]["research"] == [
        "report", "profile", "catalog-core",
    ]
    assert set(manifest["groups"]["jobs"]) == {
        "jobs/list-format.js", "jobs/progress.js", "jobs/page-tabs.js",
        "jobs/test-types.js", "jobs/jobs.js",
    }
    assert "jobs/detail.js" in manifest["groups"]["job-detail-core"]
    assert "jobs/input-detail.js" in manifest["groups"]["job-detail-input"]
    assert "jobs/highcharts-viewers.js" in manifest["groups"]["job-detail-previews"]
    assert "jobs/job-artifact-viewers.js" in manifest["groups"]["job-detail-previews"]
    assert "jobs/ic-result-view.js" in manifest["groups"]["job-detail-ic"]
    assert "jobs/backtest-result-view.js" in manifest["groups"]["job-detail-backtest"]
    assert "jobs/factor-series-view.js" in manifest["groups"]["job-detail-factor-series"]
    assert manifest["group_dependencies"]["job-detail-previews"] == [
        "job-detail-core", "report", "charts",
    ]
    assert "output-choice" in manifest["group_dependencies"]["job-detail-core"]
    core_detail = set(manifest["groups"]["job-detail-core"])
    assert "jobs/detail.js" in core_detail
    assert not core_detail.intersection({
        "jobs/highcharts-viewers.js", "jobs/job-artifact-viewers.js",
        "jobs/ic-result-view.js", "jobs/backtest-result-view.js",
        "jobs/factor-series-view.js", "core/market-data.js",
    })
    artifacts = (WEB_ROOT / "jobs" / "artifacts.js").read_text(encoding="utf-8")
    detail = (WEB_ROOT / "jobs" / "detail.js").read_text(encoding="utf-8")
    run_results = (WEB_ROOT / "workbench" / "test-run-results.js").read_text(encoding="utf-8")
    assert 'loadGroups?.(["job-detail-previews"])' in artifacts
    assert 'loadGroups?.([group])' in detail
    assert 'loadGroups?.(["job-detail"])' not in run_results
    assert 'job-detail-ic' in run_results and 'job-detail-backtest' in run_results
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


def test_product_price_chart_is_interactive_ohlcv() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "interactive_price_chart.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


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
        WEB_ROOT / "jobs" / "ic-result-model.js",
        WEB_ROOT / "jobs" / "ic-result-charts.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(path) for path in files)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


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
    assert "FTFactorDetailShared.parameterEditor" in source
    assert "factor-editor-source-metadata" in source
    assert "test-factor-family-row" not in source


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
    assert ".test-object-editor-dialog > .test-object-editor-overlay" in styles
    assert ".test-object-editor-overlay-mount > .detail-stack" in styles


def test_dialog_cards_have_shared_viewport_scroll_fallback() -> None:
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")
    dialog_rule = styles.split(".dialog-card {", 1)[1].split("}", 1)[0]
    run_spec_rule = styles.split(".run-spec-dialog-card {", 1)[1].split("}", 1)[0]
    assert "max-height: calc(100dvh - 32px)" in dialog_rule
    assert "overflow-y: auto" in dialog_rule
    assert "overscroll-behavior: contain" in dialog_rule
    assert "overflow: hidden" not in run_spec_rule


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
    assert "/api/backtest/settings/${application}/summary" in first_load
    assert "/api/backtest/settings/${application}`" not in first_load
    for endpoint in (
        "/api/catalog/factors", "/api/catalog/product-groups",
        "/api/data_source_categories", "/api/configuration-templates",
        "/api/jobs/artifact-capabilities", "/api/client/profiles",
    ):
        assert endpoint not in first_load
    assert "/api/workspace-summaries" in first_load
    assert "workbench-settings" not in first_load
    assert "FTTestInputState.initialize" not in first_load
    assert "FTTestState.initializeInputState(state)" in source
    assert "/api/workspaces/${workspaceID}/configuration" in source
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
        "workbench-settings", "workbench-settings-fields",
        "workbench-settings-chips", "workbench-ic-controls",
        "workbench-factor-controls", "workbench-product-controls",
        "workbench-factors", "workbench-products", "workbench-templates",
        "workbench-run",
    ]
    assert manifest["group_dependencies"]["workbench-input-state"] == [
        "workbench-core",
    ]
    assert manifest["group_dependencies"]["workbench-core"] == []
    assert "workbench/templates/actions.js" in manifest["groups"]["workbench-core"]
    assert "workbench/templates/actions.js" not in manifest["groups"]["workbench-templates"]
    assert "output-choice" not in manifest["group_dependencies"]["workbench-core"]
    assert "core/output-choices.js" not in research_static._initial_scripts(manifest)
    assert manifest["group_dependencies"]["workbench-compiler"] == ["core"]
    assert manifest["group_dependencies"]["workbench-run-batch"] == ["workbench-core"]
    assert manifest["group_dependencies"]["workbench-run-batch-actions"] == [
        "workbench-run-batch", "workbench-input-state", "workbench-run-submit",
    ]
    assert manifest["group_dependencies"]["workbench-run-results"] == [
        "workbench-run", "jobs",
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
    ]
    assert manifest["group_dependencies"]["workbench-source-inputs"] == [
        "workbench-input-state",
    ]
    assert "workbench/tab-list-chip.js" in manifest["groups"]["workbench-backtest"]
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
        "workbench-settings", "workbench-settings-controls",
        "workbench-products", "workbench-factors",
    ]
    assert manifest["group_dependencies"]["workbench-run-submit"] == [
        "workbench-run", "workbench-compiler", "workbench-ic-controls",
    ]
    assert manifest["group_dependencies"]["workbench-ic-controls"] == [
        "workbench-core", "workbench-compiler",
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

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_result_model.js"
    model = WEB_ROOT / "jobs" / "backtest-result-model.js"
    runtime = WEB_ROOT / "jobs" / "backtest-runtime-model.js"
    result = subprocess.run(
        ["node", str(fixture), str(model), str(runtime)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backtest_result_view_only_claims_recognized_active_artifacts() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_result_view.js"
    view = WEB_ROOT / "jobs" / "backtest-result-view.js"
    result = subprocess.run(
        ["node", str(fixture), str(view)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_backtest_analysis_api_uses_job_scoped_manager_routes() -> None:
    import subprocess

    module = ROOT / "server" / "manager" / "web" / "jobs" / "backtest-analysis-api.js"
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_analysis_api.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_backtest_group_detail_restores_fee_rules_and_intraday_windows() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_group_detail_parts.js"
    detail = (WEB_ROOT / "jobs" / "backtest-group-detail.js").read_text(encoding="utf-8")
    assert "FTBacktestGroupDetailProducts" in detail
    modules = [
        WEB_ROOT / "jobs" / "backtest-group-products.js",
        WEB_ROOT / "jobs" / "backtest-group-detail-parts.js",
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
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
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
    assert "height: max-content" in styles
    assert ".ft-multi-select-options" in styles
    assert 'menuClass: "factor-product-group-filter-menu"' in factor_filter


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
    report_view = (WEB_ROOT / "report" / "component-view.js").read_text(
        encoding="utf-8"
    )
    styles = (WEB_ROOT / "styles" / "app.css").read_text(encoding="utf-8")

    assert 'pre.className = "json-code"' in shared_ui
    assert "function isJSONCode(component, content)" in report_view
    assert "JSON.parse(source)" in report_view
    assert 'isJSONCode(component, content) ? "json-code"' in report_view
    assert ".json-code" in styles
    assert "max-height:" in styles.split(".json-code", 1)[1].split("}", 1)[0]
    assert "overflow: auto" in styles.split(".json-code", 1)[1].split("}", 1)[0]


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
    detail_page, configuration_page = detail.split(
        "async function configuration", 1
    )

    assert 'context.t("查看运行配置")' in detail_page
    assert "FTRunSpecView.open(context, runSpec.target, runSpec.serverID)" in detail_page
    assert 'context.t("结果预览")' in detail_page
    assert "function lazyConfigurationPreview(context, configuration)" in detail_page
    assert 'context.t("运行配置摘要")' in detail_page
    assert 'details.addEventListener("toggle"' in detail_page
    assert "root.append(lazyConfigurationPreview" in detail_page
    assert "FTReferencePage.render(context" in configuration_page
    assert 'kind: "run-spec"' in configuration_page
    assert 'context.t("结果预览")' not in configuration_page
    assert "FTJobArtifacts.lazyArtifactPreview" not in configuration_page


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
    assert "FTTabListChip.create" in groups
    assert "actionsFor: surfaceKey" in groups
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


def test_test_run_progress_finishes_and_refreshes_terminal_results() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_run_progress.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


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
