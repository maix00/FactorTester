/**
 * IC 测试模块独立脚本（重写版）
 * 支持因子级选择和频率配置
 */
(function() {
    // 全局变量
    let factorFamilyAlias = window.factorFamilyAlias || '';
    let factorList = [];  // 存储因子列表 [{alias, name, freq}]
    let icContractSelection = {}; // key: `${subId}-${idx}` => Set(contract_uid)
    let icHoverBandState = {}; // key: `${subId}-${idx}` => { from, to }

    if (typeof Highcharts !== 'undefined') {
        Highcharts.setOptions({
            global: { useUTC: false }
        });
    }

    // 辅助函数：获取因子列表（从后端 API）
    async function fetchFactorList() {
        if (!factorFamilyAlias) return [];
        try {
            const res = await fetch(`/api/factor_list?factor_family_alias=${encodeURIComponent(factorFamilyAlias)}`);
            const data = await res.json();
            if (data.success) {
                factorList = data.factors;
                window.factorList = factorList;   // 暴露全局
                return factorList;
            } else {
                console.error('获取因子列表失败:', data.error);
                return [];
            }
        } catch (err) {
            console.error('获取因子列表异常:', err);
            return [];
        }
    }

    function drawComparisonChart(containerId, priceData, factorData, returnData, productName, factorName, factorAlias, subId, product) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container) return;

        // 从 containerId 中提取 idx（格式：factor-chart-{subId}-{idx}）
        const parts = containerId.split('-');
        const idx = parts[parts.length - 1];

        const showVolume = document.getElementById(`show-volume-${subId}-${idx}`)?.checked;
        const showOI = document.getElementById(`show-oi-${subId}-${idx}`)?.checked;
        const hasOI = priceData.OPEN_INTEREST && priceData.OPEN_INTEREST.length > 0;
        const volumeOn = showVolume && priceData.VOLUME && priceData.VOLUME.length > 0;
        const oiOn = showOI && hasOI;

        const _parseTs = ts => typeof ts === 'string' ? new Date(ts + 'T00:00:00').getTime() : ts;
        const isDaily = factorData.dates.length > 0 && typeof factorData.dates[0] === 'string';
        const _fmtHeader = isDaily
            ? x => Highcharts.dateFormat('%Y-%m-%d', x)
            : x => Highcharts.dateFormat('%Y-%m-%d %H:%M', x);
        function groupName(group, name) {
            return `[${group}] ${name}`;
        }
        function priceSeriesName() {
            const base = productName || priceData.product || '价格序列';
            if (priceData.is_term_contract) return `${base} 合约价格`;
            return `${base} 价格`;
        }
        const ohlcData     = priceData.dates.map((ts, i) => [_parseTs(ts), priceData.OPEN[i], priceData.HIGH[i], priceData.LOW[i], priceData.CLOSE[i]]);
        const factorValues = factorData.dates.map((ts, i) => [_parseTs(ts), factorData.values[i]]);
        const returnValues = returnData.dates.map((ts, i) => [_parseTs(ts), returnData.values[i]]);
        const contractSeriesList = Array.isArray(priceData.contract_series_list) ? priceData.contract_series_list : [];

        // 动态计算各面板布局（gap=0.5%，总和精确=100%）
        let priceH, factorH, returnH, extraH;
        if (volumeOn && oiOn) {
            // 5联: 48+20+12+9+9 + 4×0.5 = 100
            priceH = 48; factorH = 20; returnH = 12; extraH = 9;
        } else if (volumeOn || oiOn) {
            // 4联: 52+22+14+10 + 3×0.5 = 99.5 ≈ 100
            priceH = 52; factorH = 22; returnH = 14; extraH = 10;
        } else {
            // 3联: 56+24+18 + 2×0.5 = 99
            priceH = 56; factorH = 24; returnH = 18;
        }

        // 构建 yAxis
        let gap = 0.5;
        const yAxis = [
            {
                labels: { format: '{value:.2f}', align: 'right', x: -8 },
                title: { text: '价格' },
                height: priceH + '%',
                resize: { enabled: true }
            },
            {
                labels: { format: '{value:.4f}', align: 'right', x: -8 },
                title: { text: '因子值' },
                top: (priceH + gap) + '%',
                height: factorH + '%',
                opposite: true,
                offset: 0,
            },
            {
                labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; }, align: 'right', x: -8 },
                title: { text: '下一期收益率' },
                top: (priceH + factorH + gap * 2) + '%',
                height: returnH + '%',
                opposite: true,
                offset: 0,
            }
        ];

        // 构建 series
        const series = [
            {
                name: groupName('价格', priceSeriesName()),
                type: 'candlestick',
                data: ohlcData,
                yAxis: 0,
                zIndex: 10,
                legendIndex: 10,
                color: '#1F2937',
                lineColor: '#1F2937',
                upColor: '#FFF176',
                upLineColor: '#1F2937',
            },
            {
                name: groupName('指标', '因子值'),
                type: 'line',
                data: factorValues,
                yAxis: 1,
                color: '#FF5722',
                id: 'factor',
                legendIndex: 200,
            },
            {
                name: groupName('指标', '下一期收益率'),
                type: 'line',
                data: returnValues,
                yAxis: 2,
                color: '#4CAF50',
                id: 'return',
                legendIndex: 210,
            }
        ];

        // 同一品种不同期限合约叠加：使用价格查看模块同链路 /api/get_price_data(contract_uid)
        const palette = ['#7E57C2', '#26A69A', '#FF7043', '#5C6BC0', '#EC407A', '#66BB6A'];
        if (contractSeriesList.length > 0) {
            contractSeriesList.forEach(function(s, i) {
                if (!s || !Array.isArray(s.data) || s.data.length === 0) return;
                const fromTs = s.data[0] && s.data[0][0] != null ? s.data[0][0] : null;
                const toTs = s.data[s.data.length - 1] && s.data[s.data.length - 1][0] != null ? s.data[s.data.length - 1][0] : null;
                series.push({
                    name: groupName('期限价格', s.name),
                    type: 'candlestick',
                    data: s.data,
                    yAxis: 0,
                    zIndex: 2,
                    legendIndex: 30 + i,
                    custom: { isContractOverlay: true, rangeFrom: fromTs, rangeTo: toTs },
                    color: palette[i % palette.length],
                    lineWidth: 1,
                    upColor: 'transparent',
                    upLineColor: palette[i % palette.length],
                    lineColor: palette[i % palette.length],
                    fillColor: 'transparent',
                });
            });
        }

        let nextTop = priceH + factorH + returnH + gap * 3;
        let nextIdx = 3;

        if (volumeOn) {
            const volData = priceData.dates.map((ts, i) => [_parseTs(ts), priceData.VOLUME[i]]);
            yAxis.push({
                labels: { format: '{value:.0f}', align: 'right', x: -8 },
                title: { text: '成交量' },
                top: nextTop + '%',
                height: extraH + '%',
                opposite: true,
                offset: 0,
            });
            series.push({
                name: groupName('成交量', productName),
                type: 'column',
                data: volData,
                yAxis: nextIdx,
                color: '#90CAF9',
                id: 'volume',
                legendIndex: 100,
            });
            contractSeriesList.forEach(function(s, i) {
                if (!s || !Array.isArray(s.volume) || s.volume.length === 0) return;
                series.push({
                    name: groupName('成交量', s.name),
                    type: 'column',
                    data: s.volume,
                    yAxis: nextIdx,
                    color: palette[i % palette.length],
                    opacity: 0.35,
                    id: `contract-volume-${i}`,
                    legendIndex: 110 + i,
                });
            });
            nextTop += extraH + gap;
            nextIdx++;
        }

        if (oiOn) {
            const oiData = priceData.dates.map((ts, i) => [_parseTs(ts), priceData.OPEN_INTEREST[i]]);
            yAxis.push({
                labels: { format: '{value:.0f}', align: 'right', x: -8 },
                title: { text: '持仓量' },
                top: nextTop + '%',
                height: extraH + '%',
                opposite: true,
                offset: 0,
            });
            series.push({
                name: groupName('持仓量', productName),
                type: 'line',
                data: oiData,
                yAxis: nextIdx,
                color: '#E91E63',
                id: 'oi',
                legendIndex: 150,
            });
            contractSeriesList.forEach(function(s, i) {
                if (!s || !Array.isArray(s.open_interest) || s.open_interest.length === 0) return;
                series.push({
                    name: groupName('持仓量', s.name),
                    type: 'line',
                    data: s.open_interest,
                    yAxis: nextIdx,
                    color: palette[i % palette.length],
                    dashStyle: 'ShortDot',
                    opacity: 0.8,
                    id: `contract-oi-${i}`,
                    legendIndex: 160 + i,
                });
            });
        }

        const chart = Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: `${productName} — ${factorName}` },
            legend: {
                enabled: true,
                layout: 'horizontal',
                align: 'center',
                verticalAlign: 'bottom',
                itemDistance: 18,
                maxHeight: 96,
                navigation: { enabled: true },
            },
            plotOptions: {
                series: {
                    point: {
                        events: {
                            click: function() {
                                if (this.series.options.id === 'factor') {
                                    openFactorDistribution(subId, factorName, factorAlias, this.x, product);
                                }
                            }
                        }
                    }
                }
            },
            xAxis: { type: 'datetime' },
            yAxis: yAxis,
            tooltip: {
                split: true,
                formatter: function() {
                    const header = _fmtHeader(this.x);
                    return [header].concat(this.points.map(pt => {
                        if (pt.series.type === 'candlestick') {
                            const p = pt.point;
                            return `${pt.series.name}<br/>开: <b>${p.open.toFixed(2)}</b>  高: <b>${p.high.toFixed(2)}</b><br/>` +
                                   `低: <b>${p.low.toFixed(2)}</b>  收: <b>${p.close.toFixed(2)}</b>`;
                        }
                        if (pt.series.options.id === 'factor') {
                            return `${pt.series.name}: <b>${pt.y.toFixed(4)}</b>`;
                        }
                        if (pt.series.options.id === 'return') {
                            return `${pt.series.name}: <b>${(pt.y * 100).toFixed(2)}%</b>`;
                        }
                        if (String(pt.series.options.id || '').indexOf('volume') >= 0) {
                            return `${pt.series.name}: <b>${pt.y.toFixed(0)}</b>`;
                        }
                        if (String(pt.series.options.id || '').indexOf('oi') >= 0) {
                            return `${pt.series.name}: <b>${pt.y.toFixed(0)}</b>`;
                        }
                        return `${pt.series.name}: <b>${pt.y}</b>`;
                    }));
                }
            },
            series: series,
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: true }
        });
        window._icComparisonChartRefs = window._icComparisonChartRefs || {};
        window._icComparisonChartRefs[`${subId}-${idx}`] = chart;
        bindLegendHoverHighlight(chart, subId, idx);
    }

    function bindLegendHoverHighlight(chart, subId, idx) {
        if (!chart || !Array.isArray(chart.series)) return;
        chart.series.forEach(function(s) {
            const custom = s && s.options ? s.options.custom : null;
            if (!custom || !custom.isContractOverlay) return;
            const legendEl = s.legendItem && s.legendItem.element;
            if (!legendEl || legendEl.__icHoverBound) return;

            legendEl.addEventListener('mouseenter', function() {
                window.icHighlightContractRange(subId, idx, custom.rangeFrom, custom.rangeTo);
            });
            legendEl.addEventListener('mouseleave', function() {
                window.icHighlightContractRange(subId, idx, null, null);
            });
            legendEl.__icHoverBound = true;
        });
    }

    // Volume / OI 复选框切换时重绘对比图（全局函数，供 onchange 调用）
    window.icRedrawComparison = function(subId, idx) {
        const cacheKey = `${subId}-${idx}`;
        const cache = window._icComparisonCache && window._icComparisonCache[cacheKey];
        if (!cache) return;
        const { priceData, factorData, returnData, product, factorName, factorAlias } = cache;
        const chartDiv = document.getElementById(`factor-chart-${subId}-${idx}`);
        if (chartDiv) {
            chartDiv.style.height = '800px';
            drawComparisonChart(`factor-chart-${subId}-${idx}`, priceData, factorData, returnData, product, factorName, factorAlias, subId, product);
        }
    };

    function updateComparisonOptionControls(subId, factorIdx, priceApi, priceData) {
        const supportsAdjusted = !!(priceApi && priceApi.supports_adjusted);
        const adjustWrap = document.getElementById(`adjust-wrap-${subId}-${factorIdx}`);
        if (adjustWrap) adjustWrap.style.display = supportsAdjusted ? 'inline-block' : 'none';
        if (window.PriceDisplay && window.PriceDisplay.setCheckboxVisibility) {
            window.PriceDisplay.setCheckboxVisibility(
                `show-volume-${subId}-${factorIdx}`,
                `show-volume-wrap-${subId}-${factorIdx}`,
                !!(priceData && priceData.has_volume),
                !!(priceData && priceData.has_volume)
            );
            window.PriceDisplay.setCheckboxVisibility(
                `show-oi-${subId}-${factorIdx}`,
                `show-oi-wrap-${subId}-${factorIdx}`,
                !!(priceData && priceData.has_open_interest),
                !!(priceData && priceData.has_open_interest)
            );
        }
    }

    function buildPriceRequestPayload(selectedProduct, submission, adjusted, isTermContractProduct, freq) {
        const body = {
            adjusted: adjusted,
            start_date: submission.start_date,
            end_date: submission.end_date,
            freq: freq || ''
        };
        if (isTermContractProduct) {
            body.contract_uid = selectedProduct;
            body.adjusted = false;
        } else {
            body.product_name = selectedProduct;
        }
        return body;
    }

    // 绘制 Highcharts 图表（保持原有功能）
    function drawChart(containerId, seriesData, seriesName) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container || !seriesData || !seriesData.dates || !seriesData.values) return;
        const isDaily = seriesData.dates.length > 0 && typeof seriesData.dates[0] === 'string';
        const _parseTs = ts => typeof ts === 'string' ? new Date(ts + 'T00:00:00').getTime() : ts;
        const data = seriesData.dates.map((ts, i) => [_parseTs(ts), seriesData.values[i]]);
        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: null },
            xAxis: { type: 'datetime', ordinal: true },
            yAxis: { title: { text: seriesName }, crosshair: true },
            tooltip: { shared: true, valueDecimals: 4, xDateFormat: isDaily ? '%Y-%m-%d' : '%Y-%m-%d %H:%M:%S' },
            series: [{ name: seriesName, data: data, type: 'line', dataGrouping: { enabled: false }, marker: { enabled: true, radius: 2 } }],
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: true }
        });
    }

    // 绘制 IC 衰减分析图（多周期 IC mean + IR）
    function drawICDecayChart(containerId, icDecay) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container || !icDecay || !icDecay.length) return;
        const lags = icDecay.map(d => d.lag);
        const means = icDecay.map(d => d.mean);
        const irs = icDecay.map(d => d.ir);
        Highcharts.chart(container, {
            chart: { zoomType: 'x' },
            title: { text: null },
            xAxis: {
                categories: lags.map(l => 'Lag ' + l),
                title: { text: '收益滞后期数' },
                crosshair: true,
            },
            yAxis: [
                { title: { text: 'IC Mean' }, labels: { format: '{value:.4f}' } },
                { title: { text: 'IR' }, opposite: true, labels: { format: '{value:.2f}' } },
            ],
            tooltip: { shared: true },
            plotOptions: {
                column: { pointPadding: 0.1, groupPadding: 0.05, borderWidth: 0 },
            },
            series: [
                {
                    name: 'IC Mean',
                    type: 'column',
                    data: means,
                    yAxis: 0,
                    color: '#0078d4',
                    tooltip: { valueDecimals: 6 },
                },
                {
                    name: 'IR',
                    type: 'spline',
                    data: irs,
                    yAxis: 1,
                    color: '#f44336',
                    marker: { enabled: true, radius: 4 },
                    tooltip: { valueDecimals: 4 },
                },
            ],
            credits: { enabled: false },
        });
    }

    // 绘制滚动窗口 IC 图
    function drawRollingICChart(containerId, rollingIc) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container || !rollingIc || !rollingIc.dates || !rollingIc.dates.length) return;
        const isDaily = rollingIc.dates.length > 0 && typeof rollingIc.dates[0] === 'string';
        const _parseTs = ts => typeof ts === 'string' ? new Date(ts + 'T00:00:00').getTime() : ts;
        const meanData = rollingIc.dates.map((ts, i) => [_parseTs(ts), rollingIc.mean[i]]);
        const irData = rollingIc.dates.map((ts, i) => [_parseTs(ts), rollingIc.ir[i]]);
        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: null },
            xAxis: { type: 'datetime' },
            yAxis: [
                { title: { text: 'IC Mean' }, labels: { format: '{value:.4f}' }, crosshair: true },
                { title: { text: 'IR' }, opposite: true, labels: { format: '{value:.2f}' } },
            ],
            tooltip: {
                shared: true,
                valueDecimals: 6,
                xDateFormat: isDaily ? '%Y-%m-%d' : '%Y-%m-%d %H:%M:%S',
            },
            series: [
                { name: 'IC Mean', type: 'line', data: meanData, yAxis: 0, color: '#0078d4', tooltip: { valueDecimals: 6 } },
                { name: 'IR', type: 'line', data: irData, yAxis: 1, color: '#f44336', dashStyle: 'Dash', tooltip: { valueDecimals: 4 } },
            ],
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: true },
            credits: { enabled: false },
        });
    }

    // 绘制自相关衰减柱状图
    function drawAutocorrChart(containerId, autocorr) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container || !autocorr || !autocorr.length) return;
        const lags = autocorr.map(d => 'Lag ' + d.lag);
        const acValues = autocorr.map(d => d.ac);
        // 找半衰期点
        let hlAnnotation = null;
        for (let i = 0; i < autocorr.length; i++) {
            if (autocorr[i].ac < 0.5) {
                const prev = i > 0 ? autocorr[i-1].ac : 1.0;
                const curr = autocorr[i].ac;
                const frac = (0.5 - prev) / (curr - prev);
                hlAnnotation = i - 1 + frac;
                break;
            }
        }

        Highcharts.chart(container, {
            chart: { type: 'column', zoomType: 'x' },
            title: { text: null },
            xAxis: {
                categories: lags,
                title: { text: '滞后期数' },
                crosshair: true,
            },
            yAxis: {
                title: { text: '自相关系数' },
                min: -0.2,
                max: 1.0,
                plotLines: [{
                    value: 0.5,
                    color: '#f44336',
                    dashStyle: 'dash',
                    width: 1,
                    label: { text: '半衰线 0.5', style: { color: '#f44336', fontSize: '10px' } },
                    zIndex: 5,
                }],
            },
            tooltip: {
                pointFormat: '<b>{point.category}</b>: {point.y:.4f}',
            },
            plotOptions: {
                column: {
                    pointPadding: 0.05,
                    groupPadding: 0,
                    borderWidth: 0,
                    color: '#0078d4',
                    negativeColor: '#f44336',
                },
            },
            series: [{
                name: '自相关',
                data: acValues,
                showInLegend: false,
            }],
            credits: { enabled: false },
        });
    }

    // 统计量最优方向：越大越好=1，越小越好=-1（key 对应后端 ic_stats 返回的 index）
    var IC_METRIC_DIRECTION = {
        'mean': 1,
        'std': -1,
        'IR': 1,
        't_stat': 1,
        'max': 1,
        'min': -1,
        'ac1': 1,
        'half_life': -1
    };

    // index → 显示名映射
    var IC_METRIC_LABELS = {
        'mean': 'IC Mean',
        'std': 'IC Std',
        'IR': 'IR',
        't_stat': 't-stat',
        'max': 'IC Max',
        'min': 'IC Min',
        'ac1': 'IC AC1',
        'half_life': 'Half-Life'
    };

    function _getBestValIdx(values, metricName) {
        var dir = IC_METRIC_DIRECTION[metricName] || 0;
        if (dir === 0) return null;
        var bestIdx = null;
        var bestVal = null;
        for (var i = 0; i < values.length; i++) {
            var v = values[i];
            if (v === null || v === undefined || v === '' || (typeof v === 'number' && isNaN(v))) continue;
            if (metricName === 'half_life' && !isFinite(v)) continue;
            var num = typeof v === 'number' ? v : parseFloat(v);
            if (isNaN(num)) continue;
            if (bestIdx === null || (dir > 0 ? num > bestVal : num < bestVal)) {
                bestIdx = i;
                bestVal = num;
            }
        }
        return bestIdx;
    }

    // 构建统计表格 HTML（含最优值高亮 + 活跃因子表头标注）
    function buildPrettyTable(data, subId) {
        if (!data || !data.ic_stats || !data.ic_stats.columns || !data.ic_stats.rows || !data.ic_stats.columns.length) {
            return '<div class="ic-empty">无可展示结果</div>';
        }
        // 默认激活第一个因子
        if (subId) {
            window._icActiveFactorIdx = window._icActiveFactorIdx || {};
            if (window._icActiveFactorIdx[subId] === undefined || window._icActiveFactorIdx[subId] >= (data.ic_stats.columns.length - 1)) {
                window._icActiveFactorIdx[subId] = 0;
            }
        }
        var activeIdx = subId ? (window._icActiveFactorIdx[subId] || 0) : 0;
        var html = '<div class="ic-table-wrap" style="margin-bottom:16px;"><table class="ic-table"><thead><tr>';
        data.ic_stats.columns.forEach(function(col, i) {
            var isIdx = i === 0;
            var isActive = !isIdx && (i - 1 === activeIdx);
            var draggable = !isIdx ? ' draggable="true"' : '';
            var dataColIdx = !isIdx ? ' data-col-idx="' + (i - 1) + '"' : '';
            var activeClass = isActive ? ' ic-active-factor' : '';
            var label = isIdx ? '统计量' : col;
            html += '<th class="' + (isIdx ? 'idx-col' : 'draggable-col') + activeClass + '"' + draggable + dataColIdx + '>' + label + '</th>';
        });
        html += '</tr></thead><tbody>';
        data.ic_stats.rows.forEach(function(row) {
            // 找该行最优值列（不含 index 列）
            var factorCols = data.ic_stats.columns.slice(1);
            var factorVals = factorCols.map(function(c) { return row[c]; });
            var metricName = row['index'] || '';
            var bestColIdx = _getBestValIdx(factorVals, metricName);
            html += '<tr>';
            data.ic_stats.columns.forEach(function(col, i) {
                var val = row[col];
                var display;
                if (i === 0) {
                    // 第一列是统计量名，使用可读标签
                    display = IC_METRIC_LABELS[val] || String(val);
                } else if (val === null || val === undefined || val === '') {
                    display = '—';
                } else if (metricName === 'half_life' && !isFinite(val)) {
                    display = '∞';
                } else if (typeof val === 'number') {
                    display = Number.isInteger(val) ? val : val.toFixed(6);
                } else {
                    display = String(val);
                }
                var cellClass = '';
                if (i === 0) {
                    cellClass = 'idx-col';
                } else if (bestColIdx !== null && (i - 1) === bestColIdx) {
                    cellClass = 'ic-best-cell';
                }
                html += '<td class="' + cellClass + '">' + display + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    // 切换到指定因子（点击表头触发）
    function switchActiveFactor(subId, colIdx, factors) {
        factors = factors || (window._icDataFactors && window._icDataFactors[subId]);
        window._icActiveFactorIdx = window._icActiveFactorIdx || {};
        window._icActiveFactorIdx[subId] = colIdx;
        // 更新表头高亮
        var table = document.querySelector('#ic-result-' + subId + ' .ic-table');
        if (table) {
            table.querySelectorAll('thead th.draggable-col').forEach(function(th, i) {
                if (i === colIdx) {
                    th.classList.add('ic-active-factor');
                } else {
                    th.classList.remove('ic-active-factor');
                }
            });
        }
        // 重新渲染因子面板
        if (factors && factors.length > colIdx) {
            renderFactorPanel(subId, factors[colIdx], colIdx, factors);
        }
    }
    window.switchActiveFactor = switchActiveFactor;

    // 本地重排表格列和因子面板（不重新请求后端数据）
    // fromIdx/toIdx 是相对于因子列（不含 index 列）的索引
    function reorderTableColumns(table, fromIdx, toIdx, subId) {
        // ── 1. 重排表格列 ──
        var rows = table.querySelectorAll('tr');
        rows.forEach(function(row) {
            var cells = Array.from(row.children);
            // cells[0] = index 列，cells[1..] = 因子列
            var factorCells = cells.slice(1);
            var moved = factorCells.splice(fromIdx, 1)[0];
            factorCells.splice(toIdx, 0, moved);
            // 更新 data-col-idx
            factorCells.forEach(function(cell, i) {
                cell.setAttribute('data-col-idx', i);
            });
            // 清空并重新插入
            while (row.children.length > 1) row.removeChild(row.lastChild);
            factorCells.forEach(function(cell) { return row.appendChild(cell); });
        });

        // ── 2. 更新活跃因子索引 ──
        window._icActiveFactorIdx = window._icActiveFactorIdx || {};
        var cur = window._icActiveFactorIdx[subId];
        if (cur === fromIdx) {
            window._icActiveFactorIdx[subId] = toIdx;
        } else if (fromIdx < toIdx) {
            if (cur > fromIdx && cur <= toIdx) window._icActiveFactorIdx[subId] = cur - 1;
        } else {
            if (cur >= toIdx && cur < fromIdx) window._icActiveFactorIdx[subId] = cur + 1;
        }

        // ── 3. 重新应用表头高亮 ──
        var activeIdx = window._icActiveFactorIdx[subId];
        table.querySelectorAll('thead th.draggable-col').forEach(function(th, i) {
            if (i === activeIdx) {
                th.classList.add('ic-active-factor');
            } else {
                th.classList.remove('ic-active-factor');
            }
        });
    }

    // 渲染单个因子的详情面板（无选项卡，由表头点击切换）
    function renderFactorPanel(subId, factor, idx, allFactors) {
        var containerId = 'ic-factor-panel-' + subId;
        var container = document.getElementById(containerId);
        if (!container) {
            var resultDiv = document.getElementById('ic-result-' + subId);
            if (!resultDiv) return;
            var existing = document.getElementById(containerId);
            if (existing) existing.remove();
            container = document.createElement('div');
            container.id = containerId;
            container.className = 'ic-factor-panel';
            resultDiv.appendChild(container);
        }
        if (!factor) {
            container.innerHTML = '<div class="ic-empty">暂无因子数据</div>';
            return;
        }
        var productOptions = (factor.products && factor.products.length)
            ? factor.products.map(function(p) { return '<option value="' + p.name + '" data-is-term-contract="' + (p.is_term_contract ? '1' : '0') + '">' + p.name + (p.desc && p.desc !== p.name ? ' · ' + p.desc : '') + '</option>'; }).join('')
            : '<option value="">无可用产品</option>';
        var icDecayHtml = '';
        var rollingIcHtml = '';
        if (factor.ic_decay && factor.ic_decay.length > 0) {
            icDecayHtml = '<div style="margin-top:20px;"><h6>IC 衰减分析（多周期）</h6><div id="ic-decay-chart-' + subId + '-' + idx + '" style="width:100%; height:300px;"></div></div>';
        }
        if (factor.rolling_ic && factor.rolling_ic.dates && factor.rolling_ic.dates.length > 0) {
            rollingIcHtml = '<div style="margin-top:20px;"><h6>滚动窗口 IC（窗口=' + factor.rolling_ic.window + '）</h6><div id="ic-rolling-chart-' + subId + '-' + idx + '" style="width:100%; height:350px;"></div></div>';
        }
        container.innerHTML = ''
            + '<!-- 因子切换导航条 -->'
            + '<div class="ic-factor-nav" style="display:flex;align-items:center;gap:12px;margin-bottom:12px;padding:10px 14px;background:#f0f5ff;border-radius:8px;border:1px solid #d0ddf0;">'
            + '<span style="font-weight:700;color:#0f4c81;font-size:14px;">📊 ' + (factor.alias || factor.name) + '</span>'
            + '<span style="font-size:12px;color:#888;">点击统计表表头切换因子</span>'
            + (allFactors && allFactors.length > 1 ? '<span style="font-size:12px;color:#666;">（共' + allFactors.length + '个因子，当前第' + (idx + 1) + '个）</span>' : '')
            + '</div>'
            // IC 序列图 & 自相关衰减图
            + '<div style="display:flex; flex-wrap:wrap; gap:20px; margin-top:16px;">'
            + '<div style="flex:1;min-width:45%;"><h6>IC 序列</h6><div id="ic-chart-' + subId + '-' + idx + '" style="width:100%; height:350px;"></div></div>'
            + '<div style="flex:1;min-width:45%;"><h6>IC 自相关衰减</h6><div id="ic-acf-chart-' + subId + '-' + idx + '" style="width:100%; height:350px;"></div></div>'
            + '</div>'
            + icDecayHtml
            + rollingIcHtml
            // 产品选择、加载按钮
            + '<div style="margin-top:16px;">'
            + '<label>主产品(用于因子/收益率)：</label>'
            + '<select id="primary-product-select-' + subId + '-' + idx + '" class="form-select" style="width:240px; display:inline-block; margin-left:8px;">' + productOptions + '</select>'
            + '<button class="btn btn-sm btn-outline-primary" data-sub="' + subId + '" data-idx="' + idx + '" data-factor-name="' + factor.name + '" data-factor-alias="' + factor.alias + '">加载因子和收益</button>'
            + '<span id="adjust-wrap-' + subId + '-' + idx + '" style="margin-left:12px;display:none;">'
            + '<label style="margin:0;"><input type="checkbox" id="adjust-price-' + subId + '-' + idx + '"> 复权价格</label>'
            + '</span>'
            + '<span id="show-volume-wrap-' + subId + '-' + idx + '" style="margin-left:12px;display:none;">'
            + '<label><input type="checkbox" id="show-volume-' + subId + '-' + idx + '" checked onchange="window.icRedrawComparison(' + subId + ',' + idx + ')"> 📊 成交量</label>'
            + '</span>'
            + '<span id="show-oi-wrap-' + subId + '-' + idx + '" style="margin-left:8px;display:none;">'
            + '<label><input type="checkbox" id="show-oi-' + subId + '-' + idx + '" checked onchange="window.icRedrawComparison(' + subId + ',' + idx + ')"> 📈 持仓量</label>'
            + '</span>'
            + '<div style="margin-top:6px;color:#666;font-size:12px;">期限合约请在下方点击表格选择</div>'
            + '</div>'
            + '<div id="contract-table-wrap-' + subId + '-' + idx + '" style="margin-top:10px;display:none;border:1px solid #e1e4e8;border-radius:6px;background:#fff;max-height:220px;overflow:auto;">'
            + '<table style="width:100%;border-collapse:collapse;font-size:12px;">'
            + '<thead><tr style="position:sticky;top:0;background:#f6f8fa;z-index:1;">'
            + '<th style="padding:6px 10px;text-align:left;border-bottom:1px solid #f0f0f0;">合约</th>'
            + '<th style="padding:6px 10px;text-align:left;border-bottom:1px solid #f0f0f0;">起始日期</th>'
            + '<th style="padding:6px 10px;text-align:left;border-bottom:1px solid #f0f0f0;">结束日期</th>'
            + '</tr></thead>'
            + '<tbody id="contract-table-body-' + subId + '-' + idx + '"></tbody>'
            + '</table>'
            + '</div>'
            // 价格/因子值/收益率三联图容器
            + '<div style="margin-top:8px;">'
            + '<p style="font-size:11px;color:#888;margin:0 0 4px 0;">💡 点击图中 <b style="color:#0078d4;">因子值</b> 曲线上的数据点可查看该时刻的截面分布</p>'
            + '<div id="factor-chart-' + subId + '-' + idx + '" style="width:100%;"></div>'
            + '</div>';

        // 绘制 IC 图表
        if (factor.ic_series && factor.ic_series.dates && factor.ic_series.values) {
            drawChart('ic-chart-' + subId + '-' + idx, factor.ic_series, 'IC');
        }
        if (factor.autocorr && factor.autocorr.length > 0) {
            drawAutocorrChart('ic-acf-chart-' + subId + '-' + idx, factor.autocorr);
        }
        if (factor.ic_decay && factor.ic_decay.length > 0) {
            drawICDecayChart('ic-decay-chart-' + subId + '-' + idx, factor.ic_decay);
        }
        if (factor.rolling_ic && factor.rolling_ic.dates && factor.rolling_ic.dates.length > 0) {
            drawRollingICChart('ic-rolling-chart-' + subId + '-' + idx, factor.rolling_ic);
        }

        // 初始化期限合约表格
        var primarySelect = document.getElementById('primary-product-select-' + subId + '-' + idx);
        if (primarySelect) {
            populateContractTable(subId, idx, primarySelect.value);
            primarySelect.addEventListener('change', function() {
                populateContractTable(subId, idx, primarySelect.value);
            });
        }

        // 绑定加载按钮事件
        var loadBtns = document.querySelectorAll('[data-sub="' + subId + '"][data-idx="' + idx + '"]');
        loadBtns.forEach(function(btn) {
            btn.removeEventListener('click', loadHandler);
            btn.addEventListener('click', loadHandler);
        });
        async function loadHandler(e) {
            var sub = e.currentTarget.getAttribute('data-sub');
            var ix = e.currentTarget.getAttribute('data-idx');
            var fName = e.currentTarget.getAttribute('data-factor-name');
            var fAlias = e.currentTarget.getAttribute('data-factor-alias');
            try {
                await loadFactorAndReturn(sub, ix, fName, fAlias);
            } catch (err) {
                console.error('loadFactorAndReturn 失败:', err);
            }
        }
    }

    // 加载因子值和收益率并绘图
    async function loadFactorAndReturn(subId, factorIdx, factorName, factorAlias) {
        const primarySelect = document.getElementById(`primary-product-select-${subId}-${factorIdx}`);
        const testerPrimary = primarySelect ? primarySelect.value : '';
        const selectedOption = primarySelect ? primarySelect.options[primarySelect.selectedIndex] : null;
        const isTermContractProduct = selectedOption ? selectedOption.getAttribute('data-is-term-contract') === '1' : false;
        const product = testerPrimary || null;
        if (!product || product === '') { alert('请选择一个产品'); return; }

        const factorChartDiv = document.getElementById(`factor-chart-${subId}-${factorIdx}`);
        if (!factorChartDiv) return;
        factorChartDiv.style.height = 'auto';
        factorChartDiv.innerHTML = '<div style="color:#888; text-align:center; padding:18px 0;">加载价格与因子值...</div>';

        const submission = window.submissions ? window.submissions.find(s => s.id == subId) : null;
        if (!submission) { 
            factorChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">未找到提交记录</div>'; 
            return; 
        }

        const factorInfo = factorList.find(f => f.alias === factorAlias) || factorList.find(f => f.name === factorName);
        const freq = (factorInfo && factorInfo.freq !== 'N') ? factorInfo.freq : '1D';

        const _safeJson = async (r, label) => {
                const text = await r.text();
                try { return JSON.parse(text); }
                catch (e) { throw new Error(`${label} 返回非JSON (HTTP ${r.status}): ${text.slice(0, 300)}`); }
            };
        try {
            const [factorData, returnData] = await Promise.all([
                fetch('/get_factor_series', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        submission_id: subId,
                        factor_family_alias: factorFamilyAlias,
                        factor_name: factorName,
                        factor_alias: factorAlias,
                        product: testerPrimary || product
                    })
                }).then(r => _safeJson(r, 'get_factor_series')),
                fetch('/get_return_series', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        submission_id: subId,
                        factor_name: factorName,
                        factor_alias: factorAlias,
                        factor_family_alias: factorFamilyAlias,
                        product: testerPrimary || product,
                        paths: submission.paths
                    })
                }).then(r => _safeJson(r, 'get_return_series'))
            ]);
            if (factorData.error) {
                var factorErr = 'get_factor_series 错误: ' + factorData.error;
                if (factorData.traceback) {
                    factorChartDiv.innerHTML = '<div style="color:#d00; text-align:left;">' + factorErr + '</div>' +
                        `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:11px;overflow:auto;white-space:pre-wrap;margin-top:8px;">${factorData.traceback.replace(/</g,'&lt;')}</pre>`;
                    return;
                }
                throw new Error(factorErr);
            }
            if (returnData.error) {
                var returnErr = 'get_return_series 错误: ' + returnData.error;
                if (returnData.traceback) {
                    factorChartDiv.innerHTML = '<div style="color:#d00; text-align:left;">' + returnErr + '</div>' +
                        `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:11px;overflow:auto;white-space:pre-wrap;margin-top:8px;">${returnData.traceback.replace(/</g,'&lt;')}</pre>`;
                    return;
                }
                throw new Error(returnErr);
            }

            const adjustCheckbox = document.getElementById(`adjust-price-${subId}-${factorIdx}`);
            const adjusted = adjustCheckbox ? adjustCheckbox.checked : false;

            // 主价格序列改为复用价格查看模块链路，保证连续性
            const priceApi = await fetch('/api/get_price_data', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(buildPriceRequestPayload(testerPrimary || product, submission, adjusted, isTermContractProduct, freq))
            }).then(r => r.json());

            const priceData = priceApiToSeries(priceApi);

            if (priceData.error) {
                var priceErr = 'get_price_data 错误: ' + priceData.error;
                if (priceApi.traceback) {
                    factorChartDiv.innerHTML = '<div style="color:#d00; text-align:left;">' + priceErr + '</div>' +
                        `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:11px;overflow:auto;white-space:pre-wrap;margin-top:8px;">${priceApi.traceback.replace(/</g,'&lt;')}</pre>`;
                    return;
                }
                throw new Error(priceErr);
            }
            updateComparisonOptionControls(subId, factorIdx, priceApi, priceData);

            if (priceData.dates && priceData.OPEN && factorData.dates && factorData.values && returnData.dates && returnData.values) {
                // 拉取“同一产品不同期限合约”叠加线（接口链路复用 price_viewer）
                const key = `${subId}-${factorIdx}`;
                const selectedContractUids = Array.from(icContractSelection[key] || []);
                const contractSeriesList = adjusted
                    ? []
                    : await fetchContractSeriesForOverlay(selectedContractUids, submission, adjusted);
                priceData.contract_series_list = contractSeriesList;

                // 缓存数据以便 Volume/OI 复选框切换时重绘
                const cacheKey = `${subId}-${factorIdx}`;
                window._icComparisonCache = window._icComparisonCache || {};
                window._icComparisonCache[cacheKey] = { priceData, factorData, returnData, product, factorName, factorAlias };
                factorChartDiv.style.height = '800px';
                drawComparisonChart(`factor-chart-${subId}-${factorIdx}`, priceData, factorData, returnData, product, factorName, factorAlias, subId, product);
            } else {
                factorChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">价格、因子或收益率数据无效</div>';
            }
        } catch (err) {
            console.error('加载错误:', err);
            factorChartDiv.innerHTML = `<div style="color:#d00; text-align:center;">请求失败: ${err.message}</div>`;
        }
    }

    async function populateContractTable(subId, factorIdx, productName) {
        const wrap = document.getElementById(`contract-table-wrap-${subId}-${factorIdx}`);
        const tbody = document.getElementById(`contract-table-body-${subId}-${factorIdx}`);
        const adjustWrap = document.getElementById(`adjust-wrap-${subId}-${factorIdx}`);
        const adjustCheckbox = document.getElementById(`adjust-price-${subId}-${factorIdx}`);
        if (!wrap || !tbody) return;
        tbody.innerHTML = '';
        wrap.style.display = 'none';
        if (adjustWrap) adjustWrap.style.display = 'none';
        if (adjustCheckbox) adjustCheckbox.checked = false;
        if (!productName) return;
        const key = `${subId}-${factorIdx}`;
        icContractSelection[key] = new Set();
        try {
            const submission = window.submissions ? window.submissions.find(s => String(s.id) === String(subId)) : null;
            const primarySelect = document.getElementById(`primary-product-select-${subId}-${factorIdx}`);
            const selectedOption = primarySelect ? primarySelect.options[primarySelect.selectedIndex] : null;
            const isTermContractProduct = selectedOption ? selectedOption.getAttribute('data-is-term-contract') === '1' : false;
            if (isTermContractProduct) return;
            const q = new URLSearchParams({ product: productName });
            if (submission && submission.start_date) q.set('start_date', submission.start_date);
            if (submission && submission.end_date) q.set('end_date', submission.end_date);
            const resp = await fetch('/api/get_contracts?' + q.toString());
            const data = await resp.json();
            if (!data.success || !Array.isArray(data.contracts)) return;
            wrap.style.display = data.contracts.length > 0 ? 'block' : 'none';
            data.contracts.forEach(function(c, idx) {
                const tr = document.createElement('tr');
                tr.style.cursor = 'pointer';
                tr.innerHTML =
                    '<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">' + c.contract + '</td>' +
                    '<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">' + (c.start || '') + '</td>' +
                    '<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">' + (c.end || '') + '</td>';
                if (idx < 3) {
                    icContractSelection[key].add(c.uid);
                    tr.style.background = 'rgba(255,165,0,0.15)';
                }
                tr.addEventListener('mouseenter', function() {
                    window.icHighlightContractRange(subId, factorIdx, c.start_ts, c.end_ts);
                });
                tr.addEventListener('mouseleave', function() {
                    window.icHighlightContractRange(subId, factorIdx, null, null);
                });
                tr.addEventListener('click', function() {
                    if (icContractSelection[key].has(c.uid)) {
                        icContractSelection[key].delete(c.uid);
                        tr.style.background = '';
                    } else {
                        icContractSelection[key].add(c.uid);
                        tr.style.background = 'rgba(255,165,0,0.15)';
                    }
                });
                tbody.appendChild(tr);
            });
        } catch (e) {
            console.warn('加载期限合约失败:', e);
        }
    }

    async function fetchContractSeriesForOverlay(contractUids, submission, adjusted) {
        const list = [];
        if (!Array.isArray(contractUids) || contractUids.length === 0) return list;
        const startMs = submission && submission.start_date ? new Date(submission.start_date + 'T00:00:00').getTime() : null;
        const endMs = submission && submission.end_date ? new Date(submission.end_date + 'T23:59:59').getTime() : null;
        const reqs = contractUids.map(async function(uid) {
            const res = await fetch('/api/get_price_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    contract_uid: uid,
                    adjusted: false,
                    start_date: submission.start_date,
                    end_date: submission.end_date,
                })
            }).then(r => r.json());
            const overlay = window.PriceDisplay && window.PriceDisplay.contractOverlayFromApi
                ? window.PriceDisplay.contractOverlayFromApi(res)
                : null;
            if (!overlay) return null;
            const keepRange = function(point) {
                const ts = point && point[0];
                if (ts == null) return false;
                if (startMs != null && ts < startMs) return false;
                if (endMs != null && ts > endMs) return false;
                return true;
            };
            overlay.data = overlay.data.filter(keepRange);
            overlay.volume = (overlay.volume || []).filter(keepRange);
            overlay.open_interest = (overlay.open_interest || []).filter(keepRange);
            if (overlay.data.length === 0) return null;
            return overlay;
        });
        const got = await Promise.all(reqs);
        got.forEach(function(x) { if (x) list.push(x); });
        return list;
    }

    function priceApiToSeries(apiData) {
        if (window.PriceDisplay && window.PriceDisplay.normalizePriceApi) {
            return window.PriceDisplay.normalizePriceApi(apiData);
        }
        if (!apiData || !apiData.success || !Array.isArray(apiData.data) || apiData.data.length === 0) {
            return { error: (apiData && apiData.error) || '无价格数据' };
        }
        const data = apiData.data.slice().sort(function(a, b) { return (a.timestamp || 0) - (b.timestamp || 0); });
        const series = {
            product: apiData.product || '',
            desc: apiData.desc || '',
            contract_uid: apiData.contract_uid || '',
            contract_name: apiData.contract_name || '',
            is_term_contract: !!apiData.is_term_contract || !!apiData.contract_uid,
            supports_term_structure: !!apiData.supports_term_structure,
            dates: data.map(d => d.timestamp),
            OPEN: data.map(d => d.open),
            HIGH: data.map(d => d.high),
            LOW: data.map(d => d.low),
            CLOSE: data.map(d => d.close),
            VOLUME: data.map(d => d.volume == null ? null : d.volume),
            OPEN_INTEREST: data.map(d => d.open_interest == null ? null : d.open_interest),
        };
        series.has_volume = series.VOLUME.some(v => v != null);
        series.has_open_interest = !!apiData.has_oi && series.OPEN_INTEREST.some(v => v != null);
        return series;
    }

    window.icHighlightContractRange = function(subId, idx, fromTs, toTs) {
        const key = `${subId}-${idx}`;
        const chart = window._icComparisonChartRefs && window._icComparisonChartRefs[key];
        if (!chart || !chart.xAxis || !chart.xAxis[0]) return;
        const axis = chart.xAxis[0];
        axis.removePlotBand('ic-contract-hover-band');
        if (fromTs == null || toTs == null) {
            delete icHoverBandState[key];
            return;
        }
        icHoverBandState[key] = { from: fromTs, to: toTs };
        axis.addPlotBand({
            id: 'ic-contract-hover-band',
            from: fromTs,
            to: toTs,
            color: 'rgba(100,149,237,0.12)',
            zIndex: 3,
        });
    };

    // 运行 IC 测试（核心修改）
    async function resolveSubmissionIdForIC(subId, submission) {
        try {
            const resp = await fetch('/api/list_submissions');
            const data = await resp.json();
            if (!data.success || !Array.isArray(data.submissions) || data.submissions.length === 0) {
                return String(subId);
            }

            const targetId = String(subId);
            const exact = data.submissions.find(s => String(s.id) === targetId);
            if (exact) return String(exact.id);

            const localPaths = new Set((submission?.paths || []).map(String));
            if (localPaths.size > 0) {
                const matched = data.submissions.find(s => {
                    const sp = new Set((s.selected_paths || []).map(String));
                    if (sp.size !== localPaths.size) return false;
                    for (const p of localPaths) {
                        if (!sp.has(p)) return false;
                    }
                    return true;
                });
                if (matched) return String(matched.id);
            }
        } catch (e) {
            console.warn('resolveSubmissionIdForIC failed:', e);
        }
        return String(subId);
    }

    window.runIC = async function(subId) {
        const btn = document.getElementById(`run-ic-btn-${subId}`);
        const statusSpan = document.getElementById(`ic-status-${subId}`);
        const resultDiv = document.getElementById(`ic-result-${subId}`);
        if (!btn || !statusSpan || !resultDiv) return;

        // 收集选中的因子及频率（从全局抽屉读取）
        const selectedFactors = [];
        const checkboxes = document.querySelectorAll('#ic-freq-table-body .factor-checkbox:checked');
        if (checkboxes.length === 0) {
            statusSpan.innerText = '请至少选择一个因子';
            statusSpan.style.color = '#d40000';
            return;
        }
        checkboxes.forEach(cb => {
            const alias = cb.getAttribute('data-factor-alias');
            const allFreqInputs = document.querySelectorAll('#ic-freq-table-body .factor-return-freq-input');
            const freqInput = Array.from(allFreqInputs).find(input => input.getAttribute('data-factor-alias') === alias) || null;
            const return_freq = freqInput ? freqInput.value.trim() : '';
            selectedFactors.push({ alias, return_freq });
        });
        const submission = window.submissions ? window.submissions.find(s => s.id == subId) : null;
        if (!submission) {
            statusSpan.innerText = '错误：未找到提交';
            btn.disabled = false;
            return;
        }
        btn.disabled = true;
        statusSpan.innerText = 'IC测试运行中...';
        statusSpan.style.color = '#0078d4';
        resultDiv.innerHTML = '';

        // 读取 IC 衰减和滚动窗口参数
        const decayLagsInput = document.getElementById(`ic-decay-lags-${subId}`);
        const rollingWinInput = document.getElementById(`ic-rolling-window-${subId}`);
        let ic_decay_lags = null;
        let rolling_window = null;
        if (decayLagsInput && decayLagsInput.value.trim()) {
            const parts = decayLagsInput.value.trim().split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n) && n > 0);
            if (parts.length > 0) ic_decay_lags = parts;
        }
        if (rollingWinInput && rollingWinInput.value.trim()) {
            const w = parseInt(rollingWinInput.value.trim(), 10);
            if (!isNaN(w) && w > 1) rolling_window = w;
        }

        try {
            const effectiveSubmissionId = await resolveSubmissionIdForIC(subId, submission);

            // 显示进度条
            const progressBarId = `ic-progress-${subId}`;
            let progressDiv = document.getElementById(progressBarId);
            if (!progressDiv) {
                progressDiv = document.createElement('div');
                progressDiv.id = progressBarId;
                progressDiv.className = 'ic-progress-container';
                progressDiv.innerHTML = `
                    <div class="ic-progress-bar-bg">
                        <div class="ic-progress-bar-fill" id="${progressBarId}-fill"></div>
                    </div>
                    <span class="ic-progress-text" id="${progressBarId}-text">0/0</span>
                `;
                resultDiv.parentNode.insertBefore(progressDiv, resultDiv);
            }

            const body = JSON.stringify({
                submission_id: effectiveSubmissionId,
                factor_family_alias: factorFamilyAlias,
                paths: submission.paths,
                factors: selectedFactors,
                ic_decay_lags: ic_decay_lags,
                rolling_window: rolling_window
            });

            const sseResponse = await fetch('/run_ic_test_stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body
            });

            if (!sseResponse.ok) {
                btn.disabled = false;
                statusSpan.innerText = '✗ IC测试失败: HTTP ' + sseResponse.status;
                statusSpan.style.color = '#d40000';
                return;
            }

            const reader = sseResponse.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let lastEvent = '';
            let data = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // 保留未完成的行

                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        lastEvent = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        try {
                            const payload = JSON.parse(line.slice(6));
                            if (lastEvent === 'start') {
                                const fill = document.getElementById(`${progressBarId}-fill`);
                                const text = document.getElementById(`${progressBarId}-text`);
                                if (fill) fill.style.width = '0%';
                                if (text) {
                                    const groups = payload.groups || payload.total;
                                    text.textContent = `0/${payload.total} 节点 (${groups} 组)`;
                                }
                            } else if (lastEvent === 'progress') {
                                const fill = document.getElementById(`${progressBarId}-fill`);
                                const text = document.getElementById(`${progressBarId}-text`);
                                const phase = payload.phase || '';
                                if (phase === 'eval') {
                                    // 节点级进度：显示 completed/total 节点
                                    if (fill) fill.style.width = (payload.completed / payload.total * 100) + '%';
                                    if (text) text.textContent = `${payload.completed}/${payload.total} 节点`;
                                } else {
                                    // group_done 等其他阶段：显示组级进度
                                    if (fill) fill.style.width = (payload.completed / payload.total * 100) + '%';
                                    if (text) text.textContent = `第 ${payload.completed}/${payload.total} 组完成`;
                                }
                            } else if (lastEvent === 'result') {
                                data = payload;
                            } else if (lastEvent === 'error') {
                                data = payload;
                            }
                        } catch (e) {
                            // skip malformed JSON
                        }
                    }
                }
            }

            // 清理进度条
            if (progressDiv) progressDiv.remove();

            btn.disabled = false;
            if (!data || !data.success) {
                statusSpan.innerText = '✗ IC测试失败: ' + (data?.error || '未知错误');
                statusSpan.style.color = '#d40000';
                if (data?.traceback) {
                    resultDiv.innerHTML = `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:12px;overflow:auto;white-space:pre-wrap;">${data.traceback.replace(/</g,'&lt;')}</pre>`;
                }
                return;
            }
            statusSpan.innerText = '✓ IC测试完成' + (data.paths_hash ? (' (路径哈希: ' + data.paths_hash + ')') : '');
            statusSpan.style.color = '#28a745';
            resultDiv.innerHTML = buildPrettyTable(data, subId);
            // 缓存因子数据供 switchActiveFactor / reorder 使用
            window._icDataFactors = window._icDataFactors || {};
            window._icDataFactors[subId] = data.factors;
            // 设置活跃因子索引（默认第一个）
            window._icActiveFactorIdx = window._icActiveFactorIdx || {};
            window._icActiveFactorIdx[subId] = 0;
            // 渲染第一个因子的详情面板
            if (data.factors && data.factors.length > 0) {
                renderFactorPanel(subId, data.factors[0], 0, data.factors);
            }
            // 表格列头点击切换到对应因子选项卡 + 拖拽排序
            const table = resultDiv.querySelector('.ic-table');
            if (table) {
                const theadRow = table.querySelector('thead tr');
                const headers = table.querySelectorAll('thead th:not(.idx-col)');

                // ── 拖拽排序 ──
                let dragStartColIdx = null;
                let dragOverColIdx = null;

                // 标记活跃因子列（默认第0列）
                headers.forEach(function(th, i) {
                    if (i === 0) th.classList.add('ic-active-factor');
                });
                headers.forEach(function(th) {
                    // 点击切换到对应因子
                    th.style.cursor = 'pointer';
                    th.addEventListener('click', function() {
                        var colIdx = parseInt(th.getAttribute('data-col-idx'));
                        if (!isNaN(colIdx) && window._icDataFactors) {
                            switchActiveFactor(subId, colIdx, window._icDataFactors[subId]);
                        }
                    });

                    // ── 长按添加因子到因子库 ──
                    bindLongPressAddToLibrary(th, subId);

                    // 拖拽开始
                    th.addEventListener('dragstart', function(e) {
                        const colIdx = parseInt(this.getAttribute('data-col-idx'));
                        if (isNaN(colIdx)) return;
                        dragStartColIdx = colIdx;
                        this.style.opacity = '0.5';
                        e.dataTransfer.effectAllowed = 'move';
                    });

                    // 拖拽结束
                    th.addEventListener('dragend', function(e) {
                        this.style.opacity = '';
                        dragStartColIdx = null;
                        dragOverColIdx = null;
                    });

                    // 拖拽经过
                    th.addEventListener('dragover', function(e) {
                        const colIdx = parseInt(this.getAttribute('data-col-idx'));
                        if (isNaN(colIdx) || dragStartColIdx === null) return;
                        e.preventDefault();
                        dragOverColIdx = colIdx;
                        this.classList.add('drag-over');
                    });

                    th.addEventListener('dragleave', function(e) {
                        this.classList.remove('drag-over');
                    });

                    // 放下
                    th.addEventListener('drop', function(e) {
                        e.preventDefault();
                        this.classList.remove('drag-over');
                        const colIdx = parseInt(this.getAttribute('data-col-idx'));
                        if (isNaN(colIdx)) return;
                        if (dragStartColIdx !== null && dragOverColIdx !== null && dragStartColIdx !== dragOverColIdx) {
                            // 先在本地重排表格列和因子面板（瞬时的前端操作，无需重新计算）
                            reorderTableColumns(table, dragStartColIdx, dragOverColIdx, subId);
                            // 同步更新因子缓存顺序
                            var cachedFactors = window._icDataFactors && window._icDataFactors[subId];
                            if (cachedFactors) {
                                var moved = cachedFactors.splice(dragStartColIdx, 1)[0];
                                cachedFactors.splice(dragOverColIdx, 0, moved);
                            }

                            // 同步后端 session 参数顺序
                            fetch('/reorder_params', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    factor_family_alias: factorFamilyAlias,
                                    from_idx: dragStartColIdx,
                                    to_idx: dragOverColIdx
                                })
                            })
                            .then(res => res.json())
                            .then(resData => {
                                if (resData.success) {
                                    // 只刷新参数模块（不重新跑 IC 测试）
                                    if (typeof window.reloadParamModule === 'function') {
                                        window.reloadParamModule();
                                    }
                                    // 同步更新因子列表缓存
                                    fetchFactorList();
                                } else {
                                    alert('排序失败: ' + (resData.error || '未知错误'));
                                }
                            });
                        }
                    });
                });
            }
            // 隐藏原有的 Highcharts 大容器
            const chartContainer = document.getElementById(`chart-container-${subId}`);
            if (chartContainer) chartContainer.style.display = 'none';
        } catch (err) {
            btn.disabled = false;
            statusSpan.innerText = '前端错误: ' + err.message;
            statusSpan.style.color = '#d40000';
        }
    };

    // 填充收益率频率设置抽屉
    function populateFreqDrawer(factors) {
        const tbody = document.getElementById('ic-freq-table-body');
        const summaryText = document.getElementById('ic-freq-summary-text');
        const summaryRow = document.getElementById('ic-freq-summary-row');
        if (!tbody || !summaryText) return;
        if (!factors || factors.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="color:#888;text-align:center;">暂无因子数据，请先选择因子家族。</td></tr>';
            summaryText.textContent = '暂无因子数据';
            return;
        }
        // 如果摘要行隐藏，显示它
        if (summaryRow) summaryRow.style.display = '';
        let rows = '';
        let customCount = 0;
        factors.forEach(f => {
            const defaultReturnFreq = f.default_return_freq || '';
            const defaultHint = defaultReturnFreq ? `默认: 因子$F (${defaultReturnFreq})` : '默认: 因子$F';
            const cat = (f.category || '').trim();
            rows += `<tr>
                <td><label><input type="checkbox" class="factor-checkbox" data-factor-alias="${f.alias}" checked> ${f.name}</label></td>
                <td style="color:#667085;font-size:12px;">${cat}</td>
                <td>
                    <input
                        type="text"
                        class="factor-return-freq-input form-control form-control-sm"
                        data-factor-alias="${f.alias}"
                        value=""
                        placeholder="留空则使用${defaultHint}"
                        title="留空则使用${defaultHint}；也可手动填写如 5min、1H、1D"
                        style="width:220px; display:inline-block;"
                    >
                    <div style="margin-top:4px; font-size:12px; color:#6b7280;">${defaultHint}</div>
                </td>
            </tr>`;
        });
        tbody.innerHTML = rows;
        // 更新摘要
        updateFreqSummary();
        // 监听输入变化更新摘要
        tbody.querySelectorAll('.factor-return-freq-input').forEach(inp => {
            inp.addEventListener('input', updateFreqSummary);
        });
        tbody.querySelectorAll('.factor-checkbox').forEach(cb => {
            cb.addEventListener('change', updateFreqSummary);
        });
    }
    
    function updateFreqSummary() {
        const summaryText = document.getElementById('ic-freq-summary-text');
        if (!summaryText) return;
        const tbody = document.getElementById('ic-freq-table-body');
        if (!tbody) return;
        const inputs = tbody.querySelectorAll('.factor-return-freq-input');
        let customCount = 0;
        inputs.forEach(inp => { if (inp.value.trim()) customCount++; });
        const checkedCount = tbody.querySelectorAll('.factor-checkbox:checked').length;
        if (customCount > 0) {
            summaryText.textContent = `${customCount}个因子设置了自定义频率，${checkedCount}个因子参与测试`;
        } else {
            summaryText.textContent = `默认使用因子$F，${checkedCount}个因子参与测试`;
        }
    }
    window.updateFreqSummary = updateFreqSummary;

    // 弃用旧的内联面板生成，保留兼容性（返回空字符串）
    function buildFactorConfigPanel(subId, factors) {
        return '';
    }

    // 渲染主选项卡（外部调用）
    window.renderICTabs = async function(submissions) {
        const container = document.getElementById('ic-tab-container');
        if (!container) return;
        if (!submissions || submissions.length === 0) {
            container.innerHTML = '<div style="color:#888; padding:8px; border:1px dashed #ccc; border-radius:4px;">请先完成产品类别设置并提交。</div>';
            return;
        }
        // 获取因子列表（如果尚未获取）
        if (factorList.length === 0) await fetchFactorList();
        // 填充收益率频率抽屉（全局，所有tab共享）
        populateFreqDrawer(factorList);
        let tabsHtml = '<ul class="nav nav-tabs" id="icTab" role="tablist">';
        let panelsHtml = '<div class="tab-content" id="icTabContent">';
        submissions.forEach((sub, idx) => {
            const activeClass = idx === 0 ? 'active' : '';
            const showClass = idx === 0 ? 'show active' : '';
            const tabId = `ic-tab-${sub.id}`;
            const panelId = `ic-panel-${sub.id}`;
            const tabLabel = sub.product_group || sub.label || sub.factor_tester_serial || ('测试器' + (idx+1));
            const pgPrefix = sub.product_group ? '📦 ' : '';
            tabsHtml += `<li class="nav-item"><button class="nav-link ${activeClass}" id="${tabId}" data-submission-id="${sub.id}" data-bs-toggle="tab" data-bs-target="#${panelId}" type="button" role="tab">${pgPrefix}${tabLabel}</button></li>`;
            panelsHtml += `
                <div class="tab-pane fade ${showClass}" id="${panelId}" role="tabpanel">
                    <div class="ic-card">
                        <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 12px;">
                            <button class="btn btn-primary btn-sm" id="run-ic-btn-${sub.id}" onclick="runIC('${sub.id}')">运行IC测试</button>
                            <span id="ic-status-${sub.id}" class="ic-status"></span>
                        </div>
                        <!-- IC 衰减 & 滚动窗口 参数 -->
                        <div style="display:flex; gap:16px; align-items:baseline; flex-wrap:wrap; margin-bottom:2px; padding:8px 12px; background:#f8fafc; border-radius:6px; border:1px solid #e5e7eb;">
                            <span style="font-size:12px; font-weight:600; color:#555;">扩展分析:</span>
                            <label style="font-size:12px; margin:0; white-space:nowrap;">
                                IC衰减滞后期
                                <input type="text" id="ic-decay-lags-${sub.id}" value="" placeholder="1,2,3,5,10,20"
                                       style="width:110px; font-size:12px; padding:2px 6px; vertical-align:center; margin:0;" title="逗号分隔的滞后期数，计算各周期IC统计量">
                            </label>
                            <label style="font-size:12px; margin:0; white-space:nowrap;">
                                滚动窗口
                                <input type="number" id="ic-rolling-window-${sub.id}" value="" placeholder="如60"
                                       min="2" max="1000" style="width:70px; font-size:12px; padding:2px 6px; vertical-align:center;" title="滚动窗口大小（期数），计算每窗 IC Mean 和 IR">
                            </label>
                        </div>
                        <div id="ic-result-${sub.id}"></div>
                        <div id="chart-container-${sub.id}" style="width:100%; margin-top:14px;"></div>
                    </div>
                </div>
            `;
        });
        tabsHtml += '</ul>';
        panelsHtml += '</div>';
        container.innerHTML = tabsHtml + panelsHtml;
        if (typeof bootstrap !== 'undefined') {
            const tabTriggers = document.querySelectorAll('#icTab button[data-bs-toggle="tab"]');
            tabTriggers.forEach(trigger => {
                const tab = new bootstrap.Tab(trigger);
                trigger.addEventListener('click', (e) => { e.preventDefault(); tab.show(); });
            });
        }
        if (typeof window.renderGroupTabs === 'function') {
            window.renderGroupTabs(submissions);
        }
    };

    // 页面加载完成后，如果已有 submissions，则渲染
    // 收益率频率抽屉的按钮事件
    function initFreqDrawerButtons() {
        const selectAll = document.getElementById('ic-freq-select-all');
        const deselectAll = document.getElementById('ic-freq-deselect-all');
        const resetFreq = document.getElementById('ic-freq-reset');
        if (selectAll) selectAll.onclick = () => {
            document.querySelectorAll('#ic-freq-table-body .factor-checkbox').forEach(cb => cb.checked = true);
            updateFreqSummary();
        };
        if (deselectAll) deselectAll.onclick = () => {
            document.querySelectorAll('#ic-freq-table-body .factor-checkbox').forEach(cb => cb.checked = false);
            updateFreqSummary();
        };
        if (resetFreq) resetFreq.onclick = () => {
            document.querySelectorAll('#ic-freq-table-body .factor-return-freq-input').forEach(input => input.value = '');
            updateFreqSummary();
        };
    }

    async function initICModule() {
        initFreqDrawerButtons();
        await fetchFactorList();
        populateFreqDrawer(factorList);
        if (window.submissions && window.submissions.length) {
            await window.renderICTabs(window.submissions);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initICModule);
    } else {
        initICModule();
    }

    // 供参数模块调用，刷新因子列表和 IC 选项卡
    window.refreshICModule = async function() {
        console.log('刷新 IC 模块因子列表');
        await fetchFactorList();  // 重新获取因子列表
        populateFreqDrawer(factorList);  // 刷新收益率频率抽屉
        if (window.submissions && window.submissions.length) {
            await window.renderICTabs(window.submissions);
        }
        window.factorList = factorList;
        if (typeof window.renderGroupTabs === 'function' && window.submissions && window.submissions.length) {
            window.renderGroupTabs(window.submissions);
        }
    };

    window.factorList = factorList;

    // ========== 因子截面分布可视化 ==========

    async function openFactorDistribution(subId, factorName, factorAlias, tsMs, product) {
        const drawer = document.getElementById('factor-dist-drawer');
        const title  = document.getElementById('dist-drawer-title');
        const chartContainer = document.getElementById('dist-chart-container');
        if (!drawer || !title || !chartContainer) return;

        // 打开抽屉并显示加载状态
        drawer.classList.add('open');
        title.textContent = `${factorName} 截面分布` + (product ? ` · ${product}` : '');
        chartContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#888;">加载中...</div>';

        try {
            const res = await fetch('/get_factor_distribution', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    submission_id: String(subId),
                    factor_family_alias: factorFamilyAlias,
                    factor_name: factorName,
                    factor_alias: factorAlias,
                    timestamp: tsMs,
                    product: product || null,
                }),
            });
            const data = await res.json();
            if (!data.success) {
                chartContainer.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#d00;">${data.error || '获取分布数据失败'}</div>`;
                return;
            }
            drawDistributionHistogram(chartContainer, data, factorName);
        } catch (err) {
            console.error('获取因子分布异常:', err);
            chartContainer.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#d00;">请求失败: ${err.message}</div>`;
        }
    }

    function drawDistributionHistogram(container, data, factorName) {
        if (typeof Highcharts === 'undefined') return;
        const values = data.values.map(v => v.value);
        const stats  = data.stats;
        const n      = data.n;
        const highlightValue = data.highlight_value;
        const highlightProduct = data.highlight_product;

        // 自动分箱：用 Sturges 公式 k = ceil(log2(n) + 1)
        const nBins = Math.max(8, Math.min(80, Math.ceil(Math.log2(n) + 1)));
        const vmin = stats.min, vmax = stats.max;
        const binWidth = (vmax - vmin) / nBins || 1;
        const bins = [];
        let highlightBinIdx = -1;
        for (let i = 0; i < nBins; i++) {
            bins.push({ low: vmin + i * binWidth, high: vmin + (i + 1) * binWidth, count: 0 });
        }
        for (const v of values) {
            let idx = Math.min(nBins - 1, Math.max(0, Math.floor((v - vmin) / binWidth)));
            if (idx === nBins) idx = nBins - 1;
            bins[idx].count++;
        }
        // 找高亮产品所在的 bin
        if (highlightValue !== null && highlightValue !== undefined) {
            highlightBinIdx = Math.min(nBins - 1, Math.max(0, Math.floor((highlightValue - vmin) / binWidth)));
            if (highlightBinIdx === nBins) highlightBinIdx = nBins - 1;
        }

        // 用区间中点作为 x 值，Highcharts 可自动计算合适的刻度密度
        const binMids = bins.map(b => (b.low + b.high) / 2);
        const binCounts = bins.map(b => b.count);

        // 构建 tooltip 用的完整区间说明
        const binFullNames = bins.map((b, i) => {
            if (i === nBins - 1) return `[${b.low.toFixed(4)}, ${b.high.toFixed(4)}]`;
            return `[${b.low.toFixed(4)}, ${b.high.toFixed(4)})`;
        });

        // 构建数据点，高亮柱用不同颜色
        const seriesData = binMids.map((mid, i) => ({
            x: mid,
            y: binCounts[i],
            color: (i === highlightBinIdx) ? '#e74c3c' : '#0078d4',
        }));

        const pcts = stats.percentiles || {};
        const extraInfo = [];
        if (highlightProduct && highlightValue !== null && highlightValue !== undefined) {
            extraInfo.push(`${highlightProduct} 因子值=${highlightValue.toFixed(4)}`);
        }
        const subtitle = [
            `N=${n}`,
            `均值=${stats.mean?.toFixed(4)}`,
            `标准差=${stats.std?.toFixed(4)}`,
            `偏度=${stats.skewness?.toFixed(4)}`,
            `峰度=${stats.kurtosis?.toFixed(4)}`,
            `P1=${pcts['1']}`,
            `P99=${pcts['99']}`,
        ].concat(extraInfo).join(' ｜ ');

        Highcharts.chart(container, {
            chart: { type: 'column', zoomType: 'x' },
            title: { text: `${factorName} 截面分布`, style: { fontSize: '14px' } },
            subtitle: { text: subtitle, style: { fontSize: '11px', color: '#666' } },
            xAxis: {
                title: { text: '因子值' },
                crosshair: true,
                labels: { style: { fontSize: '10px' }, formatter: function() { return this.value.toFixed(4); } },
            },
            yAxis: {
                title: { text: '频数' },
                min: 0,
            },
            tooltip: {
                formatter: function() {
                    var tip = '<b>' + binFullNames[this.point.index] + '</b><br/>频数: <b>' + this.y + '</b>';
                    if (this.point.index === highlightBinIdx && highlightProduct) {
                        tip += '<br/>🔴 <b>' + highlightProduct + '</b> (' + highlightValue.toFixed(4) + ')';
                    }
                    return tip;
                },
            },
            series: [{
                name: '品种数',
                data: seriesData,
                pointPadding: 0,
                groupPadding: 0,
            }],
            plotOptions: {
                column: {
                    borderWidth: 0,
                },
            },
            credits: { enabled: false },
            legend: { enabled: false },
        });
    }

    // ── 长按因子列头 → 添加到因子库 ──
    function bindLongPressAddToLibrary(th, subId) {
        var helper = window.SingleFactorLibraryHelper;
        if (!helper) return;
        helper.bindLongPress(th, {
            popoverClass: 'ic-add-to-library-popover',
            getFactorAlias: function() {
                var colIdx = parseInt(th.getAttribute('data-col-idx'));
                if (isNaN(colIdx)) return null;
                var factors = window._icDataFactors && window._icDataFactors[subId];
                if (!factors || colIdx >= factors.length) return null;
                return factors[colIdx].alias || factors[colIdx].name || null;
            },
            getProductGroup: function() {
                return helper.inferScopeFromSubmissionId(subId);
            }
        });
    }

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }
})();
