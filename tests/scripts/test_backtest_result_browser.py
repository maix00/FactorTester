"""Browser-level contract tests for lazy backtest result navigation."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed")
    return sync_playwright()


def test_backtest_result_tabs_lazy_load_and_paginate_without_page_errors() -> None:
    with _playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - depends on local browser cache
            pytest.skip(f"playwright chromium is unavailable: {exc}")
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<main id='root'></main>")
        for path in (
            "server/manager/web/core/shared-ui.js",
            "server/manager/web/report/table-view.js",
            "server/manager/web/jobs/backtest-runtime-model.js",
            "server/manager/web/jobs/backtest-result-model.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""
          window.FTRichText = {inline(value) { return document.createTextNode(String(value ?? "")); }};
          window.FTBacktestGroupDetail = {open() {}};
          window.FTBacktestRankingView = {open() {}};
          window.FTBacktestSnapshotView = {open() {}};
          window.FTJobHighcharts = {
            mount(_context, target, payload, viewer) {
              target.dataset.mountedViewer = viewer;
              target.dataset.seriesCount = String(payload.series?.length || 0);
            },
          };
          window.__artifactFetches = [];
          const orderRows = Array.from({length: 25}, (_, index) => ({
            strategy: "A1", order_id: `order-${index + 1}`,
          }));
          const payloads = {
            equity_curve_data: {
              artifact_kind: "equity_curve",
              series: [{label: "A1", timestamps: [1, 2], values: [100, 101], drawdown: [0, -0.01]}],
            },
            order_detail_data: {columns: ["strategy", "order_id"], rows: orderRows},
          };
          window.FTJobArtifacts = {
            async fetch(_context, path) {
              const name = decodeURIComponent(path.split("/artifacts/")[1].split("?")[0]);
              window.__artifactFetches.push(name);
              return {async text() { return JSON.stringify(payloads[name]); }};
            },
          };
        """)
        page.add_script_tag(
            path=str(ROOT / "server/manager/web/jobs/backtest-result-view.js")
        )
        page.evaluate("""
          const context = {t: value => value};
          const section = window.FTBacktestResults.section(context, {
            jobID: "job-browser",
            artifacts: [
              {name: "equity_curve_data", state: "active"},
              {name: "order_detail_data", state: "active"},
            ],
            resultSummary: {
              groups: [{name: "A1", metrics_key: "A1"}],
              metrics: {A1: {"Total Return": 1}},
            },
          });
          document.querySelector("#root").append(section);
        """)
        page.wait_for_function("document.querySelectorAll('.backtest-domain-tabs button').length >= 4")
        assert page.evaluate("window.__artifactFetches") == []

        page.get_by_role("button", name="净值与回撤").click()
        page.wait_for_function(
            "document.querySelector('[data-mounted-viewer=\"equity_curve\"]') !== null"
        )
        assert page.evaluate("window.__artifactFetches") == ["equity_curve_data"]

        page.get_by_role("button", name="订单").click()
        page.wait_for_function(
            "document.querySelectorAll('.backtest-domain-content tbody tr').length === 20"
        )
        assert page.evaluate("window.__artifactFetches") == [
            "equity_curve_data", "order_detail_data",
        ]
        page.get_by_role("button", name="下一页").click()
        page.wait_for_function(
            "document.querySelectorAll('.backtest-domain-content tbody tr').length === 5"
        )
        assert page.locator(".backtest-domain-content").get_by_text("order-25").count() == 1

        page.get_by_role("button", name="净值与回撤").click()
        page.wait_for_function(
            "document.querySelector('[data-mounted-viewer=\"equity_curve\"]') !== null"
        )
        assert page.evaluate("window.__artifactFetches") == [
            "equity_curve_data", "order_detail_data",
        ], "returning to a result tab must reuse its loaded payload"
        assert errors == []
        browser.close()
