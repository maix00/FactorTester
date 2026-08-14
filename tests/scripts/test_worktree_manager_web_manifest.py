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
    assert architecture["max_script_lines"] == 400
    assert architecture["max_style_lines"] == 500
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
    assert script_paths == [*manifest["external_scripts"], *manifest["scripts"]]
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

    script_lines = {
        relative: len((WEB_ROOT / relative).read_text(encoding="utf-8").splitlines())
        for relative in manifest["scripts"]
    }
    assert max(script_lines.values()) <= architecture["max_script_lines"], script_lines
    style_lines = {
        relative: len((WEB_ROOT / relative).read_text(encoding="utf-8").splitlines())
        for relative in manifest["styles"]
    }
    assert max(style_lines.values()) <= architecture["max_style_lines"], style_lines


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


def test_pinned_feature_and_detail_tabs_have_stable_ownership() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "product_tabs.js"
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
    source = WEB_ROOT / "workbench" / "test-source-upload.js"
    result = subprocess.run(
        ["node", str(fixture), str(source)], cwd=ROOT,
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
    assert 'FTTestRunFields.field(manifest, "service_port")' in settings


def test_every_registered_test_setting_has_an_explicit_web_control(tmp_path) -> None:
    import subprocess

    from tools.testers.settings import backtest_setting_registry

    registered = sorted({
        field["control_template"]
        for application in ("ic_test", "group_test")
        for field in backtest_setting_registry.get(application).manifest()["defaults"].values()
    })
    expected = tmp_path / "registered-controls.json"
    expected.write_text(json.dumps(registered), encoding="utf-8")
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_setting_control_contract.js"
    module = WEB_ROOT / "workbench" / "test-settings.js"
    result = subprocess.run(
        ["node", str(fixture), str(module), str(expected)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_research_shell_loads_the_owned_highstock_runtime() -> None:
    shell = research_static.shell_bytes().decode("utf-8")

    assert '/research-static/vendor/highcharts/highstock.min.js?v=' in shell


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
        WEB_ROOT / "workbench" / "test-settings.js",
    ]
    result = subprocess.run(
        ["node", str(fixture), *(str(path) for path in files)], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


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


def test_backtest_result_model_reconstructs_persisted_domain_outputs() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "backtest_result_model.js"
    model = WEB_ROOT / "jobs" / "backtest-result-model.js"
    result = subprocess.run(
        ["node", str(fixture), str(model)], cwd=ROOT,
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
    module = WEB_ROOT / "jobs" / "backtest-group-detail-parts.js"
    result = subprocess.run(
        ["node", str(fixture), str(module)], cwd=ROOT,
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


def test_backtest_group_form_uses_registered_override_editor() -> None:
    form = (WEB_ROOT / "workbench" / "backtest-group-form.js").read_text(
        encoding="utf-8"
    )

    assert "FTBacktestGroupOverrides.render" in form
    assert "overrides.value()" in form
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


def test_job_detail_uses_the_shared_run_spec_view() -> None:
    detail = (WEB_ROOT / "jobs" / "detail.js").read_text(encoding="utf-8")
    detail_page, configuration_page = detail.split(
        "async function configuration", 1
    )

    assert 'context.t("查看运行配置")' in detail_page
    assert "FTRunSpecView.open(context, runSpec.target)" in detail_page
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
    test_outputs = (WEB_ROOT / "workbench" / "test-outputs.js").read_text(
        encoding="utf-8"
    )
    generation = (WEB_ROOT / "jobs" / "generation.js").read_text(encoding="utf-8")
    tests = (WEB_ROOT / "workbench" / "tests.js").read_text(encoding="utf-8")
    run_batch = (WEB_ROOT / "workbench" / "test-run-batch.js").read_text(encoding="utf-8")
    groups = (WEB_ROOT / "workbench" / "backtest-groups.js").read_text(encoding="utf-8")

    assert 'root.className = "backend-settings-shell test-settings-shell"' in settings
    assert 'bar.className = options.barClass || "backend-settings-tab-bar"' in tab_content
    assert 'host.className = options.hostClass || "backend-settings-host"' in tab_content
    assert "options.onActivate?.(key)" in tab_content
    assert "FTTabChipContent.create" in settings
    assert 'groupBy: "tab"' in settings
    assert 'groupBy: "tab"' in groups
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
    assert "tab-chip-description" not in tab_content
    assert "fieldValueSelector" in output_choices
    assert "FTOutputChoices.fieldValueSelector" in test_outputs
    assert "FTOutputChoices.fieldValueSelector" in generation
    assert "activeTab: state.settingsTabKey" in tests
    assert "FTTestRunBatch.render" in tests
    assert "function jobPath(item)" in run_batch
    assert "function runSpecPath(item)" in run_batch
    assert '"查看运行配置", runSpecPath(item)' in run_batch


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

    assert "factorTesterAuthentication" in auth
    assert 'nativeAuthentication("open")' in auth
    assert 'nativeAuthentication("logout")' in auth


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


def test_test_run_results_freezes_the_ic_evaluation_matrix() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "test_run_results.js"
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
