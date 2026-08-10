"""Contracts for the static Web renderer module manifest."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.worktree_manager_research as research_static
from scripts.worktree_manager_research import asset_revision, shell_bytes, static_file


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "scripts" / "worktree_manager_web"


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
        "styles/app.css", "styles/report.css", "styles/outputs.css",
        "styles/workbench.css",
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


def test_job_result_charts_use_interactive_highcharts_data() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "interactive_job_charts.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"

    styles = (WEB_ROOT / "styles" / "outputs.css").read_text(encoding="utf-8")
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


def test_job_detail_and_test_configuration_are_independent_pages() -> None:
    detail = (WEB_ROOT / "jobs" / "detail.js").read_text(encoding="utf-8")
    detail_page, configuration_page = detail.split(
        "async function configuration", 1
    )

    assert 'context.t("查看测试配置")' in detail_page
    assert "/configuration" in detail_page
    assert 'context.t("结果预览")' in detail_page
    assert 'context.t("具体测试配置")' not in detail_page
    assert "function lazyConfigurationPreview(context, configuration)" in detail_page
    assert 'context.t("测试配置")' in detail_page
    assert 'details.addEventListener("toggle"' in detail_page
    assert "root.append(lazyConfigurationPreview" in detail_page
    assert 'context.t("具体测试配置")' in configuration_page
    assert 'context.t("返回任务详情")' in configuration_page
    assert 'context.t("结果预览")' not in configuration_page
    assert "FTJobArtifacts.lazyArtifactPreview" not in configuration_page


def test_test_configuration_uses_a_tabbed_settings_page() -> None:
    settings = (WEB_ROOT / "workbench" / "test-settings.js").read_text(encoding="utf-8")
    tests = (WEB_ROOT / "workbench" / "tests.js").read_text(encoding="utf-8")

    assert 'root.className = "backend-settings-shell test-settings-shell"' in settings
    assert 'bar.className = "backend-settings-tab-bar"' in settings
    assert 'host.className = "backend-settings-host"' in settings
    assert "options.onTabChange?.(item.tab.key)" in settings
    assert "activeTab: state.settingsTabKey" in tests
    assert 'context.navigate(`/jobs/${value.port}/' in tests


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


def test_output_selection_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "output_selection.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_ic_multi_product_run_batch_keeps_runspec_and_job_links() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "ic_run_batch.js"
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
