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
              window.__assetPriceLines = [];
              return {destroy() {}, xAxis: [{setExtremes() {}}],
                yAxis: [{removePlotLine() {}, addPlotLine(line) {
                  window.__assetPriceLines.push(line);
                }}]};
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
        page.wait_for_function(
            "document.querySelector('.backtest-asset-chart')?.dataset.assetPlotReady === 'true'"
        )
        assert page.locator(".backtest-inner-tabs button").count() == 0
        assert page.locator(".backtest-asset-events tbody tr").count() == 20
        assert page.locator(".backtest-asset-filter").count() == 3
        assert page.locator(".backtest-order-track-controls").count() == 1
        assert page.locator(".backtest-asset-events thead th").all_text_contents() == [
            "时间", "订单阶段 / ID", "策略", "账户 / 资金池", "方向 / 状态",
            "数量", "价格", "剩余", "手续费", "账本变化",
        ]
        assert page.locator(".backtest-asset-filter").last.locator("summary").inner_text() == "AU.SHF"
        assert page.locator(".backtest-result-strategy-filter").count() == 0
        assert set(page.evaluate("window.__artifactQueries.map(item => item.name)")) == {
            "equity_curve_data", "metrics_over_time_data", "order_detail_data",
        }
        assert page.evaluate("window.__artifactFetches") == []
        assert page.evaluate("window.__assetPlot.display.keepOtherSeriesVisible") is True
        assert page.evaluate("window.__assetPlot.display.preserveSourceBars") is True
        assert page.evaluate("window.__assetPriceRequest.anchor_tolerance_ms") == 86400000
        assert errors == []

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


def test_factor_workbench_shows_all_nested_layers_with_market_panes() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<div id='chart' style='width:1100px'></div>")
        page.add_script_tag(path=str(ROOT /
            "static/vendor/lightweight-charts/lightweight-charts.standalone.production.js"))
        page.evaluate("""() => {
          const source = window.LightweightCharts;
          window.LightweightCharts = {...source, createChart(...args) {
            window.__factorChart = source.createChart(...args);
            return window.__factorChart;
          }};
        }""")
        page.add_script_tag(path=str(ROOT /
            "static/vendor/chart-workbench/chart-workbench.js"))
        page.evaluate("""() => {
          const start = Date.UTC(2025, 0, 2, 9);
          const bars = Array.from({length: 20}, (_, index) => ({
            timestamp: start + index * 60000, open: 100 + index,
            high: 102 + index, low: 99 + index, close: 101 + index,
            volume: 1000 + index, openInterest: 500 + index,
          }));
          const points = bars.map((bar, index) => ({timestamp: bar.timestamp,
            value: index === 4 ? null : index / 10}));
          window.__factorRangeCalls = [];
          window.__factorController = FTChartWorkbench.mountFactorChart(
            document.querySelector('#chart'), {
              product: 'T.CFE', bars,
              indicators: [
                {id:'root', label:'最终信号', points},
                {id:'duration', label:'当日差持续期', points},
              ],
              async loadRange(minimum, maximum, maxPoints) {
                window.__factorRangeCalls.push({minimum, maximum, maxPoints});
                return bars;
              },
            });
        }""")
        page.wait_for_selector(".ft-factor-chart-canvas canvas")
        assert page.evaluate("window.__factorChart.panes().length") == 5
        factor_data = page.evaluate("""() => window.__factorChart.panes()[1]
          .getSeries()[0].data()""")
        assert len(factor_data) == 19
        assert not any(row["time"] == 1735808640 for row in factor_data)
        assert page.locator(".ft-factor-indicators label").count() == 2
        assert page.get_by_label("当日差持续期").is_checked()
        page.get_by_label("当日差持续期").uncheck()
        assert not page.get_by_label("当日差持续期").is_checked()
        assert page.evaluate("""() => window.__factorChart.panes()[2]
          .getSeries()[0].options().visible""") is False
        page.evaluate("""() => window.__factorController.setVisibleRange(
          Date.UTC(2025, 0, 2, 9, 5), Date.UTC(2025, 0, 2, 9, 10))""")
        page.wait_for_function("window.__factorRangeCalls.length > 0")
        assert page.evaluate("window.__factorRangeCalls.at(-1).maxPoints") == 5000
        assert errors == []
        browser.close()


def test_factor_result_groups_nested_layers_by_product_in_one_chart() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<main id='root'></main>")
        for path in (
            "server/manager/web/core/shared-ui.js",
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/factor-evaluation/results/model.js",
            "static/vendor/lightweight-charts/lightweight-charts.standalone.production.js",
            "static/vendor/chart-workbench/chart-workbench.js",
            "server/manager/web/test-modules/factor-evaluation/results/view.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""() => {
          window.__loadedGroups = [];
          FTStaticLoader = {async loadGroups(groups) {
            window.__loadedGroups.push(...groups);
          }};
          FTJobResultTabs = {filterPanel(_context, options) {
            const element = document.createElement('div');
            element.append(...options.rows.map(row => row.element));
            return {element};
          }};
          FTMultiSelectFilter = {create(_context, options) {
            const element = document.createElement('select');
            element.className = options.className || '';
            for (const item of options.items) {
              const choice = document.createElement('option');
              choice.value = item.value; choice.textContent = item.label;
              element.append(choice);
            }
            element.value = options.selected[0];
            element.addEventListener('change', () => options.onChange([element.value]));
            return {element};
          }};
          const start = Date.UTC(2025, 0, 2, 9);
          const dates = Array.from({length: 20}, (_, index) =>
            new Date(start + index * 60000).toISOString());
          FTMarketData = {
            rangeRequest(request, minimum, maximum, maxPoints) {
              return {...request, minimum, maximum, maxPoints};
            },
            async prices() { return {source: 'server', payload: {data:
              dates.map((timestamp, index) => ({timestamp,
                open: 100 + index, high: 102 + index, low: 99 + index,
                close: 101 + index, volume: 1000 + index,
                open_interest: 500 + index}))}}; },
            async contracts() { return {payload: {contracts: []}}; },
          };
          const resultSummary = {factor: {alias:'TsDurDev', freq:'MIN1'},
            series: [
              {product:'T.CFE', dates, values: dates.map((_, i) => i / 10)},
              {product:'T.CFE', layer:'当日差持续期', dates,
                values: dates.map((_, i) => i / 20)},
              {product:'T.CFE', layer:'平滑持续期', dates,
                values: dates.map((_, i) => i / 30)},
            ]};
          document.querySelector('#root').append(FTFactorSeriesResults.embedded(
            {t:value=>value}, {resultSummary, configuration:{}}));
        }""")
        page.wait_for_selector(".ft-factor-chart-canvas canvas")
        assert page.evaluate("window.__loadedGroups") == ["chart-workbench-factor"]
        assert page.locator(".factor-series-product-filter option").count() == 1
        assert page.locator(".ft-factor-indicators label").count() == 3
        assert page.locator(".factor-series-chart-mount canvas").count() > 0
        assert page.locator(".highcharts-container").count() == 0
        assert errors == []
        browser.close()


@pytest.mark.parametrize("view", ["price", "asset", "factor"])
def test_lightweight_chart_keeps_existing_bars_after_zoom_out(view: str) -> None:
    """A shorter range response must not erase already loaded history."""
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1100, "height": 850})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<main id='root'></main>")
        page.add_script_tag(path=str(ROOT / "static/vendor/lightweight-charts/lightweight-charts.standalone.production.js"))
        page.add_script_tag(path=str(ROOT / "static/vendor/chart-workbench/chart-workbench.js"))
        page.evaluate("""view => {
          const start = Date.UTC(2025, 0, 1);
          const bars = Array.from({length: 8}, (_, index) => ({
            timestamp: start + index * 86400000,
            open: 100 + index, high: 102 + index,
            low: 99 + index, close: 101 + index,
            volume: 1000 + index, openInterest: 500 + index,
          }));
          window.__bars = bars;
          window.__requests = 0;
          window.__candleTimes = [];
          const createChart = LightweightCharts.createChart;
          window.LightweightCharts = {...LightweightCharts, createChart: (...args) => {
            const chart = createChart(...args);
            window.__chart = chart;
            const addSeries = chart.addSeries.bind(chart);
            chart.addSeries = (...seriesArgs) => {
              const series = addSeries(...seriesArgs);
              if (seriesArgs[0] === LightweightCharts.CandlestickSeries) {
                const setData = series.setData.bind(series);
                series.setData = rows => {
                  window.__candleTimes = rows.map(row => row.time);
                  setData(rows);
                };
              }
              return series;
            };
            return chart;
          }};
          const loadRange = async (minimum, maximum) => {
            window.__requests += 1;
            const shortened = bars.slice(3, 5);
            if (view === 'price' && maximum - minimum >= 6 * 86400000) return bars;
            return view === 'asset' ? {bars: shortened, events: []} : shortened;
          };
          const root = document.querySelector('#root');
          if (view === 'price') window.__priceHandle =
            FTChartWorkbench.mountPriceChart(root, {bars, loadRange});
          if (view === 'asset') FTChartWorkbench.mountAssetChart(root,
            {bars, events: [], frequencyMs: 86400000, loadRange});
          if (view === 'factor') FTChartWorkbench.mountFactorChart(root,
            {bars, indicators: [{id: 'x', label: 'x', points: []}], product: 'AU.SHF', loadRange});
        }""", view)
        page.wait_for_selector("canvas", timeout=5000)
        assert page.evaluate("Boolean(window.__chart)"), errors
        assert page.evaluate("window.__candleTimes.length") == 8, errors
        if view == "price":
            assert page.evaluate("window.__requests") == 0
            page.evaluate("document.querySelector('.ft-lightweight-price-canvas').dispatchEvent(new Event('pointerdown'))")
        # The first change initializes the subscriber in the asset/factor charts.
        page.evaluate("window.__chart.timeScale().setVisibleRange({from: __bars[1].timestamp / 1000, to: __bars[6].timestamp / 1000})")
        page.evaluate("window.__chart.timeScale().setVisibleRange({from: __bars[3].timestamp / 1000, to: __bars[4].timestamp / 1000})")
        page.wait_for_function("window.__requests > 0")
        page.wait_for_function("window.__candleTimes.length === 8")
        if view == "price":
            page.evaluate("document.querySelector('.ft-lightweight-price-canvas').dispatchEvent(new Event('pointerdown'))")
        page.evaluate("window.__chart.timeScale().setVisibleRange({from: __bars[0].timestamp / 1000, to: __bars[7].timestamp / 1000})")
        if view != "price":
            page.wait_for_function("window.__requests > 1")
        else:
            assert page.evaluate("window.__requests") == 1
        assert page.evaluate("window.__candleTimes.length") == 8
        if view == "price":
            page.evaluate("window.__priceHandle.focusRange(__bars[2].timestamp, __bars[5].timestamp)")
            page.wait_for_function("""() => {
              const range = __chart.timeScale().getVisibleRange();
              return range && Number(range.from) === __bars[2].timestamp / 1000
                && Number(range.to) === __bars[5].timestamp / 1000;
            }""")
        assert errors == []
        browser.close()


def test_price_chart_zoom_settles_after_detail_load() -> None:
    """Replacing coarse bars with finer bars must not recursively reload a settled zoom."""
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1100, "height": 850})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<main id='root'></main>")
        page.add_script_tag(path=str(ROOT / "static/vendor/lightweight-charts/lightweight-charts.standalone.production.js"))
        page.add_script_tag(path=str(ROOT / "static/vendor/chart-workbench/chart-workbench.js"))
        page.evaluate("""() => {
          const start = Date.UTC(2025, 0, 1);
          const bar = (timestamp, value) => ({timestamp, open: value,
            high: value + 1, low: value - 1, close: value + 0.5,
            volume: 100, openInterest: 200});
          const overview = Array.from({length: 30}, (_, i) =>
            bar(start + i * 86400000, 100 + i));
          window.__requests = [];
          window.__rangeWrites = [];
          const createChart = LightweightCharts.createChart;
          window.LightweightCharts = {...LightweightCharts, createChart: (...args) => {
            const chart = createChart(...args);
            const scale = chart.timeScale();
            for (const method of ['setVisibleRange', 'setVisibleLogicalRange']) {
              const original = scale[method].bind(scale);
              scale[method] = range => {
                window.__rangeWrites.push({method, range});
                return original(range);
              };
            }
            window.__chart = chart;
            return chart;
          }};
          const loadRange = async (minimum, maximum) => {
            __requests.push([minimum, maximum]);
            await new Promise(resolve => setTimeout(resolve, 650));
            return Array.from({length: 1440}, (_, i) => {
              const timestamp = minimum + i * (maximum - minimum) / 1439;
              return bar(timestamp, 110 + i / 1440);
            });
          };
          window.__handle = FTChartWorkbench.mountPriceChart(
            document.querySelector('#root'), {bars: overview, loadRange});
          window.__zoom = () => __handle.focusRange(
            start + 10 * 86400000, start + 12 * 86400000);
          window.__timeUnderPointer = x => Number(__chart.timeScale().coordinateToTime(x));
        }""")
        page.wait_for_selector("canvas", timeout=5000)
        page.evaluate("window.__zoom()")
        page.wait_for_function("window.__requests.length > 0")
        page.locator(".ft-lightweight-price-loading").wait_for()
        pointer = page.evaluate("""() => {
          const rect = document.querySelector('.ft-lightweight-price-canvas')
            .getBoundingClientRect();
          return {x: rect.left + rect.width * 0.48, y: rect.top + 160,
            localX: rect.width * 0.48};
        }""")
        page.mouse.move(pointer["x"], pointer["y"])
        fractional_anchor = page.evaluate("window.__timeUnderPointer", pointer["localX"])
        before_logical = page.evaluate("""x => ({point: __chart.timeScale().coordinateToLogical(x),
          range: __chart.timeScale().getVisibleLogicalRange()})""", pointer["localX"])
        page.evaluate("window.__rangeWrites = []")
        page.wait_for_timeout(1500)
        assert page.evaluate("window.__requests.length") == 1, errors
        assert page.evaluate("window.__requests[0][0]") < 1736553600000, (
            "detail request should include bars before the visible zoom window"
        )
        assert page.locator(".ft-lightweight-price-loading").count() == 0
        fractional_after = page.evaluate("window.__timeUnderPointer", pointer["localX"])
        after_logical = page.evaluate("""x => ({point: __chart.timeScale().coordinateToLogical(x),
          range: __chart.timeScale().getVisibleLogicalRange(), writes: __rangeWrites})""", pointer["localX"])
        # Lightweight Charts snaps the cursor to a source bar. The synthetic
        # detail is ~240 seconds per bar; half a bar is the useful tolerance.
        assert abs(fractional_after - fractional_anchor) <= 125, (
            f"time under pointer moved: {fractional_anchor} → {fractional_after}; "
            f"before={before_logical}; after={after_logical}"
        )
        assert page.evaluate("window.__rangeWrites.map(write => write.method)") == [
            "setVisibleLogicalRange"
        ], "detail replacement should commit one anchored range, not redraw twice"
        page.evaluate("""() => {
          document.querySelector('.ft-lightweight-price-canvas')
            .dispatchEvent(new Event('pointerdown'));
          __chart.timeScale().setVisibleRange({
            from: Date.UTC(2025, 0, 1) / 1000,
            to: Date.UTC(2025, 0, 30) / 1000,
          });
        }""")
        page.wait_for_function("window.__chart.panes()[0].getSeries()[0].data().length === 30")
        assert page.evaluate("window.__requests.length") == 1
        range_after_zoom_out = page.evaluate("""() => {
          const range = __chart.timeScale().getVisibleRange();
          return [Number(range.from), Number(range.to)];
        }""")
        assert range_after_zoom_out[0] >= 1735689600
        assert range_after_zoom_out[1] <= 1738195200
        page.evaluate("""() => __chart.timeScale().setVisibleRange({
          from: Date.UTC(2024, 11, 1) / 1000,
          to: Date.UTC(2025, 1, 28) / 1000,
        })""")
        range_outside_data = page.evaluate("""() => {
          const range = __chart.timeScale().getVisibleRange();
          return [Number(range.from), Number(range.to)];
        }""")
        assert range_outside_data[0] >= 1735689600
        assert range_outside_data[1] <= 1738195200
        assert errors == []
        browser.close()


def test_product_price_heading_aligns_icon_glyphs_to_text_baseline() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page()
        page.set_content("""<div class="product-price-heading">
          <h2>价格曲线<span class="baseline-probe"></span></h2>
          <span class="product-price-timezone-label">时区 · Asia/Shanghai
            <span class="baseline-probe"></span></span>
          <button class="icon-action-button"><span class="ft-icon">
            <svg class="ft-icon-svg" viewBox="0 0 16 16">
              <path d="M2 2 L14 14" /></svg></span></button></div>""")
        page.add_style_tag(path=str(ROOT / "server/manager/web/styles/app.css"))
        metrics = page.evaluate("""() => {
          for (const probe of document.querySelectorAll('.baseline-probe')) {
            probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline';
          }
          const baselines = [...document.querySelectorAll('.baseline-probe')]
            .map(probe => probe.getBoundingClientRect().top);
          const icon = document.querySelector('.ft-icon').getBoundingClientRect();
          const button = document.querySelector('.icon-action-button').getBoundingClientRect();
          return {baselines, glyphBottom: icon.bottom - 2,
            upperGap: icon.top + 2 - button.top,
            lowerGap: button.bottom - (icon.bottom - 2)};
        }""")
        assert abs(metrics["baselines"][0] - metrics["baselines"][1]) <= 1
        assert abs(metrics["glyphBottom"] - metrics["baselines"][0]) <= 1
        assert abs(metrics["upperGap"] - metrics["lowerGap"]) <= 1
        browser.close()


def test_price_chart_keeps_open_interest_pane_when_overview_values_are_missing() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1100, "height": 850})
        page.set_content("<main id='root'></main>")
        page.add_script_tag(path=str(ROOT / "static/vendor/lightweight-charts/lightweight-charts.standalone.production.js"))
        page.add_script_tag(path=str(ROOT / "static/vendor/chart-workbench/chart-workbench.js"))
        page.evaluate("""() => {
          const start = Date.UTC(2025, 0, 1);
          const bars = Array.from({length: 10}, (_, i) => ({
            timestamp: start + i * 86400000, open: 100, high: 101,
            low: 99, close: 100, volume: 100, openInterest: null,
          }));
          const createChart = LightweightCharts.createChart;
          window.LightweightCharts = {...LightweightCharts, createChart: (...args) => {
            const chart = createChart(...args);
            window.__chart = chart;
            return chart;
          }};
          window.__handle = FTChartWorkbench.mountPriceChart(
            document.querySelector('#root'), {bars, hasOpenInterest: true,
              loadRange: async () => bars.slice(2, 4).map(bar =>
                ({...bar, openInterest: 500}))});
          window.__zoom = () => __handle.focusRange(
            start + 2 * 86400000, start + 3 * 86400000);
        }""")
        page.wait_for_selector("canvas")
        assert page.evaluate("window.__chart.panes().length") == 3
        page.evaluate("window.__zoom()")
        page.wait_for_function("window.__chart.panes()[2].getSeries()[0].data()"
                               ".some(row => row.value === 500)")
        oi = page.evaluate("""() => __chart.panes()[2].getSeries()[0].data()
          .filter(row => row.value !== undefined).map(row => row.value)""")
        assert oi == [500, 500]
        browser.close()


def test_price_chart_highlights_hovered_candle_and_opens_click_toolkit() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1100, "height": 850})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<main id='root' style='width:800px'></main>")
        page.add_style_tag(path=str(ROOT / "server/manager/web/styles/app.css"))
        page.add_script_tag(path=str(ROOT / "static/vendor/lightweight-charts/lightweight-charts.standalone.production.js"))
        page.evaluate("""() => {
          const library = LightweightCharts;
          window.LightweightCharts = {...library,
            createChart(...args) {
              window.__chart = library.createChart(...args);
              return window.__chart;
            },
            createSeriesMarkers(...args) {
              window.__hoverMarker = library.createSeriesMarkers(...args);
              return window.__hoverMarker;
            },
          };
        }""")
        page.add_script_tag(path=str(ROOT / "static/vendor/chart-workbench/chart-workbench.js"))
        page.evaluate("""() => {
          const start = Date.UTC(2025, 0, 1);
          const bars = Array.from({length: 10}, (_, i) => ({
            timestamp: start + i * 86400000, open: 100, high: 102.72,
            low: 99.2, close: 101.5, volume: 1000, openInterest: 500,
          }));
          window.__handle = FTChartWorkbench.mountPriceChart(
            document.querySelector('#root'), {bars, timeZone: 'Asia/Shanghai'});
          window.__candlePoint = () => {
            const node = document.querySelector('.ft-lightweight-price-canvas');
            const rect = node.getBoundingClientRect();
            const series = __chart.panes()[0].getSeries()[0];
            return {x: rect.left + __chart.timeScale().timeToCoordinate(
              bars[4].timestamp / 1000), y: rect.top + series.priceToCoordinate(101)};
          };
        }""")
        page.wait_for_selector("canvas")
        page.evaluate("""() => __handle.setRangeBands([
          {id:'early', start:Date.UTC(2025,0,1), end:Date.UTC(2025,0,4)},
          {id:'late', start:Date.UTC(2025,0,7), end:Date.UTC(2025,0,10)},
        ])""")
        assert page.locator(".ft-lightweight-range-band").count() == 2
        initial_range = page.evaluate("""() => {
          const range = __chart.timeScale().getVisibleRange();
          return [Number(range.from), Number(range.to)];
        }""")
        page.evaluate("window.__handle.selectRangeBand('late')")
        assert page.evaluate("""() => {
          const range = __chart.timeScale().getVisibleRange();
          return [Number(range.from), Number(range.to)];
        }""") == initial_range, "overlapping term selection must not move the viewport"
        page.evaluate("""() => __handle.focusRange(Date.UTC(2025,0,1), Date.UTC(2025,0,3))""")
        page.wait_for_function("""() => Number(__chart.timeScale().getVisibleRange()?.to)
          <= Date.UTC(2025,0,3) / 1000""")
        page.evaluate("window.__handle.selectRangeBand('late')")
        page.wait_for_function("""() => Number(__chart.timeScale().getVisibleRange()?.to)
          >= Date.UTC(2025,0,7) / 1000""")
        assert page.evaluate("""() => {
          const range = __chart.timeScale().getVisibleRange();
          return Number(range.to) >= Date.UTC(2025,0,7) / 1000;
        }"""), page.evaluate("""() => __chart.timeScale().getVisibleRange()""")
        page.evaluate("window.__handle.fitContent()")
        assert page.locator(".ft-lightweight-range-band").count() == 2
        assert page.evaluate("window.__hoverMarker.markers().length") == 0
        point = page.evaluate("window.__candlePoint()")
        page.mouse.move(point["x"], point["y"])
        page.wait_for_function("window.__hoverMarker.markers().length === 1")
        page.mouse.click(point["x"], point["y"])
        toolkit = page.get_by_role("dialog", name="蜡烛详情")
        toolkit.wait_for()
        expected = page.evaluate("""() => new Date(Date.UTC(2025, 0, 5))
          .toLocaleString(undefined, {timeZone: 'Asia/Shanghai'})""")
        assert toolkit.locator("header strong").inner_text() == expected
        page.evaluate("window.__handle.setTimeZone('UTC')")
        expected_utc = page.evaluate("""() => new Date(Date.UTC(2025, 0, 5))
          .toLocaleString(undefined, {timeZone: 'UTC'})""")
        assert toolkit.locator("header strong").inner_text() == expected_utc
        assert toolkit.get_by_text("1000").count() == 1
        assert toolkit.get_by_text("500").count() == 1
        assert toolkit.locator("dd").all_inner_texts()[:4] == [
            "100.00", "102.72", "99.20", "101.50",
        ]
        assert toolkit.locator("dd").first.evaluate(
            "node => getComputedStyle(node).whiteSpace") == "nowrap"
        toolkit.get_by_role("button", name="关闭").click()
        assert toolkit.count() == 0
        assert errors == []
        browser.close()


def test_product_term_structure_marks_chart_without_limiting_loaded_range() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1100, "height": 850})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<main id='content'></main>")
        page.add_script_tag(path=str(ROOT / "server/manager/web/core/shared-ui.js"))
        page.add_script_tag(path=str(ROOT / "server/manager/web/catalog/details.js"))
        page.evaluate("""async () => {
          window.__focused = [];
          window.__ranges = [];
          window.__navigated = [];
          FTProductPricePanel = {render(_context, mount) {
            const panel = document.createElement('div');
            panel.setTermRanges = ranges => __ranges.push(ranges);
            panel.selectTermRange = item => __focused.push(item);
            mount.append(panel);
            return new Promise(resolve => { window.__resolvePricePanel = () => resolve(panel); });
          }};
          const rows = Array.from({length: 20}, (_, i) => ({
            uid: `item-${i}`, contract: `标识-${i}`,
            start: `2025-01-${String(i + 1).padStart(2, '0')}`,
            end: `2025-02-${String(i + 1).padStart(2, '0')}`,
            has_data: true,
          }));
          const context = {
            content: document.querySelector('#content'), t: x => x,
            isRouteCurrent: () => true, activeNav() {}, setHeading() {},
            updateActiveTab() {}, navigate: path => __navigated.push(path),
            async api(path) {
              return path.includes('product-fields') ? {fields: [{name: 'A', value: 1}]}
                : {supports_term_structure: true, contracts: rows};
            },
          };
          const helpers = {
            sourceOf: () => 'server',
            load: async () => ({products: [{name: 'AU.SHF'}]}),
            catalogSwitch() {}, sourceSummary: () => document.createElement('div'),
            pathFor: path => path,
          };
          await FTProductDetails.productDetail(context, 'AU.SHF', helpers);
        }""")
        assert page.locator(".product-fields-section").count() == 1
        assert page.locator(".product-detail-page > :last-child").evaluate(
            "element => element.classList.contains('product-fields-section')")
        assert page.locator(".product-fields-section").evaluate("element => !element.open")
        assert page.locator(".product-term-structure tbody tr").count() == 15
        page.locator(".product-term-structure .shared-table-pagination button").last.click()
        assert page.locator(".product-term-structure tbody tr").count() == 5
        page.locator(".product-term-structure tbody tr").first.click(position={"x": 300, "y": 18})
        assert page.evaluate("window.__focused.length") == 0
        page.evaluate("window.__resolvePricePanel()")
        page.wait_for_function("window.__focused.length === 1")
        assert page.evaluate("window.__ranges.at(-1).length") == 20
        assert page.evaluate("window.__focused[0].uid") == "item-4"
        assert page.evaluate("window.__navigated.length") == 0
        page.locator(".product-term-structure tbody tr a").first.click()
        assert page.evaluate("window.__navigated.length") == 1
        assert errors == []
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


def test_asset_plot_keeps_legacy_order_snapshots_linked_to_fills() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page()
        page.set_content("<main></main>")
        for path in (
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        result = page.evaluate("""async () => {
          const t = 1700000000000;
          const orders = [
            {order_id:'done', product:'AU.SHF', timestamp:t, status:'filled',
              requested_quantity:1, active_leaves:0},
            {order_id:'partial', product:'AU.SHF', timestamp:t+1000,
              status:'partially_filled', requested_quantity:2, active_leaves:1},
            {order_id:'cancelled', product:'AU.SHF', timestamp:t+2000,
              status:'cancelled', requested_quantity:1, active_leaves:1},
            {order_id:'missing-fill', product:'AU.SHF', timestamp:t+3000,
              status:'filled', requested_quantity:1, active_leaves:0},
          ];
          const fills = [
            {order_id:'done', fill_id:'f1', product:'AU.SHF',
              timestamp:t+100, quantity:1, fill_price:101},
            {order_id:'partial', fill_id:'f2', product:'AU.SHF',
              timestamp:t+1100, quantity:1, fill_price:102},
          ];
          window.FTJobArtifactQuery = {timeSource(_context, path) {
            return {async load() {return {rows:path.includes('fill_detail_data')
              ? fills : orders};}};
          }};
          const state = {artifactsByName:new Map([
            ['order_detail_data',{name:'order_detail_data'}],
            ['fill_detail_data',{name:'fill_detail_data'}],
          ]),options:{jobID:'job'}};
          const data = await FTBacktestAssetPlot.loadEvents(
            {}, state, {product:'AU.SHF'}, t-1000, t+5000, 100);
          const linked = data.events.find(item => item.row.fill_id === 'f1');
          return {orders:data.events.filter(item =>
              item.artifact === 'order_detail_data').map(item => item.row.order_id),
            fills:data.events.filter(item =>
              item.artifact === 'fill_detail_data').map(item => item.row.fill_id),
            sourceCount:data.sourceCount,
            linkedDetail:FTBacktestAssetPlot.eventDetail(linked)};
        }""")
        # Legacy snapshots remain selectable so a fill can lead back to its
        # originating order; they are labelled as snapshots, not a dated close.
        assert result["orders"] == ["done", "partial", "cancelled", "missing-fill"]
        assert result["fills"] == ["f1", "f2"]
        assert result["sourceCount"] == 6
        assert "关联订单 done" in result["linkedDetail"]
        browser.close()


def test_asset_plot_order_flow_uses_recorded_phases_and_pool_scope() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page()
        page.set_content("<main></main>")
        for path in (
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        result = page.evaluate("""async () => {
          const t = 1700000000000;
          const order = {order_id:'o1', product:'AU.SHF', strategy:'S', side:'BUY',
            submitted_at:t, status:'cancelled', requested_quantity:2,
            lifecycle:[
              {kind:'action', action:'submit', order_id:'o1', timestamp:t},
              {kind:'attempt', attempt_id:'a1', order_id:'o1', timestamp:t+1000},
              {kind:'action', action:'cancel', order_id:'o1', timestamp:t+2000},
            ]};
          const fill = {order_id:'o1', fill_id:'f1', strategy:'S', timestamp:t+1000,
            side:'BUY', quantity:1, fill_price:101, account_id:'A', cash_pool_id:'P'};
          window.FTJobArtifactQuery = {timeSource(_context, path) {
            return {async load() {return {rows:path.includes('fill_detail_data')
              ? [fill] : [order]};}};
          }};
          const state = {artifactsByName:new Map([
            ['order_detail_data',{name:'order_detail_data'}],
            ['fill_detail_data',{name:'fill_detail_data'}],
          ]),options:{jobID:'job'}};
          const selected = {product:'AU.SHF', strategy:'S', filterMode:'cash_pool',
            cashPool:'P'};
          const value = await FTBacktestAssetPlot.loadEvents({}, state, selected,
            t-1000, t+3000, 100);
          const bars = [{timestamp:t, high:103, low:99, close:100},
            {timestamp:t+1000, high:103, low:99, close:100},
            {timestamp:t+2000, high:103, low:99, close:100}];
          const fillsOnly = FTBacktestAssetPlot.markerSeries(value.events, bars,
            () => {});
          const timeline = FTBacktestAssetPlot.orderTimeline({t:s=>s}, value.events,
            t-1000, t+3000, () => {});
          return {
            kinds:value.events.map(item => item.row.kind || item.artifact),
            visibleOrders:value.events.filter(item => item.artifact === 'order_lifecycle').length,
            poolFilter:FTBacktestAssetPlot.eventFilters(selected).cash_pool.values,
            fillAccount:value.events.find(item => item.row.fill_id === 'f1').row.account_id,
            defaultMarks:fillsOnly.reduce((n, item) => n + item.data.length, 0),
            orderRows:timeline.rows.length,
            orderNodes:timeline.series.at(-1).data.length,
            noOrderPriceMarkers:fillsOnly.every(item => !item.id.startsWith('asset-cancel')),
          };
        }""")
        assert result["kinds"] == ["action", "attempt", "fill_detail_data", "action"]
        assert result["visibleOrders"] == 3
        assert result["poolFilter"] == ["P"]
        assert result["fillAccount"] == "A"
        assert result["defaultMarks"] == 1
        assert result["orderRows"] == 1
        assert result["orderNodes"] == 3
        assert result["noOrderPriceMarkers"] is True
        browser.close()


def test_asset_plot_order_history_separates_orders_and_groups_same_time() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page()
        page.set_content("<main id='root'></main>")
        for path in (
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        result = page.evaluate("""() => {
          const t = 1700000000000;
          const events = [
            {artifact:'order_lifecycle',timestamp:t,row:{order_id:'A',kind:'action',action:'submit'}},
            {artifact:'order_lifecycle',timestamp:t+1000,row:{order_id:'A',kind:'attempt'}},
            {artifact:'fill_detail_data',timestamp:t+1000,row:{order_id:'A',fill_id:'F1',side:'BUY'}},
            {artifact:'order_lifecycle',timestamp:t+2000,row:{order_id:'B',kind:'action',action:'submit'}},
          ];
          let selected = [];
          const timeline = FTBacktestAssetPlot.orderTimeline({t:v=>v}, events,
            t, t+3000, items => {selected = items;});
          const node = timeline.series.at(-1).data.find(point =>
            point.custom.orderID === 'A' && point.custom.items.length === 2);
          timeline.series.at(-1).point.events.click.call(node);
          return {orderNames:timeline.rows.map(row => row[0]),
            nodes:timeline.rows.map(row => timeline.series.at(-1).data.filter(point =>
              point.custom.orderID === row[0]).length),
            selected:selected.map(item => item.row.fill_id || item.row.kind),
            lineTimes:timeline.series.find(series => series.id === 'asset-order-line-A')
              .data.map(point => point[0])};
        }""")
        assert result["orderNames"] == ["B", "A"]
        assert result["nodes"] == [1, 2]
        assert result["selected"] == ["attempt", "F1"]
        assert result["lineTimes"] == [1700000000000, 1700000001000]
        browser.close()


def test_asset_plot_order_history_loads_more_without_mixing_orders() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page()
        page.set_content("<main id='root'></main>")
        for path in (
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        value = page.evaluate("""() => {
          const t = 1700000000000;
          const events = Array.from({length: 13}, (_, index) => ({
            artifact:'order_lifecycle', timestamp:t+index*1000,
            row:{order_id:`order-${index}`,kind:'submitted'},
          }));
          const first = FTBacktestAssetPlot.orderTimeline({t:v=>v}, events,
            t, t+15000, () => {}, {limit:10});
          const expanded = FTBacktestAssetPlot.orderTimeline({t:v=>v}, events,
            t, t+15000, () => {}, {limit:20});
          return {first:first.rows.length, expanded:expanded.rows.length,
            unique:new Set(expanded.rows.map(row=>row[0])).size,
            noMore:expanded.rows.length === expanded.total};
        }""")
        assert value == {"first": 10, "expanded": 13, "unique": 13,
                         "noMore": True}
        browser.close()


def test_asset_plot_reuses_complete_nested_range_without_requerying() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page()
        page.set_content("<main id='root'></main>")
        for path in (
            "server/manager/web/core/shared-ui.js",
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        result = page.evaluate("""async () => {
          const t = Date.parse('2025-04-11T10:00:00Z');
          const calls = {events: 0, prices: 0};
          let pending = 0;
          let maxConcurrent = 0;
          window.FTJobArtifactQuery = {timeSource(_context, path) {
            return {async load() {
              calls.events++;
              pending++;
              maxConcurrent = Math.max(maxConcurrent, pending);
              await new Promise(resolve => setTimeout(resolve, 20));
              pending--;
              return {rows: path.includes('order_detail_data') ? [{
                order_id: 'order-1', product: 'AU.SHF', strategy: 'A', timestamp: t,
                active_leaves: 0, terminal_unfilled: 0,
              }] : [], sampling: {visible_rows: path.includes('order_detail_data') ? 1 : 0}};
            }};
          }};
          window.FTMarketData = {
            rangeRequest(request, minimum, maximum, maxPoints) {
              return {...request, minimum, maximum, maxPoints};
            },
            async prices() {
              calls.prices++;
              return {payload: {data: [{timestamp: t, open: 1, high: 2,
                low: 0, close: 1, volume: 10}], count: 1, returned_count: 1}};
            },
          };
          const timestampOf = FTPriceChart.timestampOf;
          window.FTPriceChart = {timestampOf, render(_context, mount, payload, display) {
            window.__display = display;
            mount.dataset.ready = 'true';
            return {destroy() {}, xAxis: [{}], yAxis: [{}]};
          }};
          const state = {
            selectedAsset: {product: 'AU.SHF', strategy: 'A', timestamp: t},
            assetPlotDiscovery: {status: 'ready'},
            artifactsByName: new Map([
              ['order_detail_data', {name:'order_detail_data'}],
              ['fill_detail_data', {name:'fill_detail_data'}],
            ]),
            options: {jobID: 'test', configuration: {}},
          };
          const root = FTBacktestAssetPlot.render({t:(value, options) =>
            options === undefined ? value : String(options)}, state);
          document.querySelector('#root').append(root);
          await new Promise((resolve, reject) => {
            const deadline = Date.now() + 3000;
            const poll = () => {
              if (window.__display) resolve();
              else if (Date.now() >= deadline) reject(new Error('asset plot did not load'));
              else setTimeout(poll, 10);
            };
            poll();
          });
          const cold = {...calls};
          const nested = await window.__display.loadRange(t - 1000, t + 1000,
            {maxPoints: 1200, visibleMinimum: t - 1000, visibleMaximum: t + 1000});
          const headings = [...root.querySelectorAll('.backtest-asset-events thead th')]
            .map(node => node.textContent);
          const detail = FTBacktestAssetPlot.eventDetail(nested.__assetEvents[0]);
          const firstRow = root.querySelector('.backtest-asset-events tbody tr').textContent;
          const warm = {...calls};
          await window.__display.loadRange(t + 31 * 86400000, t + 32 * 86400000,
            {maxPoints: 1200});
          return {cold, warm, outside: {...calls},
            nestedCount: nested.__assetEvents.length, maxConcurrent,
            headings, detail, firstRow};
        }""")
        assert result["cold"] == {"events": 3, "prices": 1}
        assert result["warm"] == result["cold"]
        assert result["outside"] == {"events": 6, "prices": 2}
        assert result["nestedCount"] == 1
        assert result["maxConcurrent"] == 2
        assert result["headings"] == [
            "时间", "订单阶段 / ID", "策略", "账户 / 资金池", "方向 / 状态",
            "数量", "价格", "剩余", "手续费", "账本变化",
        ]
        assert "订单最终剩余 0" in result["detail"]
        assert "0（订单最终）" in result["firstRow"]
        assert "事件后剩余" not in result["detail"]
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
              keepOtherSeriesVisible: true, assetMode: true,
              preserveSourceBars: true,
              overlaySeries(_payload, normalizedBars) {
                return FTBacktestAssetPlot.markerSeries(events, normalizedBars, () => {});
              },
            });
            const timeline = FTBacktestAssetPlot.orderTimeline({t:v=>v}, events,
              start, start + 9 * 86400000, () => {});
          const buy = chart.series.find(series => series.options.id === 'asset-buy');
          const sell = chart.series.find(series => series.options.id === 'asset-sell');
          buy.points[0].onMouseOver();
          return {
            orderCount: timeline.rows.length,
            buyCount: buy.points[0].options.custom.items.length,
            markerAxis: buy.yAxis.index,
            candleAxis: chart.series[0].yAxis.index,
            buyBelowWick: buy.points[0].plotY >= chart.series[0].points[2].plotLow + 9,
            sellAboveWick: sell.points[0].plotY <= chart.series[0].points[4].plotHigh - 9,
            noOrderSeries: chart.series.every(series => series.options.id !== 'asset-submitted'),
            sellCount: sell.points.length,
            inactiveOpacity: sell.options.states.inactive.opacity,
            markerTime: buy.points[0].x,
            candleTime: bars[2].timestamp,
            tooltip: chart.tooltip.label?.text?.textStr || "",
          };
        }""")
        assert result["orderCount"] == 1
        assert result["buyCount"] == 1
        assert result["markerAxis"] == 0
        assert result["candleAxis"] == 0
        assert result["buyBelowWick"]
        assert result["sellAboveWick"]
        assert result["noOrderSeries"]
        assert result["sellCount"] == 1
        assert result["inactiveOpacity"] == 1
        assert result["markerTime"] == result["candleTime"]
        assert "成交量" in result["tooltip"]
        assert "持仓量" in result["tooltip"]
        browser.close()


def test_asset_plot_markers_keep_a_pixel_gap_from_nearby_candles_at_each_zoom() -> None:
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
          const bars = Array.from({length: 360}, (_, index) => ({
            timestamp: start + index * 60000,
            open: 100, high: index === 181 ? 112 : 101,
            low: index === 179 ? 88 : 99, close: 100, volume: 10,
          }));
          const events = ['buy', 'sell'].map((side, index) => ({
            artifact: 'fill_detail_data', timestamp: bars[180].timestamp,
            row: {side, fill_price: 100, fill_id: `f${index}`},
          }));
          const chart = FTPriceChart.render({t: value => value},
            document.querySelector('#chart'), {data: bars, freq: 'MIN1'}, {
              assetMode: true, preserveSourceBars: true,
              overlaySeries(_payload, normalizedBars) {
                return FTBacktestAssetPlot.markerSeries(events, normalizedBars, () => {});
              },
            });
          const gaps = () => {
            const buy = chart.series.find(series => series.options.id === 'asset-buy').points[0];
            const sell = chart.series.find(series => series.options.id === 'asset-sell').points[0];
            const nearby = chart.series[0].points.filter(candle =>
              Math.abs(candle.plotX - buy.plotX) <= 10);
            return {
              buy: buy.plotY - Math.max(...nearby.map(item => item.plotLow)),
              sell: Math.min(...nearby.map(item => item.plotHigh)) - sell.plotY,
              nearby: nearby.length,
            };
          };
          const wide = gaps();
          chart.xAxis[0].setExtremes(bars[174].timestamp, bars[186].timestamp, true);
          return {wide, zoomed: gaps()};
        }""")
        assert result["wide"]["nearby"] > 1
        assert result["wide"]["buy"] >= 9
        assert result["wide"]["sell"] >= 9
        assert result["zoomed"]["buy"] >= 9
        assert result["zoomed"]["sell"] >= 9
        browser.close()


def test_asset_plot_tooltip_retains_market_bar_and_zoom_reaches_source_interval() -> None:
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
          const start = Date.UTC(2025, 3, 24);
          const bars = Array.from({length: 90}, (_, index) => ({
            timestamp: start + index * 60000, open: 100 + index,
            high: 102 + index, low: 99 + index, close: 101 + index,
            volume: 10 + index, open_interest: 20 + index,
          }));
          const events = [
            {artifact: 'fill_detail_data', timestamp: start + 30 * 60000,
              row: {side: 'buy', fill_price: 131, fill_id: 'f30'}},
            {artifact: 'fill_detail_data', timestamp: start + 30 * 60000,
              row: {side: 'sell', fill_price: 132, fill_id: 'f31'}},
          ];
          let activeTime = null;
          let chart;
          chart = FTPriceChart.render({t: value => value},
            document.querySelector('#chart'), {data: bars, freq: 'MIN1'}, {
              assetMode: true, preserveSourceBars: true,
              keepOtherSeriesVisible: true,
              eventTooltipFields(item) { return [['手续费', item.row.fill_id]]; },
              tooltipEventItems(timestamp) { return timestamp === activeTime ? events : []; },
              overlaySeries(_payload, normalizedBars) {
                return FTBacktestAssetPlot.markerSeries(events, normalizedBars,
                  (_items, point) => { activeTime = point.x; chart.tooltip.refresh(point); });
              },
            });
          const marker = chart.series.find(series => series.options.id === 'asset-buy')
            .points[0];
          marker.onMouseOver();
          const hoverTooltip = chart.tooltip.label?.text?.textStr || '';
          marker.firePointEvent('click');
          const markerTooltip = chart.tooltip.label?.text?.textStr || '';
          const disclosures = [...document.querySelectorAll('.highcharts-tooltip details')];
          const before = disclosures.map(item => item.open);
          disclosures[1]?.querySelector('summary')?.click();
          const after = disclosures.map(item => item.open);
          const candle = chart.series[0].points.find(point => point.x === marker.x);
          candle.onMouseOver();
          const candleTooltip = chart.tooltip.label?.text?.textStr || '';
          chart.xAxis[0].setExtremes(start + 30 * 60000,
            start + 31 * 60000, true);
          return {hoverTooltip, markerTooltip, candleTooltip, before, after,
            actionCount: document.querySelectorAll('.asset-tooltip-price-toggle').length,
            minRange: chart.xAxis[0].minRange,
            zoomSpan: chart.xAxis[0].max - chart.xAxis[0].min,
            candleGrouping: chart.series[0].options.dataGrouping.enabled,
            volumeGrouping: chart.series[1].options.dataGrouping.enabled};
        }""")
        for tooltip in (result["markerTooltip"], result["candleTooltip"]):
            for label in ("开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"):
                assert label in tooltip
            assert "130" in tooltip  # event candle open, not an adjacent bar
        assert "2 笔" in result["markerTooltip"]
        assert "交易事件" not in result["hoverTooltip"]
        assert result["actionCount"] == 2
        assert result["before"] == [True, False]
        assert result["after"] == [True, True]
        assert "手续费" in result["markerTooltip"]
        assert result["minRange"] == 60000
        assert result["zoomSpan"] == 60000
        assert result["candleGrouping"] is False
        assert result["volumeGrouping"] is False
        browser.close()


def test_asset_order_track_shares_chart_axis_and_range_refreshes_market_tooltip() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.set_content("<div id='chart' style='width:1100px'></div>")
        for path in (
            "static/vendor/highcharts/highstock.min.js",
            "server/manager/web/core/highcharts-range-loader.js",
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        result = page.evaluate("""() => {
          const start = Date.UTC(2025, 3, 24);
          const bars = offset => Array.from({length: 20}, (_, index) => ({
            timestamp:start + (offset + index) * 60000,
            open:100 + index, high:102 + index, low:99 + index, close:101 + index,
            volume:1000 + offset + index, open_interest:2000 + offset + index,
          }));
          const event = {artifact:'order_lifecycle',timestamp:start + 60000,
            row:{order_id:'order-1',kind:'action',action:'submit'}};
          const display = {assetMode:true, preserveSourceBars:true,
            orderTimeline(payload) {
              return FTBacktestAssetPlot.orderTimeline({t:s=>s},
                payload.__assetEvents || [], start, start+40*60000, () => {});
            }};
          const first = {data:bars(0), freq:'MIN1', __assetEvents:[event]};
          const chart = FTPriceChart.render({t:s=>s}, document.querySelector('#chart'),
            first, display);
          const order = chart.series.find(series => series.options.id === 'asset-order-nodes');
          const sharedAxis = order.xAxis === chart.series[0].xAxis;
          const nodeTime = order.points[0].x;
          const zoom = chart.options.chart.zooming;
          const next = {data:bars(20), freq:'MIN1', __assetEvents:[]};
          const nextMount = document.createElement('div');
          nextMount.style.width = '1100px';
          document.body.append(nextMount);
          const nextChart = FTPriceChart.render({t:s=>s}, nextMount, next, display);
          const options = nextChart.userOptions;
          FTHighchartsRangeLoader.replaceVisibleSeries(chart,options,
            start+20*60000,start+39*60000);
          const formatterUpdated = chart.tooltip.options.formatter.call({x:start+21*60000});
          chart.xAxis[0].setExtremes(start+30*60000,start+31*60000,true,false,
            {trigger:'ft-data-refresh'});
          return {sharedAxis,nodeTime,formatterUpdated,
            wheelZoom:zoom.mouseWheel.enabled, selectionZoom:zoom.type,
            minRange:chart.xAxis[0].minRange,
            span:chart.xAxis[0].max-chart.xAxis[0].min};
        }""")
        assert result["sharedAxis"] is True
        assert result["nodeTime"] == 1745452860000
        assert result["wheelZoom"] is True
        assert result["selectionZoom"] == "x"
        assert "成交量: <b>1,021</b>" in result["formatterUpdated"]
        assert "持仓量: <b>2,021</b>" in result["formatterUpdated"]
        assert result["minRange"] == 60000
        assert result["span"] == 60000
        browser.close()


def test_asset_plot_clicked_toolkit_toggles_independent_trade_price_lines() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1200, "height": 850})
        page.set_content("<main id='root'></main>")
        for path in (
            "static/vendor/highcharts/highstock.min.js",
            "server/manager/web/core/shared-ui.js",
            "server/manager/web/catalog/shared/multi-select-filter/index.js",
            "server/manager/web/core/highcharts-range-loader.js",
            "server/manager/web/core/price-chart.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""() => {
          const start = Date.UTC(2025, 3, 10, 9);
          const bars = Array.from({length: 80}, (_, index) => ({
            timestamp: start + index * 60000, open: 100 + index * .1,
            high: 102 + index * .1, low: 99 + index * .1,
            close: 101 + index * .1, volume: 100 + index,
            open_interest: 200 + index,
          }));
          const fills = [
            {instrument: 'AU', timestamp: start + 20 * 60000,
              fill_id: 'f1', side: 'BUY', fill_price: 101, quantity: 1},
            {instrument: 'AU', timestamp: start + 20 * 60000,
              fill_id: 'f2', side: 'BUY', fill_price: 103, quantity: 1},
          ];
          FTJobArtifactQuery = {timeSource() { return {async load() {
            return {rows: fills, sampling: {}};
          }}; }};
          FTMarketData = {
            rangeRequest(request) { return {...request}; },
            async prices(_context, request) {
              window.__requestedAnchors = request.anchor_timestamps;
              return {payload: {data: bars, freq: 'MIN1'}};
            },
          };
          const state = {
            target: document.querySelector('#root'),
            options: {jobID: 'test-job', configuration: {freq: 'MIN1'}},
            artifactsByName: new Map([['fill_detail_data', {name: 'fill_detail_data'}]]),
            assetPlotDiscovery: {status: 'ready', products: ['AU'], strategies: [], accounts: []},
            selectedAsset: {product: 'AU', contractUID: '', timestamp: fills[0].timestamp},
            rerender() {},
          };
          document.querySelector('#root').append(FTBacktestAssetPlot.render(
            {t: value => value}, state,
          ));
        }""")
        page.wait_for_function("document.querySelector('.backtest-asset-chart')?.__ftPriceChart")
        assert page.evaluate("window.__requestedAnchors.length") == 1
        page.evaluate("""() => {
          const chart = document.querySelector('.backtest-asset-chart').__ftPriceChart;
          chart.series.find(series => series.options.id === 'asset-buy').points[0]
            .onMouseOver();
        }""")
        assert page.locator(".asset-tooltip-price-toggle").count() == 0
        page.evaluate("""() => {
          const chart = document.querySelector('.backtest-asset-chart').__ftPriceChart;
          chart.series.find(series => series.options.id === 'asset-buy').points[0]
            .firePointEvent('click');
        }""")
        buttons = page.locator(".asset-tooltip-price-toggle")
        assert buttons.count() == 2
        buttons.first.click()
        assert page.evaluate("document.querySelector('.backtest-asset-chart').__ftPriceChart._ftTradePriceLineCount") == 1
        page.locator(".asset-tooltip-event").nth(1).locator("summary").click()
        buttons.nth(1).click()
        assert page.evaluate("document.querySelector('.backtest-asset-chart').__ftPriceChart._ftTradePriceLineCount") == 2
        buttons.first.click()
        assert page.evaluate("document.querySelector('.backtest-asset-chart').__ftPriceChart._ftTradePriceLineCount") == 1
        browser.close()


def test_asset_plot_lazy_mounts_lightweight_chart_with_job_events() -> None:
    with _playwright() as playwright:
        browser = _launch_chromium(playwright)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<main id='root'></main>")
        page.add_style_tag(content=".ft-asset-chart-canvas {width:100%;height:640px}")
        for path in (
            "server/manager/web/core/shared-ui.js",
            "server/manager/web/core/price-chart.js",
            "static/vendor/lightweight-charts/lightweight-charts.standalone.production.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""() => {
          const source = window.LightweightCharts;
          window.LightweightCharts = {...source, createChart(...args) {
            window.__chartApi = source.createChart(...args);
            return window.__chartApi;
          }};
        }""")
        for path in (
            "static/vendor/chart-workbench/chart-workbench.js",
            "server/manager/web/test-modules/backtest/results/asset-plot.js",
        ):
            page.add_script_tag(path=str(ROOT / path))
        page.evaluate("""() => {
          const start = Date.UTC(2025, 3, 10, 9);
          const bars = Array.from({length: 80}, (_, i) => ({
            timestamp: start + i * 60000, open: 100 + i * .1,
            high: 102 + i * .1, low: 99 + i * .1,
            close: 101 + i * .1, volume: 100 + i,
            open_interest: 200 + i,
          }));
          const order = {instrument: 'AU', order_id: 'o1', side: 'BUY',
            timestamp: start + 20 * 60000, status: 'filled',
            lifecycle: [{timestamp: start + 20 * 60000, kind: 'submitted'}]};
          const fills = [{instrument: 'AU', order_id: 'o1', fill_id: 'f1',
            timestamp: start + 21 * 60000, side: 'BUY', fill_price: 103,
            quantity: 1, fee: 2}, {instrument: 'AU', order_id: 'o1', fill_id: 'f2',
            timestamp: start + 21 * 60000, side: 'BUY', fill_price: 104,
            quantity: 1, fee: 2}];
          window.__chartGroups = [];
          FTStaticLoader = {async loadGroups(groups) { window.__chartGroups.push(...groups); }};
          FTJobArtifactQuery = {timeSource(_context, path) { return {async load() {
            return {rows: path.includes('order_detail_data') ? [order] : fills,
              sampling: {}};
          }}; }};
          FTMarketData = {
            rangeRequest(request, minimum, maximum, maxPoints) {
              return {...request, minimum, maximum, maxPoints};
            },
            async prices() { return {payload: {data: bars, freq: 'MIN1',
              count: bars.length, returned_count: bars.length}}; },
          };
          const state = {
            target: document.querySelector('#root'),
            options: {jobID: 'test-job', configuration: {freq: 'MIN1'}},
            artifactsByName: new Map([
              ['order_detail_data', {name:'order_detail_data'}],
              ['fill_detail_data', {name:'fill_detail_data'}],
            ]),
            assetPlotDiscovery: {status:'ready', products:['AU'],
              strategies:[], accounts:[], cashPools:[]},
            selectedAsset: {product:'AU', timestamp:start + 21 * 60000},
            rerender() {},
          };
          document.querySelector('#root').append(FTBacktestAssetPlot.render(
            {t:value=>value}, state));
        }""")
        page.wait_for_selector(".ft-asset-chart-canvas canvas")
        page.wait_for_function("document.querySelector('.ft-asset-chart-legend')?.textContent.includes('1/1')")
        assert page.evaluate("window.__chartGroups") == ["chart-workbench-asset"]
        assert page.locator(".backtest-asset-chart .highcharts-container").count() == 0
        assert page.locator(".backtest-asset-events thead th").count() == 10
        assert page.evaluate("window.__chartApi.panes().length") == 4
        assert page.evaluate("window.__chartApi.panes()[1].getSeries().length") == 1
        assert page.evaluate("window.__chartApi.panes()[2].getSeries().length") == 1
        marker = page.evaluate("""() => {
          const time = Date.UTC(2025, 3, 10, 9) / 1000 + 21 * 60;
          const chart = window.__chartApi;
          const series = chart.panes()[0].getSeries()[0];
          const canvas = document.querySelector('.ft-asset-chart-canvas')
            .getBoundingClientRect();
          return {x:canvas.left + chart.timeScale().timeToCoordinate(time),
            y:canvas.top + series.priceToCoordinate(99 + 21 * .1) + 12};
        }""")
        page.mouse.click(marker["x"], marker["y"])
        page.wait_for_selector(".ft-asset-chart-events details")
        assert page.locator(".ft-asset-chart-events details").count() == 2
        assert page.locator(".backtest-asset-inspector-mount").inner_html() == ""
        buttons = page.locator(".ft-asset-chart-events button")
        buttons.first.click()
        assert "移除价格线" in buttons.first.inner_text()
        page.locator(".ft-asset-chart-events summary").nth(1).click()
        buttons.nth(1).click()
        assert "移除价格线" in buttons.nth(1).inner_text()
        assert page.evaluate("window.__chartApi.panes()[0].getSeries()[0].priceLines().length") == 2
        assert errors == []
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
        assert value["labels"] == ["筛选维度", "策略", "品种 / 合约"]
        assert value["renderCount"] == 1
        assert value["filters"]["account"]["values"] == ["ledger-1"]
        browser.close()
