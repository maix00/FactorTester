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
            "server/manager/web/catalog/shared/multi-select-filter.js",
            "server/manager/web/jobs/result-tabs.js",
            "server/manager/web/jobs/artifact-query.js",
            "server/manager/web/jobs/highcharts-timeline.js",
            "server/manager/web/report/table-view.js",
            "server/manager/web/test-modules/backtest/results/runtime-model.js",
            "server/manager/web/test-modules/backtest/results/model.js",
            "server/manager/web/test-modules/backtest/results/strategy-selection.js",
            "server/manager/web/test-modules/backtest/results/analysis/ui.js",
            "server/manager/web/test-modules/backtest/results/event-flow.js",
            "server/manager/web/test-modules/backtest/results/surfaces.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""
          window.FTRichText = {inline(value) { return document.createTextNode(String(value ?? "")); }};
          window.FTBacktestStrategyAnalysis = {open() {}};
          window.FTBacktestSnapshotView = {open() {}};
          window.FTJobHighcharts = {
            metricChoices(payload) {
              const rows = payload?.rows || [];
              return [
                ["annual_return", "年化收益率"], ["sharpe_ratio", "Sharpe ratio"],
              ].filter(([key]) => rows.some(row => row[key] != null))
                .map(([key, label]) => ({key, label}));
            },
            mount(_context, target, payload, viewer, display) {
              target.dataset.mountedViewer = viewer;
              target.dataset.seriesCount = String(payload.series?.length || 0);
              target.dataset.selectedMetric = display?.selectedMetric || "";
              window.__pointClick = display?.onPointClick;
            }, mountRows(_context, target) { target.dataset.mountedViewer = "rows"; },
          };
          window.__artifactFetches = [];
          window.__artifactQueries = [];
          const orderRows = Array.from({length: 25}, (_, index) => ({
            strategy: "A1", order_id: `order-${index + 1}`,
            timestamp: 1700000000000 + index * 60000,
            account_id: `account-${(index % 2) + 1}`,
            cash_pool_id: `pool-${(index % 2) + 1}`,
            account_currency: index % 2 ? "HKD" : "USD",
            cash_pool_base_currency: "CNY",
          }));
          const payloads = {
            equity_curve_data: {
              artifact_kind: "equity_curve",
              series: [
                {strategy_id: "strategy-a1", label: "A1", timestamps: [1, 2], values: [100, 101], drawdown: [0, -0.01]},
                {strategy_id: "strategy-a2", label: "A2", timestamps: [1, 2], values: [100, 99], drawdown: [0, -0.01]},
              ],
            },
            metrics_over_time_data: {
              artifact_kind: "metrics_over_time",
              rows: [
                {series: "A1", timestamp: "2025-01-02", annual_return: 0.1, sharpe_ratio: 1.2},
                {series: "A2", timestamp: "2025-01-02", annual_return: 0.2, sharpe_ratio: 1.3},
              ],
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
          window.__queryArtifact = async (path, options) => {
            const name = decodeURIComponent(
              path.split("/artifacts/")[1].split("/query")[0],
            );
            const request = JSON.parse(options.body || "{}");
            window.__artifactQueries.push({name, request});
            const payload = payloads[name];
            if (request.mode === "series" || request.mode === "time_rows") {
              return {data: payload};
            }
            let rows = [...(payload.rows || [])];
            const filters = request.filters || {};
            const candidate = (row, fields) => String(
              fields.map(field => row[field]).find(value => value != null && String(value)) || "",
            );
            Object.values(filters).forEach(filter => {
              rows = rows.filter(row => {
                const value = candidate(row, filter.fields || []);
                return !value || (filter.values || []).includes(value);
              });
            });
            const facets = Object.fromEntries(Object.entries(request.facets || {}).map(
              ([key, fields]) => [key, [...new Set(
                payload.rows.map(row => candidate(row, fields)).filter(Boolean),
              )].sort()],
            ));
            const distinct = Object.fromEntries(Object.entries(request.distinct || {}).map(
              ([key, definition]) => {
                const seen = new Set();
                const values = rows.flatMap(row => {
                  const item = Object.fromEntries(Object.entries(definition).map(
                    ([label, fields]) => [label, candidate(row, fields)],
                  ));
                  const identity = JSON.stringify(item);
                  if (seen.has(identity)) return [];
                  seen.add(identity); return [item];
                });
                return [key, values];
              },
            ));
            const page = Number(request.page || 1);
            const pageSize = Number(request.page_size || 20);
              return {data: {
              query_mode: "table", columns: payload.columns,
              rows: rows.slice((page - 1) * pageSize, page * pageSize),
                page, page_size: pageSize, total: rows.length, facets, distinct,
              }};
            };
            void 0;
          """)
        page.add_script_tag(
            path=str(ROOT / "server/manager/web/test-modules/backtest/results/view.js")
        )
        page.evaluate("""
          const context = {t: value => value, api: window.__queryArtifact};
          const section = window.FTBacktestResults.section(context, {
            jobID: "job-browser",
            artifacts: [
              {name: "equity_curve_data", state: "active"},
              {name: "metrics_over_time_data", state: "active"},
              {name: "order_detail_data", state: "active"},
            ],
            resultSummary: {
              groups: [
                {strategy_id: "strategy-a1", name: "A1", metrics_key: "A1"},
                {strategy_id: "strategy-a2", name: "A2", metrics_key: "A2"},
              ],
              metrics: {A1: {"Total Return": 1}, A2: {"Total Return": -1}},
            },
          });
          document.querySelector("#root").append(section);
        """)
        page.wait_for_function("document.querySelectorAll('.job-result-tabs button').length >= 3")
        assert page.evaluate("window.__artifactFetches") == []

        page.get_by_role("button", name="策略统计").click()
        page.get_by_role("button", name="A1").click()

        page.get_by_role("button", name="时变指标").click()
        page.wait_for_function(
            "document.querySelector('[data-mounted-viewer=\"equity_curve\"]') !== null"
        )
        assert page.locator(
            ".backtest-time-series-surface .backtest-surface-filter-row"
        ).count() == 2
        assert page.locator(
            ".backtest-time-series-surface .backtest-surface-filter-label"
        ).all_text_contents() == ["策略", "曲线"]
        page.wait_for_function(
            "window.__artifactQueries.some(item => item.name === 'metrics_over_time_data')"
        )
        page.wait_for_function(
            "document.querySelector('input[data-filter-value=\"metric:sharpe_ratio\"]') !== null"
        )
        assert set(page.evaluate("window.__artifactQueries.map(item => item.name)")) == {
            "equity_curve_data", "metrics_over_time_data",
        }
        assert page.locator('[data-mounted-viewer="equity_curve"]').get_attribute(
            "data-series-count"
        ) == "2"

        page.locator(".backtest-result-chart-filter summary").click()
        chart_options = page.locator(
            "body > .ft-multi-select-menu.is-portaled .ft-multi-select-options"
        )
        chart_options.get_by_text("净值", exact=True).wait_for()
        chart_options.get_by_text("回撤", exact=True).wait_for()
        chart_options.get_by_text("年化收益率", exact=True).wait_for()
        chart_options.get_by_text("Sharpe ratio", exact=True).wait_for()
        page.locator('input[data-filter-value="equity"]').uncheck()
        page.locator('input[data-filter-value="drawdown"]').check()
        page.locator('input[data-filter-value="metric:sharpe_ratio"]').check()
        page.get_by_role("button", name="保存").click()
        page.wait_for_function(
            "document.querySelector('[data-mounted-viewer=\"drawdown_curve\"]') !== null"
        )
        page.wait_for_function(
            "document.querySelector('[data-selected-metric=\"sharpe_ratio\"]') !== null"
        )
        assert page.locator(".backtest-chart-card h3").all_text_contents() == [
            "回撤", "Sharpe ratio",
        ]

        page.locator(".backtest-result-strategy-filter summary").click()
        page.locator('input[data-filter-value="strategy-a1"]').check()
        page.get_by_role("button", name="保存").click()
        page.wait_for_function(
            "document.querySelector('[data-mounted-viewer=\"drawdown_curve\"]')?.dataset.seriesCount === '1'"
        )
        page.evaluate("window.__pointClick(1700000000000)")
        page.get_by_role("dialog").locator("strong", has_text="order-1").wait_for()
        page.get_by_role("dialog").get_by_title("关闭").click()

        page.get_by_role("button", name="交易与账户").click()
        assert page.locator(".backtest-result-strategy-filter summary").inner_text() == "全部策略"
        page.get_by_role("button", name="事件流", exact=True).click()
        page.locator(".backtest-event-flow strong", has_text="order-25").wait_for()
        assert page.get_by_role("button", name="上一时刻").is_enabled()
        page.get_by_role("button", name="订单", exact=True).click()
        page.get_by_text("策略、账户与资金池关系").wait_for()
        assert page.locator(
            ".backtest-dimension-filters .backtest-surface-filter-row"
        ).count() == 4
        assert page.locator(
            ".backtest-dimension-filters .backtest-surface-filter-label"
        ).all_text_contents() == ["账户", "资金池", "账户币种", "资金池基准币种"]
        assert page.get_by_text("account-1", exact=True).count() >= 1
        page.get_by_role("button", name="按账户").click()
        page.locator(".backtest-relation-table").get_by_text(
            "USD", exact=True,
        ).wait_for()
        page.get_by_role("button", name="按资金池").click()
        page.locator(".backtest-relation-table").get_by_text(
            "CNY", exact=True,
        ).first.wait_for()
        page.wait_for_function(
            "document.querySelectorAll('.backtest-result-lazy-target > .backtest-domain-table tbody tr').length === 20"
        )
        assert page.evaluate("window.__artifactFetches") == []
        assert set(page.evaluate("window.__artifactQueries.map(item => item.name)")) == {
            "equity_curve_data", "metrics_over_time_data", "order_detail_data",
        }
        page.locator(
            ".backtest-result-lazy-target > .backtest-domain-table"
        ).get_by_role("button", name="下一页").click()
        page.wait_for_function(
            "document.querySelectorAll('.backtest-result-lazy-target > .backtest-domain-table tbody tr').length === 5"
        )
        assert page.locator(".backtest-domain-content").get_by_text("order-25").count() == 1
        page.get_by_label("账户", exact=True).click()
        page.locator('input[data-filter-value="account-1"]').check()
        page.get_by_role("button", name="保存").click()
        page.get_by_text("共 13 行").wait_for()

        page.get_by_role("button", name="时变指标").click()
        page.wait_for_function(
            "document.querySelector('[data-mounted-viewer=\"drawdown_curve\"]') !== null"
        )
        assert page.evaluate("window.__artifactFetches") == []
        assert page.locator(".backtest-result-strategy-filter summary").inner_text() == "A1"
        assert errors == []
        browser.close()


def test_strategy_statistics_opens_one_tabbed_analysis_overlay() -> None:
    with _playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<main></main>")
        for path in (
            "server/manager/web/core/shared-ui.js",
            "server/manager/web/test-modules/backtest/results/analysis/ui.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""
          window.FTBacktestResultModel = {
            relatedGroupEntries() { return [
              {key: "g1", label: "第一组", configurationID: "same"},
              {key: "g2", label: "第二组", configurationID: "same"},
            ]; },
            diagnosticKey() { return "same"; },
          };
          window.FTBacktestGroupDetail = {
            tabs: [
              {id: "overview", label: "概览"},
              {id: "returns", label: "收益时序"},
              {id: "products", label: "产品贡献"},
            ],
            async load(_context, _options, entry) { return {entry: entry.key}; },
            renderTab(_context, target, detail, tab) {
              target.textContent = `${tab}:${detail.entry}`;
            },
          };
          window.FTBacktestRankingView = {
            async load() { return {ranking: true}; },
            render(_context, target) { target.textContent = "ranking:shared"; },
          };
        """)
        page.add_script_tag(path=str(
            ROOT / "server/manager/web/test-modules/backtest/results/analysis/strategy-analysis.js"
        ))
        page.evaluate("""
          FTBacktestStrategyAnalysis.open(
            {t: value => value}, {resultSummary: {}},
            {key: "g2", label: "第二组", configurationID: "same"},
            "products",
          );
        """)
        assert page.get_by_role("dialog").count() == 1
        assert page.get_by_role("button", name="概览").count() == 1
        assert page.get_by_role("button", name="收益时序").count() == 1
        assert page.get_by_role("button", name="产品贡献").count() == 1
        page.get_by_text("products:g2").wait_for()
        page.get_by_role("button", name="排序诊断").click()
        page.get_by_text("ranking:shared").wait_for()
        browser.close()
