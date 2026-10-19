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


def _launch_chromium(playwright):
    errors = []
    for options in ({"channel": "chrome"}, {}):
        try:
            return playwright.chromium.launch(headless=True, **options)
        except Exception as exc:  # pragma: no cover - depends on local browser install
            errors.append(str(exc))
    pytest.skip(f"Chrome and Playwright Chromium are unavailable: {errors[-1]}")


def test_backtest_result_tabs_lazy_load_and_paginate_without_page_errors() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<main id='root'></main>")
        for path in (
            "server/manager/web/core/shared-ui.js",
            "server/manager/web/catalog/shared/multi-select-filter/index.js",
            "server/manager/web/jobs/result-tabs.js",
            "server/manager/web/jobs/artifact-query.js",
            "server/manager/web/core/price-chart.js",
            "server/manager/web/jobs/highcharts-timeline.js",
            "server/manager/web/report/table-view.js",
            "server/manager/web/test-modules/shared/results/runtime-summary.js",
            "server/manager/web/test-modules/backtest/results/model.js",
            "server/manager/web/test-modules/backtest/results/strategy-selection.js",
            "server/manager/web/test-modules/backtest/results/analysis/ui.js",
            "server/manager/web/test-modules/backtest/results/event-flow.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
            "server/manager/web/test-modules/backtest/results/surfaces.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""
          window.FTRichText = {inline(value) { return document.createTextNode(String(value ?? "")); }};
          window.FTBacktestStrategyAnalysis = {open() {}};
          window.FTBacktestSnapshotView = {open() {}};
          const nativeTimestampOf = window.FTPriceChart.timestampOf;
          window.FTPriceChart = {
            timestampOf: nativeTimestampOf,
            render(_context, target, payload, display) {
              window.__assetPlot = {payload, display};
              target.dataset.assetPlotReady = "true";
              return {destroy() {}, xAxis: [{setExtremes() {}}]};
            },
          };
          window.FTMarketData = {
            rangeRequest(request, minimum, maximum, maxPoints) {
              return {...request, minimum, maximum, maxPoints};
            },
            async prices(_context, request) {
              window.__assetPriceRequest = request;
              return {payload: {data: [[request.minimum, 1, 2, 0, 1, 10]]}};
            },
          };
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
            product: "AU.SHF", side: "BUY", quantity: 2, price: 99,
            timestamp: 1700000000000 + (index === 1 ? 0 : index * 60000),
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
            order_detail_data: {
              columns: ["strategy", "order_id", "product", "timestamp", "side", "quantity", "price"],
              rows: orderRows,
            },
            fill_detail_data: {
              rows: [
                {strategy: 'A1', order_id: 'order-1', fill_id: 'fill-1',
                  timestamp: 1700000000000000000, side: 'BUY', price: 99},
                {strategy: 'A1', order_id: 'unrelated', fill_id: 'fill-2',
                  timestamp: 1700000000000000000, side: 'SELL', price: 99},
              ],
            },
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
            if (request.mode === "series") {
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
                return (filter.values || []).includes(value);
              });
            });
            if (request.mode === 'time_rows') {
              return {data: {rows, sampling: {visible_rows: rows.length}}};
            }
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
              runtime_info_rows: [{type: '运行信息', detail: '测试参数已冻结'}],
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
        assert page.locator(".job-result-tabs button", has_text="运行摘要").count() == 0
        assert page.locator(".job-result-tabs button", has_text="回测表现").count() == 1
        assert page.locator(".backtest-runtime-disclosure summary").inner_text() == "运行摘要"

        page.get_by_role("button", name="策略统计").click()
        page.get_by_role("button", name="A1").click()

        page.get_by_role("button", name="时变指标").click()
        page.wait_for_function(
            "document.querySelector('[data-mounted-viewer=\"equity_curve\"]') !== null"
        )
        assert page.locator(
            ".backtest-time-series-surface .job-result-filter-row"
        ).count() == 2
        assert page.locator(
            ".backtest-time-series-surface .job-result-filter-label"
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
        chart_options.locator("span.ft-multi-select-option-label", has_text="净值").first.wait_for()
        chart_options.locator("span.ft-multi-select-option-label", has_text="回撤").first.wait_for()
        chart_options.locator("span.ft-multi-select-option-label", has_text="年化收益率").first.wait_for()
        chart_options.locator("span.ft-multi-select-option-label", has_text="Sharpe ratio").first.wait_for()
        page.locator('input[data-filter-value="equity"]').first.uncheck()
        page.locator('input[data-filter-value="drawdown"]').first.check()
        page.locator('input[data-filter-value="metric:sharpe_ratio"]').first.check()
        # Multi picks commit when the menu collapses (no save button).
        page.locator(".backtest-result-chart-filter summary").click()
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
        page.locator('input[data-filter-value="strategy-a1"]').first.check()
        page.locator(".backtest-result-strategy-filter summary").click()
        page.wait_for_function(
            "document.querySelector('[data-mounted-viewer=\"drawdown_curve\"]')?.dataset.seriesCount === '1'"
        )
        page.evaluate("window.__pointClick(1700000000000)")
        page.get_by_role("dialog").locator("strong", has_text="order-1").wait_for()
        page.get_by_role("dialog").get_by_title("关闭").click()

        page.get_by_role("button", name="交易与账户").click()
        assert page.locator(".backtest-result-strategy-filter summary").inner_text() == "全部策略"
        page.get_by_role("button", name="交易图", exact=True).click()
        page.wait_for_function(
            "document.querySelector('.backtest-asset-chart')?.dataset.assetPlotReady === 'true'"
        )
        assert page.locator(".backtest-asset-events tbody tr").count() == 20
        assert page.locator(".backtest-asset-filter").count() == 3
        assert page.locator(".backtest-asset-filter").last.locator("summary").inner_text() == "AU.SHF"
        assert page.locator(".backtest-asset-filter").nth(1).locator("summary").inner_text() == "全部账本"
        assert page.locator(".backtest-result-strategy-filter").count() == 0
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
        page.get_by_role("button", name="查看交易图").first.click()
        page.wait_for_function("document.querySelector('.backtest-asset-chart')?.dataset.assetPlotReady === 'true'")
        assert page.get_by_role("dialog").count() == 0
        assert page.locator(".backtest-asset-events .shared-paged-table tbody tr").count() == 13
        assert page.locator(".backtest-asset-filter").nth(1).locator("summary").inner_text() == "account-1"
        assert page.locator(".backtest-asset-filter").first.locator("summary").inner_text() == "A1"
        page.locator(".backtest-asset-filter").nth(1).locator("summary").click()
        page.locator('input[data-filter-value="__all_asset_账本__"]').click()
        page.wait_for_function(
            "document.querySelector('.backtest-asset-chart')?.dataset.assetPlotReady === 'true'"
        )
        assert page.locator(".backtest-asset-events tbody tr").count() == 20
        asset = page.evaluate("""() => ({
          request: window.__assetPriceRequest,
          events: window.__artifactQueries.filter(item => item.request.mode === 'time_rows'
            && item.name === 'order_detail_data').at(-1)?.request,
          series: window.__assetPlot.display.overlaySeries(
            {__assetEvents: window.__assetPlot.payload.__assetEvents},
            [{timestamp: 1700000000000, close: 100}], () => {},
              ).map(item => ({name: item.name, count: item.data.length,
                events: item.data.reduce((n, point) => n + point.custom.items.length, 0)})),
        })""")
        assert asset["request"]["product_name"] == "AU.SHF"
        assert asset["events"]["filters"]["product"]["values"] == ["AU.SHF"]
        assert asset["events"]["filters"]["strategy"]["values"] == ["A1"]
        assert "account" not in asset["events"]["filters"]
        assert asset["series"][0]["count"] == 1
        assert asset["series"][0]["events"] == 25
        assert page.evaluate("window.__assetPlot.display.keepOtherSeriesVisible") is True
        page.evaluate("""() => {
          const series = window.__assetPlot.display.overlaySeries(
            {__assetEvents: window.__assetPlot.payload.__assetEvents},
            [{timestamp: 1700000000000, close: 100}],
          );
          const order = series.find(item => item.id === 'asset-order');
          const group = order.data.find(item => item.custom.items.length === 25);
          order.point.events.click.call({options: group});
        }""")
        assert "同一位置的 25 笔事件" in page.locator(
            ".backtest-asset-group-filter"
        ).inner_text()
        assert page.locator(".backtest-asset-events tbody tr").count() == 20
        cards = page.locator(".backtest-asset-event-card")
        assert cards.count() == 25
        assert cards.first.get_by_text("事件 ID").count() == 1
        assert cards.first.locator("dd").count() >= 6
        assert cards.nth(1).get_attribute("open") is None
        cards.nth(1).locator("summary").click()
        assert cards.nth(1).get_attribute("open") is not None
        page.get_by_role("button", name="显示全部事件").click()
        assert page.locator(".backtest-asset-events tbody tr").count() == 20
        fill_marker = page.evaluate("""() => {
          const marker = FTBacktestAssetPlot.markerSeries([
            {artifact: 'fill_detail_data', timestamp: 1700000000000,
              row: {side: 'SELL', fill_price: 105, quantity: 2}},
          ], [{timestamp: 1700000000000, high: 103, low: 99, close: 100}], () => {});
          return marker.find(series => series.id === 'asset-sell').data[0].y;
        }""")
        assert fill_marker == 0.5
        native_fills = page.evaluate("""async () => {
          const state = {artifactsByName: new Map([
            ['order_detail_data', {name: 'order_detail_data'}],
            ['fill_detail_data', {name: 'fill_detail_data'}],
          ]), options: {jobID: 'job-browser'}};
          const selected = FTBacktestAssetPlot.identity({
            product: 'AU.SHF', strategy: 'A1', timestamp: 1700000000000,
          });
          const value = await FTBacktestAssetPlot.loadEvents(
            {t: value => value, api: window.__queryArtifact}, state, selected,
            1699990000000, 1700010000000, 1200,
          );
          return {fills: value.events.filter(item => item.artifact === 'fill_detail_data')
            .map(item => ({id: item.row.fill_id, timestamp: item.timestamp})),
            filteredByOrder: window.__artifactQueries.some(item =>
              item.name === 'fill_detail_data' && item.request.filters?.order?.values
                ?.includes('order-1'))};
        }""")
        assert native_fills == {"fills": [{"id": "fill-1", "timestamp": 1700000000000}],
                                "filteredByOrder": True}
        grouped = page.evaluate("""() => {
          const a = {artifact: 'fill_detail_data', timestamp: 1700000000000,
            row: {side: 'BUY', fill_price: 105, quantity: 2, fee: 3,
              cash_before: 1000, cash_after: 787,
              margin_before: 0, margin_after: 0}};
          const b = {artifact: 'fill_detail_data', timestamp: 1700000000000,
            row: {side: 'SELL', fill_price: 105, quantity: 1}};
          const c = {artifact: 'fill_detail_data', timestamp: 1700000000000,
            row: {side: 'BUY', fill_price: 106, quantity: 1}};
          const groups = FTBacktestAssetPlot.groupedPoints(
            [a, b, c], [{timestamp: 1700000000000, close: 100}],
          );
          const markers = FTBacktestAssetPlot.markerSeries(
            [a, b, c], [{timestamp: 1700000000000, close: 100}], () => {},
          );
          const state = {rerender() { this.rendered = true; }};
          FTBacktestAssetPlot.show(state, {timestamp: 1700000000000,
            instrument: 'AU.SHF', contract_uid: 'CN|AU|au2612|SHF'});
          return {groups: groups.map(group => [group.y, group.items.length]),
            markerCount: markers.reduce((count, item) => count + item.data.length, 0),
            detail: FTBacktestAssetPlot.eventDetail(a),
            selected: state.selectedAsset, view: state.executionView,
            rerendered: state.rendered};
        }""")
        assert grouped["groups"] == [[105, 2], [106, 1]]
        assert grouped["markerCount"] == 1
        assert "现金 1,000 → 787" in grouped["detail"]
        assert "手续费 3" in grouped["detail"]
        assert "保证金" not in grouped["detail"]
        assert grouped["selected"]["contractUID"] == "CN|AU|au2612|SHF"
        assert grouped["view"] == "asset_plot"
        assert grouped["rerendered"] is True
        native_order = page.evaluate("""() => {
          const order = FTBacktestAssetPlot.identity({
            submitted_at: '2025-04-10T14:30:00+08:00',
            product: 'SHFE|F|AU|2506', strategy: 'screen_AU',
          });
          return {order, filters: FTBacktestAssetPlot.eventFilters(order)};
        }""")
        assert native_order["order"]["contractUID"] == "SHFE|F|AU|2506"
        assert native_order["order"]["timestamp"] == 1744266600000
        assert native_order["filters"]["product"]["fields"] == [
            "contract_uid", "instrument", "product",
        ]
        page.get_by_role("button", name="订单", exact=True).click()
        page.get_by_label("账户", exact=True).click()
        page.locator('input[data-filter-value="account-1"]').first.check()
        # Collapse the open menu (outside click) to commit the multi pick.
        page.mouse.click(6, 6)
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
        browser = _launch_chromium(playwright)
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


def test_factor_series_stock_chart_renders_visible_navigator() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_content(
            "<div id='chart' style='width:1200px;min-height:650px'></div>"
        )
        for path in (
            "server/manager/web/styles/outputs/artifacts.css",
            "server/manager/web/styles/outputs/backtest-results.css",
        ):
            page.add_style_tag(path=str(ROOT / path))
        for path in (
            "static/vendor/highcharts/highstock.min.js",
            "server/manager/web/jobs/highcharts-timeline.js",
            "server/manager/web/core/highcharts-range-loader.js",
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/factor-evaluation/results/model.js",
            "server/manager/web/jobs/highcharts-viewers.js",
            "server/manager/web/test-modules/factor-evaluation/results/chart.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""
          const dates = Array.from({length: 240}, (_, index) =>
            new Date(2026, 0, 2, 9, index).toISOString());
          window.__factorRangeLoads = [];
          FTFactorSeriesChart.mount(
            {t: value => value}, document.querySelector('#chart'), {
              product: 'AP.CZC', factorLabel: 'factor',
              factorSeries: {dates, values: dates.map((_, index) => index % 3)},
              price: {data: dates.map((timestamp, index) => ({
                timestamp, open: 100 + index, high: 102 + index,
                low: 99 + index, close: 101 + index,
                volume: 1000 + index,
              }))},
              contracts: [],
            }, {
              rangeOverscanBeforeMs: 7 * 24 * 60 * 60 * 1000,
              async loadRange(minimum, maximum, options) {
                window.__factorRangeLoads.push({minimum, maximum, options});
                return {
                  data: dates.slice(100, 141).map((timestamp, index) => ({
                    timestamp, open: 200 + index, high: 202 + index,
                    low: 199 + index, close: 201 + index,
                    volume: 2000 + index,
                  })),
                  __ftRange: {minimum, maximum},
                };
              },
            },
          );
          document.querySelector('#chart').__ftFactorSeriesChart.xAxis[0].setExtremes(
            Date.parse(dates[100]), Date.parse(dates[140]), true,
          );
        """)
        page.wait_for_timeout(300)
        loaded_range = page.evaluate("window.__factorRangeLoads.at(-1)")
        visible_minimum = page.evaluate(
            "Date.parse(new Date(2026, 0, 2, 9, 100).toISOString())"
        )
        visible_maximum = page.evaluate(
            "Date.parse(new Date(2026, 0, 2, 9, 140).toISOString())"
        )
        assert loaded_range["minimum"] == visible_minimum - 604800000
        assert loaded_range["maximum"] > visible_maximum
        assert loaded_range["options"]["maxPoints"] == 5000
        assert loaded_range["options"]["visibleMinimum"] == visible_minimum
        assert loaded_range["options"]["visibleMaximum"] == visible_maximum
        navigator = page.locator(".highcharts-navigator")
        assert navigator.count() > 0
        navigator_box = navigator.first.bounding_box()
        mount_box = page.locator("#chart").bounding_box()
        canvas_box = page.locator(".interactive-artifact-chart-canvas").bounding_box()
        svg_box = page.locator(".interactive-artifact-chart-canvas svg").bounding_box()
        assert abs(svg_box["height"] - canvas_box["height"]) < 1
        assert navigator_box["height"] > 0
        assert navigator_box["y"] >= mount_box["y"]
        assert navigator_box["y"] + navigator_box["height"] <= (
            mount_box["y"] + mount_box["height"]
        )
        assert page.locator(".highcharts-scrollbar").count() > 0
        browser.close()


def test_price_chart_keeps_trade_markers_when_range_is_reloaded() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1200, "height": 850})
        page.set_content("<div id='chart' style='width:1100px;height:700px'></div>")
        for path in (
            "static/vendor/highcharts/highstock.min.js",
            "server/manager/web/core/highcharts-range-loader.js",
            "server/manager/web/core/price-chart.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""() => {
          const start = Date.UTC(2026, 0, 1);
          const bars = Array.from({length: 50}, (_, index) => ({
            timestamp: start + index * 86400000, open: 100, high: 102,
            low: 99, close: 101, volume: 10,
          }));
          window.__rangeLoads = 0;
          const event = {x: start + 20 * 86400000, y: 105};
          const chart = FTPriceChart.render({t: value => value},
            document.querySelector('#chart'), {data: bars, product: 'AU.SHF'}, {
              overlaySeries(value) { return [{
                id: 'fills', type: 'scatter', name: '成交',
                data: value.__event ? [value.__event] : [event],
              }]; },
              async loadRange() {
                window.__rangeLoads += 1;
                return {data: bars.slice(10, 31), __event: event};
              },
            });
          chart.xAxis[0].setExtremes(start + 10 * 86400000,
            start + 30 * 86400000, true);
        }""")
        page.wait_for_function("window.__rangeLoads > 0")
        page.wait_for_function("document.querySelector('#chart').__ftPriceChart.series.some(s => s.options.id === 'fills' && s.points.length === 1)")
        assert page.evaluate("""() => {
          const chart = document.querySelector('#chart').__ftPriceChart;
          return chart.series.find(s => s.options.id === 'fills').points[0].y;
        }""") == 105
        browser.close()


def test_asset_plot_same_location_group_keeps_other_markers_visible() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1200, "height": 850})
        page.set_content("<div id='chart' style='width:1100px;height:700px'></div>")
        for path in (
            "static/vendor/highcharts/highstock.min.js",
            "server/manager/web/core/highcharts-range-loader.js",
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        result = page.evaluate("""() => {
          const start = Date.UTC(2026, 0, 1);
          const bars = Array.from({length: 10}, (_, index) => ({
            timestamp: start + index * 86400000,
            open: 100, high: 103, low: 99, close: 101, volume: 10,
            open_interest: 200,
          }));
          const events = [
            {artifact: 'order_detail_data', timestamp: start + 2 * 86400000,
              row: {side: 'BUY', price: 102, order_id: 'o1'}},
            {artifact: 'fill_detail_data', timestamp: start + 2 * 86400000,
              row: {side: 'BUY', fill_price: 102, fill_id: 'f1'}},
            {artifact: 'fill_detail_data', timestamp: start + 4 * 86400000,
              row: {side: 'SELL', fill_price: 100, fill_id: 'f2'}},
          ];
          const chart = FTPriceChart.render({t: value => value},
            document.querySelector('#chart'), {data: bars, product: 'AU.SHF'}, {
              keepOtherSeriesVisible: true, eventLane: true,
              overlaySeries(_payload, normalizedBars) {
                return FTBacktestAssetPlot.markerSeries(events, normalizedBars, () => {});
              },
            });
          const mixed = chart.series.find(series => series.options.id === 'asset-mixed');
          const sell = chart.series.find(series => series.options.id === 'asset-sell');
          mixed.points[0].onMouseOver();
          return {
            mixedCount: mixed.points[0].options.custom.items.length,
            mixedLabel: mixed.points[0].dataLabel?.text?.textStr || "",
            markerAxis: mixed.yAxis.index,
            candleAxis: chart.series[0].yAxis.index,
            laneBottom: mixed.yAxis.top + mixed.yAxis.height,
            candleTop: chart.series[0].yAxis.top,
            sellCount: sell.points.length,
            inactiveOpacity: sell.options.states.inactive.opacity,
            markerTime: mixed.points[0].x,
            candleTime: bars[2].timestamp,
            tooltip: chart.tooltip.label?.text?.textStr || "",
          };
        }""")
        assert result["mixedCount"] == 2
        assert result["mixedLabel"] == ""
        assert result["markerAxis"] == 3
        assert result["candleAxis"] == 0
        assert result["laneBottom"] < result["candleTop"]
        assert result["sellCount"] == 1
        assert result["inactiveOpacity"] == 1
        assert result["markerTime"] == result["candleTime"]
        assert "成交量" in result["tooltip"]
        assert "持仓量" in result["tooltip"]
        browser.close()


def test_asset_plot_discovers_scope_and_switches_contract_without_a_selected_order() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page()
        page.set_content("<main id='root'></main>")
        for path in (
            "server/manager/web/catalog/shared/multi-select-filter/index.js",
            "server/manager/web/jobs/artifact-query.js",
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/backtest/results/strategy-selection.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        value = page.evaluate("""async () => {
          const rows = [
            {product: 'AU.SHF', strategy: 'A', account_id: 'ledger-1', timestamp: 1700000000000},
            {product: 'RB.SHF', strategy: 'B', account_id: 'ledger-2', timestamp: 1700000060000},
          ];
          const context = {t: value => value, async api(_path, options) {
            const request = JSON.parse(options.body);
            let matching = rows;
            for (const filter of Object.values(request.filters || {})) {
              matching = matching.filter(row => filter.values.some(value =>
                filter.fields.some(field => row[field] === value)));
            }
            return {data: {rows: matching.slice(0, 1), facets: {
              product: ['AU.SHF', 'RB.SHF'], strategy: ['A', 'B'],
              account: ['ledger-1', 'ledger-2'],
            }}};
          }};
          const state = {
            artifactsByName: new Map([['order_detail_data', {name: 'order_detail_data'}]]),
            options: {jobID: 'job-test'}, strategySelection: ['B'],
            model: {strategies: [{id: 'B', label: 'B'}]},
            executionView: 'asset_plot', target: document.querySelector('#root'),
            rerender() { this.renderCount = (this.renderCount || 0) + 1; },
          };
          const found = await FTBacktestAssetPlot.discover(context, state);
          state.assetPlotDiscovery = {status: 'ready', ...found.choices};
          state.selectedAsset = found.selected;
          const controls = FTBacktestAssetPlot.controls(context, state);
          controls.forEach(item => document.querySelector('#root').append(item.element));
          const product = controls.find(item => item.label === '品种 / 合约').element;
          product.querySelector('summary').click();
          product.querySelector('input[data-filter-value="AU.SHF"]').click();
          await new Promise(resolve => setTimeout(resolve, 0));
          return {initial: found.selected, selected: state.selectedAsset,
            labels: controls.map(item => item.label), renderCount: state.renderCount,
            filters: FTBacktestAssetPlot.eventFilters({
              product: 'AU.SHF', strategy: 'A', account: 'ledger-1',
            })};
        }""")
        assert value["initial"]["product"] == "RB.SHF"
        assert value["initial"]["strategy"] == "B"
        assert value["selected"]["product"] == "AU.SHF"
        assert value["selected"]["timestamp"] == 1700000000000
        assert value["labels"] == ["策略", "账本", "品种 / 合约"]
        assert value["renderCount"] == 1
        assert value["filters"]["account"]["values"] == ["ledger-1"]
        browser.close()
