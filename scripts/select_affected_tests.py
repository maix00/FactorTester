#!/usr/bin/env python3
"""Select focused pytest and JavaScript tests for a Git hook.

Mappings stay explicit at domain boundaries. Unknown production paths run the
full suite; known paths should select the narrowest tests that exercise them.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZERO_SHA = "0" * 40
TEST_MODULES = {
    "analytics", "backtest", "calc", "catalog", "cli", "data", "factors",
    "group", "js", "migrations", "products", "release", "scripts", "server",
    "skills", "sources", "templates", "testers", "traderules",
}
# Cross-module consumers are included, even if a test does not directly import
# the changed package. Keep these groups broad until dependency coverage can
# justify a narrower selection.
IMPACT = {
    "cli": ("cli", "release", "scripts", "server", "catalog"),
    "factors": ("factors", "calc", "group", "backtest", "testers", "server",
                "catalog", "data", "migrations", "release", "scripts"),
    "testers": ("testers", "group", "backtest", "server", "release", "factors", "scripts"),
    "data": ("data", "sources", "products", "factors", "testers", "backtest",
             "calc", "catalog", "scripts", "server"),
    "products": ("products", "data", "sources", "testers", "backtest", "factors", "server"),
    "sources": ("sources", "data", "products", "testers", "backtest"),
    "analytics": ("analytics", "testers", "group", "server"),
    "traderules": ("traderules", "backtest", "testers"),
    "migrations": ("migrations", "server", "release", "data"),
    "templates": ("templates", "server", "release"),
    "apple": ("release", "cli"),
    "skills": ("skills",),
    "js": ("js", "server", "release"),
}
LEAF_TEST_MODULES = {"calc", "catalog", "group", "backtest", "scripts", "release"}
# Precise ownership mappings for modules that previously expanded to most of
# the repository. Add the directly affected tests here when a domain changes.
EXACT_PATH_TESTS = {
    "scripts/test_js.sh": ("tests/js/test_playwright_runtime.js",),
    "server/services/nautilus_bridge/config.py": (
        "tests/server/test_nautilus_bridge_config.py",
        "tests/server/test_nautilus_native_configuration_contract.py",
    ),
    "server/services/nautilus_bridge/native_configuration.py": (
        "tests/server/test_nautilus_bridge_config.py",
        "tests/server/test_nautilus_native_configuration_contract.py",
    ),
    "server/services/nautilus_bridge/engine_factory.py": (
        "tests/server/test_nautilus_bridge_engine_factory.py",
    ),
    "server/services/nautilus_bridge/market_data.py": (
        "tests/server/test_nautilus_bridge_data_contract.py",
        "tests/server/test_nautilus_bridge_historical_rule_events.py",
    ),
    "server/services/nautilus_bridge/catalog.py": (
        "tests/server/test_nautilus_bridge_catalog.py",
    ),
    "tests/benchmarks/bench_nautilus_catalog_staging.py": (
        "tests/server/test_nautilus_bridge_catalog.py",
    ),
    "server/services/nautilus_bridge/backtest_runner.py": (
        "tests/server/test_nautilus_bridge_backtest_runner.py",
        "tests/server/test_nautilus_bridge_reports.py",
    ),
    "server/services/nautilus_bridge/factor_stream.py": (
        "tests/server/test_nautilus_bridge_factor_stream.py",
    ),
    "server/services/nautilus_bridge/rule_transition.py": (
        "tests/server/test_nautilus_bridge_rule_transition.py",
        "tests/server/test_nautilus_bridge_historical_rule_events.py",
    ),
    "server/services/nautilus_bridge/reports.py": (
        "tests/server/test_nautilus_bridge_reports.py",
        "tests/server/test_nautilus_bridge_backtest_runner.py",
    ),
    "server/services/nautilus_bridge/historical_fees.py": (
        "tests/server/test_nautilus_bridge_historical_fees.py",
        "tests/server/test_nautilus_bridge_historical_rule_events.py",
    ),
    "server/services/nautilus_bridge/trading_fields.py": (
        "tests/server/test_nautilus_bridge_trading_fields.py",
    ),
    "server/services/nautilus_bridge/run_spec.py": (
        "tests/server/test_nautilus_bridge_run_spec.py",
        "tests/server/test_research_runspec_field_contract.py",
    ),
    "server/services/nautilus_bridge/venues.py": (
        "tests/server/test_nautilus_bridge_run_spec.py",
        "tests/server/test_nautilus_bridge_engine_factory.py",
    ),
    "server/services/nautilus_bridge/position_offsets.py": (
        "tests/server/test_nautilus_bridge_position_offsets.py",
    ),
    "server/modules/shared/run_spec_resolution/freezing.py": (
        "tests/server/test_nautilus_bridge_run_spec.py",
        "tests/server/test_research_runspec_field_contract.py",
        "tests/server/test_strategy_plans.py",
    ),
    "server/modules/nautilus_workbench/__init__.py": (
        "tests/server/test_nautilus_manager_preview.py",
    ),
    "server/manager/web/workbench/backtest-group-form.js": (
        "tests/scripts/test_worktree_manager_web_manifest.py::test_backtest_group_forms_mount_shared_picker_elements",
    ),
    "server/manager/web/workbench/backtest-groups.js": (
        "tests/scripts/test_worktree_manager_web_manifest.py::test_backtest_strategy_surfaces_follow_backend_adapter_and_selection_contract",
    ),
    "server/manager/web/workbench/strategy-binding-panel.js": (
        "tests/scripts/test_worktree_manager_web_manifest.py::test_strategy_binding_panel_only_routes_library_strategies_to_venues",
        "tests/js/test_strategy_binding_venues.js",
    ),
    "server/manager/web/workbench/nautilus-configuration.js": (
        "tests/scripts/test_nautilus_config_review.py",
    ),
    "server/manager/web/workbench/test-settings.js": (
        "tests/scripts/test_nautilus_config_review.py",
        "tests/scripts/test_worktree_manager_web_manifest.py::test_manifest_matches_html_script_order_and_files",
    ),
    "server/manager/web/workbench/test-configuration.js": (
        "tests/scripts/test_nautilus_config_review.py",
    ),
    "server/manager/web/module-manifest.json": (
        "tests/scripts/test_nautilus_config_review.py",
        "tests/scripts/test_worktree_manager_web_manifest.py::test_manifest_matches_html_script_order_and_files",
    ),
    "server/manager/web/styles/workbench-settings.css": (
        "tests/scripts/test_nautilus_config_review.py",
    ),
    "server/manager/web/trading/workbench.js": (
        "tests/scripts/test_nautilus_trading_workbench.py",
    ),
    "server/manager/web/trading/workbench.css": (
        "tests/scripts/test_nautilus_trading_workbench.py",
    ),
    "server/manager/web/jobs/artifacts.js": (
        "tests/scripts/test_nautilus_report_viewer.py",
    ),
    "server/manager/web/jobs/job-artifact-viewers.js": (
        "tests/scripts/test_nautilus_report_viewer.py",
    ),
    "server/manager/web/test-modules/backtest/results/view.js": (
        "tests/scripts/test_nautilus_report_viewer.py",
    ),
    "server/services/nautilus_bridge/capabilities.py": (
        "tests/server/test_nautilus_source_capabilities.py",
    ),
    "server/services/nautilus_bridge/source_registry.py": (
        "tests/server/test_nautilus_source_registry.py",
        "tests/server/test_nautilus_source_declarations.py",
    ),
    "tests/nautilus_source_fixture.py": (
        "tests/server/test_nautilus_source_registry.py",
        "tests/server/test_nautilus_source_declarations.py",
    ),
    "tests/scripts/fixtures/nautilus_source_overlay.js": (
        "tests/scripts/test_nautilus_source_overlay.py",
    ),
    "server/services/product_catalog_projection.py": (
        "tests/products/test_product_source_projection.py",
    ),
    "server/manager/web/catalog/source-list.js": (
        "tests/scripts/test_nautilus_source_overlay.py",
    ),
    "server/manager/http/job_proxy_routes.py": (
        "tests/server/test_nautilus_preview_routes.py",
    ),
    "server/manager/web/catalog/source-family-detail.js": (
        "tests/scripts/test_nautilus_source_overlay.py",
    ),
    "server/manager/web/workbench/object-overlay.js": (
        "tests/scripts/test_nautilus_source_overlay.py",
    ),
    "server/manager/web/styles/app.css": (
        "tests/scripts/test_nautilus_source_overlay.py",
    ),
    "sources/LocalCNFutures/CNFutures.py": (
        "tests/server/test_nautilus_source_registry.py",
        "tests/server/test_nautilus_source_declarations.py",
        "tests/products/test_product_source_projection.py",
    ),
    "sources/LocalCNFutures/nautilus_adapter.py": (
        "tests/server/test_nautilus_source_registry.py",
        "tests/server/test_nautilus_source_declarations.py",
        "tests/products/test_product_source_projection.py",
    ),
    "sources/registry.py": (
        "tests/server/test_nautilus_source_registry.py",
        "tests/server/test_nautilus_source_declarations.py",
        "tests/products/test_product_source_projection.py",
    ),
    "tools/data/source_catalog.py": (
        "tests/server/test_nautilus_source_registry.py",
        "tests/server/test_nautilus_source_declarations.py",
        "tests/products/test_product_source_projection.py",
    ),
    "tools/data/providers/DataProviderProductTS.py": (
        "tests/server/test_nautilus_source_registry.py",
        "tests/server/test_nautilus_source_declarations.py",
        "tests/products/test_product_source_projection.py",
    ),
    "server/manager/http/strategy_library_routes.py": (
        "tests/server/test_strategy_library.py",
        "tests/scripts/test_worktree_manager_client_app.py::test_strategy_library_patch_uses_manager_application_route",
    ),
    "server/manager/storage/account_domain/factor_version_sync.py": (
        "tests/server/test_versioning_revisions.py",
        "tests/server/test_strategy_catalog_sync.py",
    ),
    "server/manager/storage/account_domain/local.py": (
        "tests/server/test_versioning_revisions.py",
        "tests/server/test_strategy_catalog_sync.py",
        "tests/server/test_account_domain_compact_identity.py",
    ),
    "server/manager/storage/account_domain/service.py": (
        "tests/server/test_versioning_revisions.py",
        "tests/server/test_strategy_catalog_sync.py",
        "tests/scripts/test_worktree_manager_account_domain_sync.py",
    ),
    "server/manager/storage/account_domain/strategy_sync.py": (
        "tests/server/test_strategy_catalog_sync.py",
    ),
    "server/manager/web/app/coordinator.js": (
        "tests/js/test_route_dispatch_nav.js",
    ),
    "server/manager/web/app/navigation.js": (
        "tests/js/test_route_dispatch_nav.js",
        "tests/js/test_tab_nav_highlight.js",
    ),
    "server/manager/web/app/webmcp.js": (
        "tests/js/test_app_shell_startup.js",
    ),
    "server/manager/web/catalog/strategy-library-list.js": (
        "tests/scripts/test_worktree_manager_web_manifest.py::test_strategy_list_keeps_compact_batch_and_inline_name_interactions",
    ),
    "server/manager/web/catalog/strategy-library-runtime.js": (
        "tests/scripts/test_worktree_manager_web_manifest.py::test_inline_strategy_creation_uses_shared_nested_object_overlay",
    ),
    "server/services/factor_strategy_templates.py": (
        "tests/server/test_strategy_library.py",
        "tests/server/test_strategy_plans.py",
    ),
    "server/services/frozen_product_scope.py": (
        "tests/server/test_frozen_product_scope.py",
        "tests/server/test_strategy_plans.py",
    ),
    "server/services/strategy_bindings.py": (
        "tests/server/test_strategy_library.py",
        "tests/server/test_strategy_plans.py",
    ),
    "server/services/strategy_library/service.py": (
        "tests/server/test_strategy_library.py",
        "tests/server/test_strategy_catalog_sync.py",
    ),
    "server/services/strategy_plans.py": (
        "tests/server/test_strategy_plans.py",
    ),
    "server/services/strategy_source_inspection.py": (
        "tests/server/test_strategy_library.py",
        "tests/server/test_strategy_plans.py",
    ),
    "tools/data/sqlite/account_manager/product_group.py": (
        "tests/products/test_product_group_revisions.py",
        "tests/products/test_product_group_subjects.py",
        "tests/server/test_manager_catalog_product_group_write.py",
    ),
    "tools/data/sqlite/factor_source_versions.py": (
        "tests/server/test_versioning_revisions.py",
        "tests/data/test_factor_source_versions.py",
    ),
}
PREFIX_PATH_TESTS = {
    "server/services/versioning/": ("tests/server/test_versioning_revisions.py",),
}
FULL_PATHS = {
    "AGENTS.md", "CONTEXT.md", "conftest.py", "environment.yml", "pytest.ini",
    "pyproject.toml", "setup.cfg", "requirements.txt", "scripts/test.sh",
    ".githooks/pre-commit", ".githooks/pre-push",
}


def _git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def paths_from_name_status(data: bytes) -> set[str]:
    """Parse Git's NUL-delimited name-status format, including both rename ends."""
    tokens = data.decode("utf-8", "surrogateescape").split("\0")
    paths: set[str] = set()
    pos = 0
    while pos < len(tokens) and tokens[pos]:
        status = tokens[pos]
        pos += 1
        count = 2 if status[0] in "RC" else 1
        if pos + count > len(tokens) - 1:
            raise ValueError("incomplete Git name-status output")
        paths.update(tokens[pos : pos + count])
        pos += count
    return paths


def staged_paths() -> set[str]:
    return paths_from_name_status(
        _git("diff", "--cached", "--name-status", "-z", "--find-renames")
    )


def pushed_paths(ref_lines: str) -> set[str] | None:
    """Return None when a push cannot be bounded safely (then run all tests)."""
    if not ref_lines.strip():
        return None
    paths: set[str] = set()
    for line in ref_lines.splitlines():
        fields = line.split()
        if len(fields) != 4:
            return None
        _, local_sha, _, remote_sha = fields
        if local_sha == ZERO_SHA:  # Deleting a remote ref changes no code.
            continue
        if remote_sha == ZERO_SHA:
            try:
                remote_sha = _git("merge-base", "origin/feat", local_sha).decode().strip()
            except subprocess.CalledProcessError:
                return None
        try:
            diff = _git("diff", "--name-status", "-z", "--find-renames", remote_sha, local_sha)
        except subprocess.CalledProcessError:
            return None
        paths.update(paths_from_name_status(diff))
    return paths


def select(paths: set[str] | None) -> tuple[str, list[str]]:
    if paths is None:
        return "FULL", []
    modules: set[str] = set()
    for path in paths:
        parts = Path(path).parts
        if not parts:
            return "FULL", []
        if path == "scripts/select_affected_tests.py":
            modules.add("tests/scripts/test_select_affected_tests.py")
            continue
        exact_tests = EXACT_PATH_TESTS.get(path)
        if exact_tests:
            modules.update(exact_tests)
            continue
        prefix_tests = next(
            (targets for prefix, targets in PREFIX_PATH_TESTS.items() if path.startswith(prefix)),
            None,
        )
        if prefix_tests:
            modules.update(prefix_tests)
            continue
        if path in FULL_PATHS or parts[-1] == "AGENTS.md" or parts[0] in {".github", "deploy", "environments", "third_party"}:
            return "FULL", []
        if parts[0] == "docs" or (path.endswith((".md", ".rst")) and parts[0] != "skills"):
            continue
        if parts[0] == "tests":
            if len(parts) < 3 or parts[1] not in TEST_MODULES:
                return "FULL", []
            if parts[1] == "js":
                modules.add(path if parts[-1].startswith("test_") and path.endswith(".js") and (ROOT / path).exists() else "tests/js")
                continue
            if parts[-1] in {"conftest.py", "__init__.py"}:
                modules.add(f"tests/{parts[1]}")
            elif parts[-1].startswith("test_") and path.endswith(".py"):
                modules.add(path if (ROOT / path).exists() else f"tests/{parts[1]}")
            else:
                modules.add(f"tests/{parts[1]}")
            continue
        if parts[0] == "server" and len(parts) > 1:
            # Unknown server ownership is intentionally fail-closed. Do not
            # turn one Manager edit into a dozen unrelated test directories.
            return "FULL", []
        if parts[0] == "tools" and len(parts) > 2:
            name = parts[1]
            if name in IMPACT:
                modules.update(f"tests/{item}" for item in IMPACT[name])
                continue
            if name in LEAF_TEST_MODULES:
                modules.add(f"tests/{name}")
                continue
            return "FULL", []
        if parts[0] == "sources" and len(parts) > 1:
            modules.update(f"tests/{item}" for item in IMPACT["sources"])
            continue
        if parts[0] == "apple" and len(parts) > 1:
            modules.update(f"tests/{item}" for item in IMPACT["apple"])
            continue
        if parts[0] == "skills" and len(parts) > 1:
            modules.update(f"tests/{item}" for item in IMPACT["skills"])
            modules.add("tests/release/test_bundled_runtime_activation.py")
            continue
        if parts[0] == "static" and len(parts) > 1:
            modules.update(f"tests/{item}" for item in IMPACT["js"])
            continue
        return "FULL", []
    if not modules:
        return "SKIP", []
    return "SCOPED", sorted(modules)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("commit", "push"))
    args = parser.parse_args()
    try:
        paths = staged_paths() if args.phase == "commit" else pushed_paths(sys.stdin.read())
        mode, targets = select(paths)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[test-select] Cannot classify changes: {exc}; using full suite", file=sys.stderr)
        mode, targets = "FULL", []
    print(mode)
    print(*targets, sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
