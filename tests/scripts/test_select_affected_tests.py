from pathlib import Path
import subprocess

from scripts import select_affected_tests as selector


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def test_known_module_selects_cross_module_consumers():
    mode, targets = selector.select({"tools/cli/release/research_reporting/tree.py"})
    assert mode == "SCOPED"
    assert "tests/cli" in targets
    assert "tests/release" in targets
    assert "tests/server" in targets


def test_skill_change_checks_activation_and_skill_tests():
    assert selector.select({"skills/factortester-research-skill/SKILL.md"}) == (
        "SCOPED",
        ["tests/release/test_bundled_runtime_activation.py", "tests/skills"],
    )


def test_shared_and_unclassified_paths_fail_closed():
    assert selector.select({"environment.yml"}) == ("FULL", [])
    assert selector.select({"tools/parameters/base.py"}) == ("FULL", [])
    assert selector.select({"tools/cli/app.py", "mystery/new.py"}) == ("FULL", [])


def test_docs_only_skips_and_deleted_test_falls_back_to_module():
    assert selector.select({"docs/adr/new.md"}) == ("SKIP", [])
    assert selector.select({"tests/scripts/support.py"}) == ("SCOPED", ["tests/scripts"])
    assert selector.select({"tests/server/test_nonexistent_deleted.py"}) == (
        "SCOPED", ["tests/server"],
    )


def test_rename_considers_both_paths():
    paths = selector.paths_from_name_status(
        b"R100\0tools/cli/old.py\0tools/parameters/new.py\0"
    )
    assert paths == {"tools/cli/old.py", "tools/parameters/new.py"}
    assert selector.select(paths) == ("FULL", [])


def test_js_only_change_has_no_python_target():
    assert selector.select({"tests/js/test_report_export.js"}) == (
        "SCOPED", ["tests/js/test_report_export.js"],
    )


def test_mixed_python_and_js_change_selects_both_runners():
    mode, targets = selector.select({"tools/cli/app.py", "tests/js/test_report_export.js"})
    assert mode == "SCOPED"
    assert "tests/cli" in targets
    assert "tests/js/test_report_export.js" in targets
    assert all((selector.ROOT / path).exists() for path in targets)


def test_unmapped_server_change_fails_closed_instead_of_expanding_to_many_suites():
    assert selector.select({"server/manager/web/report/report.js"}) == ("FULL", [])


def test_versioning_and_strategy_change_selects_only_direct_domain_tests():
    paths = {
        "server/services/versioning/revisions.py",
        "server/manager/storage/account_domain/strategy_sync.py",
        "server/services/strategy_plans.py",
        "tools/data/sqlite/account_manager/product_group.py",
    }
    mode, targets = selector.select(paths)
    assert mode == "SCOPED"
    assert set(targets) == {
        "tests/server/test_versioning_revisions.py",
        "tests/server/test_strategy_catalog_sync.py",
        "tests/server/test_strategy_plans.py",
        "tests/products/test_product_group_revisions.py",
        "tests/products/test_product_group_subjects.py",
        "tests/server/test_manager_catalog_product_group_write.py",
    }
    assert len(targets) == 6
    assert all((selector.ROOT / path.split("::", 1)[0]).is_file() for path in targets)


def test_js_runner_change_checks_conda_playwright_module_resolution():
    assert selector.select({"scripts/test_js.sh"}) == (
        "SCOPED", ["tests/js/test_playwright_runtime.js"],
    )


def test_strategy_web_edits_select_individual_contract_tests():
    mode, targets = selector.select({
        "server/manager/web/catalog/strategy-library-list.js",
        "server/manager/web/catalog/strategy-library-runtime.js",
        "server/manager/http/strategy_library_routes.py",
    })
    assert mode == "SCOPED"
    assert set(targets) == {
        "tests/scripts/test_worktree_manager_web_manifest.py::test_strategy_list_keeps_compact_batch_and_inline_name_interactions",
        "tests/scripts/test_worktree_manager_web_manifest.py::test_strategy_binding_panel_only_routes_library_strategies_to_venues",
        "tests/scripts/test_worktree_manager_client_app.py::test_strategy_library_patch_uses_manager_application_route",
        "tests/server/test_strategy_library.py",
    }


def test_nautilus_run_spec_and_source_ui_select_focused_tests():
    mode, targets = selector.select({
        "server/services/nautilus_bridge/config.py",
        "server/services/nautilus_bridge/native_configuration.py",
        "server/services/nautilus_bridge/engine_factory.py",
        "server/services/nautilus_bridge/source_registry.py",
        "server/services/nautilus_bridge/capabilities.py",
        "server/services/product_catalog_projection.py",
        "server/manager/web/catalog/source-list.js",
        "server/manager/web/catalog/source-family-detail.js",
        "server/manager/web/workbench/object-overlay.js",
        "server/manager/web/styles/app.css",
        "server/manager/http/job_proxy_routes.py",
        "tests/nautilus_source_fixture.py",
        "tests/scripts/fixtures/nautilus_source_overlay.js",
        "sources/LocalCNFutures/CNFutures.py",
        "sources/LocalCNFutures/nautilus_adapter.py",
        "sources/registry.py",
        "tools/data/source_catalog.py",
        "tools/data/providers/DataProviderProductTS.py",
    })
    assert mode == "SCOPED"
    assert set(targets) == {
        "tests/server/test_nautilus_bridge_config.py",
        "tests/server/test_nautilus_native_configuration_contract.py",
        "tests/server/test_nautilus_bridge_engine_factory.py",
        "tests/server/test_nautilus_source_capabilities.py",
        "tests/server/test_nautilus_source_registry.py",
        "tests/server/test_nautilus_source_declarations.py",
        "tests/products/test_product_source_projection.py",
        "tests/scripts/test_nautilus_source_overlay.py",
        "tests/server/test_nautilus_preview_routes.py",
    }
    assert all((selector.ROOT / path).is_file() for path in targets)


def test_nautilus_execution_bridge_selects_only_its_focused_tests():
    paths = {
        "server/services/nautilus_bridge/market_data.py",
        "server/services/nautilus_bridge/catalog.py",
        "tests/benchmarks/bench_nautilus_catalog_staging.py",
        "server/services/nautilus_bridge/backtest_runner.py",
        "server/services/nautilus_bridge/factor_stream.py",
        "server/services/nautilus_bridge/rule_transition.py",
        "server/services/nautilus_bridge/reports.py",
        "server/services/nautilus_bridge/historical_fees.py",
        "server/services/nautilus_bridge/trading_fields.py",
        "server/services/nautilus_bridge/run_spec.py",
        "server/services/nautilus_bridge/venues.py",
        "server/services/research_run_identity.py",
        "server/services/research_runs.py",
        "server/modules/single_factor_test/research_jobs.py",
        "server/modules/single_factor_test/backtest_jobs.py",
        "server/modules/single_factor_test/process_runners.py",
        "server/modules/single_factor_test/group.py",
        "server/jobs/repository/queries.py",
        "server/jobs/scheduling/daemon.py",
        "server/services/nautilus_bridge/position_offsets.py",
    }
    mode, targets = selector.select(paths)
    assert mode == "SCOPED"
    assert set(targets) == {
        "tests/server/test_nautilus_bridge_data_contract.py",
        "tests/server/test_nautilus_bridge_historical_rule_events.py",
        "tests/server/test_nautilus_bridge_catalog.py",
        "tests/server/test_nautilus_bridge_backtest_runner.py",
        "tests/server/test_nautilus_bridge_reports.py",
        "tests/server/test_nautilus_bridge_factor_stream.py",
        "tests/server/test_nautilus_bridge_rule_transition.py",
        "tests/server/test_nautilus_bridge_historical_fees.py",
        "tests/server/test_nautilus_bridge_trading_fields.py",
        "tests/server/test_nautilus_bridge_run_spec.py",
        "tests/server/test_research_runspec_field_contract.py",
        "tests/server/test_nautilus_bridge_engine_factory.py",
        "tests/server/test_research_run_sample_use.py",
        "tests/server/test_research_job_lifecycle.py",
        "tests/server/test_research_job_scheduler.py",
        "tests/server/test_group_research_run_module.py",
        "tests/server/test_nautilus_bridge_position_offsets.py",
    }
    assert all((selector.ROOT / path).is_file() for path in targets)


def test_nautilus_runspec_freezing_and_preview_select_focused_tests():
    mode, targets = selector.select({
        "server/modules/shared/run_spec_resolution/freezing.py",
        "server/modules/nautilus_workbench/__init__.py",
        "server/services/nautilus_bridge/run_spec.py",
        "server/services/nautilus_bridge/venues.py",
    })
    assert mode == "SCOPED"
    assert set(targets) == {
        "tests/server/test_nautilus_bridge_run_spec.py",
        "tests/server/test_research_runspec_field_contract.py",
        "tests/server/test_strategy_plans.py",
        "tests/server/test_nautilus_manager_preview.py",
        "tests/server/test_nautilus_bridge_engine_factory.py",
    }
    assert all((selector.ROOT / path).is_file() for path in targets)


def test_nautilus_strategy_review_report_and_trading_ui_select_focused_tests():
    mode, targets = selector.select({
        "server/manager/web/workbench/backtest-group-form.js",
        "server/manager/web/workbench/backtest-groups.js",
        "server/manager/web/workbench/strategy-binding-panel.js",
        "server/manager/web/workbench/nautilus-configuration.js",
        "server/manager/web/workbench/test-settings.js",
        "server/manager/web/workbench/test-configuration.js",
        "server/manager/web/app/route-dispatch.js",
        "server/manager/web/module-manifest.json",
        "server/manager/web/styles/workbench-settings.css",
        "server/manager/web/styles/workbench.css",
        "server/manager/web/trading/workbench.js",
        "server/manager/web/trading/workbench.css",
        "server/manager/web/jobs/artifacts.js",
        "server/manager/web/jobs/job-artifact-viewers.js",
        "server/manager/web/test-modules/backtest/results/view.js",
        "tests/scripts/test_worktree_manager_web_manifest.py",
        "tests/scripts/fixtures/backtest_group_form.js",
        "tests/scripts/fixtures/backtest_group_surfaces.js",
        "tests/scripts/fixtures/nautilus_config_review.js",
        "tests/scripts/fixtures/nautilus_report_viewer.js",
        "tests/scripts/fixtures/nautilus_trading_workbench.js",
    })
    assert mode == "SCOPED"
    assert set(targets) == {
        "tests/scripts/test_worktree_manager_web_manifest.py::test_backtest_group_forms_mount_shared_picker_elements",
        "tests/scripts/test_worktree_manager_web_manifest.py::test_backtest_strategy_surfaces_follow_backend_adapter_and_selection_contract",
        "tests/scripts/test_worktree_manager_web_manifest.py::test_strategy_binding_panel_only_routes_library_strategies_to_venues",
        "tests/scripts/test_worktree_manager_web_manifest.py::test_test_workbench_defers_catalog_data_until_needed",
        "tests/scripts/test_worktree_manager_web_manifest.py::test_strategy_list_keeps_compact_batch_and_inline_name_interactions",
        "tests/scripts/test_nautilus_config_review.py",
        "tests/scripts/test_worktree_manager_web_manifest.py::test_manifest_matches_html_script_order_and_files",
        "tests/js/test_strategy_binding_venues.js",
        "tests/js/test_route_dispatch_nav.js",
        "tests/scripts/test_nautilus_trading_workbench.py",
        "tests/scripts/test_nautilus_report_viewer.py",
    }
    assert all((selector.ROOT / path.split("::", 1)[0]).is_file() for path in targets)


def test_selector_change_runs_its_own_contract_test_not_full_suite():
    assert selector.select({"scripts/select_affected_tests.py"}) == (
        "SCOPED", ["tests/scripts/test_select_affected_tests.py"],
    )


def test_isolated_nautilus_report_routes_select_their_boundary_test():
    mode, targets = selector.select({
        "server/manager/http/job_list_routes.py",
        "server/manager/http/job_transfer_routes.py",
        "server/manager/http/write_routes.py",
    })
    assert mode == "SCOPED"
    assert targets == ["tests/server/test_nautilus_report_route.py"]


def test_strategy_group_setting_registry_selects_its_contract_test():
    assert selector.select({"tools/testers/settings/applications.py"}) == (
        "SCOPED", ["tests/backtest/test_setting_surfaces.py"],
    )


def test_factor_expr_streaming_changes_select_bounded_contract_tests():
    mode, targets = selector.select({
        "tools/factors/expr/core.py",
        "tools/factors/expr/streaming/incremental.py",
        "tools/testers/backtest/modules/factor_signal.py",
    })
    assert mode == "SCOPED"
    assert set(targets) == {
        "tests/factors/test_factor_expr_incremental.py",
        "tests/factors/test_groupby_scope_derived_missing.py",
        "tests/factors/test_groupby_scope_infinities.py",
        "tests/factors/test_groupby_scope_streaming.py",
        "tests/backtest/native/test_factor_incremental_compile.py",
        "tests/backtest/native/test_factor_incremental_rolling_window.py",
        "tests/backtest/native/test_incremental_cross_sectional_kernels.py",
        "tests/server/test_nautilus_bridge_factor_stream.py",
    }


def test_all_declared_module_targets_exist():
    assert all((selector.ROOT / "tests" / name).is_dir()
               for group in selector.IMPACT.values() for name in group)
    assert all((selector.ROOT / path.split("::", 1)[0]).is_file()
               for group in selector.EXACT_PATH_TESTS.values() for path in group)
    assert all((selector.ROOT / path.split("::", 1)[0]).is_file()
               for group in selector.PREFIX_PATH_TESTS.values() for path in group)


def test_staged_and_push_ranges_are_separate(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tools/cli").mkdir(parents=True)
    (repo / "tools/cli/app.py").write_text("original\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "-f", "origin/feat", base)
    (repo / "tools/cli/app.py").write_text("pushed\n")
    _git(repo, "commit", "-qam", "outgoing")
    head = _git(repo, "rev-parse", "HEAD")
    (repo / "tools/factors").mkdir(parents=True)
    (repo / "tools/factors/new.py").write_text("staged\n")
    _git(repo, "add", ".")
    monkeypatch.setattr(selector, "ROOT", repo)

    assert selector.staged_paths() == {"tools/factors/new.py"}
    assert selector.pushed_paths(f"refs/heads/feat {head} refs/heads/feat {base}\n") == {
        "tools/cli/app.py"
    }
    assert selector.pushed_paths(f"refs/heads/new {head} refs/heads/new {selector.ZERO_SHA}\n") == {
        "tools/cli/app.py"
    }
    assert selector.pushed_paths(f"refs/heads/feat {base} refs/heads/feat {base}\n") == set()
