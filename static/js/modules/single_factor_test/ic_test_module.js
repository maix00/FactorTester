/**
 * IC 测试模块独立脚本（重写版）
 * 支持因子级选择和频率配置
 */
(function() {
    // 全局变量
    let factorFamilyAlias = window.factorFamilyAlias || '';
    let factorList = [];  // 存储因子列表 [{alias, name, freq}]

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

    function drawComparisonChart(containerId, priceData, factorData, returnData, productName, factorName, subId, product) {
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
        const ohlcData     = priceData.dates.map((ts, i) => [_parseTs(ts), priceData.OPEN[i], priceData.HIGH[i], priceData.LOW[i], priceData.CLOSE[i]]);
        const factorValues = factorData.dates.map((ts, i) => [_parseTs(ts), factorData.values[i]]);
        const returnValues = returnData.dates.map((ts, i) => [_parseTs(ts), returnData.values[i]]);

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
                name: `${productName} 价格`,
                type: 'candlestick',
                data: ohlcData,
                yAxis: 0,
            },
            {
                name: `因子值`,
                type: 'line',
                data: factorValues,
                yAxis: 1,
                color: '#FF5722',
                id: 'factor'
            },
            {
                name: `下一期收益率`,
                type: 'line',
                data: returnValues,
                yAxis: 2,
                color: '#4CAF50',
                id: 'return'
            }
        ];

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
                name: `成交量`,
                type: 'column',
                data: volData,
                yAxis: nextIdx,
                color: '#90CAF9',
                id: 'volume'
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
                name: `持仓量`,
                type: 'line',
                data: oiData,
                yAxis: nextIdx,
                color: '#E91E63',
                id: 'oi'
            });
        }

        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: `${productName} — ${factorName}` },
            plotOptions: {
                series: {
                    point: {
                        events: {
                            click: function() {
                                if (this.series.options.id === 'factor') {
                                    openFactorDistribution(subId, factorName, this.x, product);
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
                            return `开: <b>${p.open.toFixed(2)}</b>  高: <b>${p.high.toFixed(2)}</b><br/>` +
                                   `低: <b>${p.low.toFixed(2)}</b>  收: <b>${p.close.toFixed(2)}</b>`;
                        }
                        if (pt.series.options.id === 'factor') {
                            return `因子值: <b>${pt.y.toFixed(4)}</b>`;
                        }
                        if (pt.series.options.id === 'return') {
                            return `收益率: <b>${(pt.y * 100).toFixed(2)}%</b>`;
                        }
                        if (pt.series.options.id === 'volume') {
                            return `成交量: <b>${pt.y.toFixed(0)}</b>`;
                        }
                        if (pt.series.options.id === 'oi') {
                            return `持仓量: <b>${pt.y.toFixed(0)}</b>`;
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
    }

    // Volume / OI 复选框切换时重绘对比图（全局函数，供 onchange 调用）
    window.icRedrawComparison = function(subId, idx) {
        const cacheKey = `${subId}-${idx}`;
        const cache = window._icComparisonCache && window._icComparisonCache[cacheKey];
        if (!cache) return;
        const { priceData, factorData, returnData, product, factorName } = cache;
        const chartDiv = document.getElementById(`factor-chart-${subId}-${idx}`);
        if (chartDiv) {
            chartDiv.style.height = '800px';
            drawComparisonChart(`factor-chart-${subId}-${idx}`, priceData, factorData, returnData, product, factorName, subId, product);
        }
    };

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

    // 构建统计表格 HTML
    function buildPrettyTable(data) {
        if (!data || !data.ic_stats || !data.ic_stats.columns || !data.ic_stats.rows || !data.ic_stats.columns.length) {
            return '<div class="ic-empty">无可展示结果</div>';
        }
        let html = '<div class="ic-table-wrap"><table class="ic-table"><thead><tr>';
        data.ic_stats.columns.forEach((col, i) => {
            html += '<th class="' + (i === 0 ? 'idx-col' : '') + '">' + col + '</th>';
        });
        html += '</tr></thead><tbody>';
        data.ic_stats.rows.forEach(row => {
            html += '<tr>';
            data.ic_stats.columns.forEach((col, i) => {
                let val = row[col];
                let display;
                if (val === null || val === undefined || val === '') {
                    display = '—';
                } else if (col === 'half_life' && !isFinite(val)) {
                    display = '∞';
                } else if (typeof val === 'number') {
                    display = Number.isInteger(val) ? val : val.toFixed(6);
                } else {
                    display = String(val);
                }
                html += '<td class="' + (i === 0 ? 'idx-col' : '') + '">' + display + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    // 渲染因子次级选项卡（IC 结果下方）
    function renderFactorTabs(subId, factors) {
        const container = document.getElementById(`factor-tabs-${subId}`);
        if (!container || !factors || factors.length === 0) {
            container.innerHTML = '<div class="ic-empty">暂无因子数据</div>';
            return;
        }
        let tabsHtml = '<ul class="nav nav-tabs" id="factor-tab-' + subId + '" role="tablist">';
        let panesHtml = '<div class="tab-content" id="factor-tab-content-' + subId + '">';
        factors.forEach((factor, idx) => {
            const activeClass = idx === 0 ? 'active' : '';
            const showClass = idx === 0 ? 'show active' : '';
            const tabId = `factor-tab-${subId}-${idx}`;
            const paneId = `factor-pane-${subId}-${idx}`;
            tabsHtml += `<li class="nav-item" role="presentation"><button class="nav-link ${activeClass}" id="${tabId}" data-bs-toggle="tab" data-bs-target="#${paneId}" type="button" role="tab">${factor.alias || factor.name}</button></li>`;
            const productOptions = (factor.products && factor.products.length) ? factor.products.map(p => `<option value="${p.name}">${p.name}${p.desc && p.desc !== p.name ? ' · ' + p.desc : ''}</option>`).join('') : '<option value="">无可用产品</option>';
            // IC 衰减 & 滚动窗口 附加图表（如有数据）
            let icDecayHtml = '';
            let rollingIcHtml = '';
            if (factor.ic_decay && factor.ic_decay.length > 0) {
                icDecayHtml = `<div style="margin-top:20px;"><h6>IC 衰减分析（多周期）</h6><div id="ic-decay-chart-${subId}-${idx}" style="width:100%; height:300px;"></div></div>`;
            }
            if (factor.rolling_ic && factor.rolling_ic.dates && factor.rolling_ic.dates.length > 0) {
                rollingIcHtml = `<div style="margin-top:20px;"><h6>滚动窗口 IC（窗口=${factor.rolling_ic.window}）</h6><div id="ic-rolling-chart-${subId}-${idx}" style="width:100%; height:350px;"></div></div>`;
            }
            panesHtml += `
                <div class="tab-pane fade ${showClass}" id="${paneId}" role="tabpanel">
                    <!-- IC 序列图 & 自相关衰减图 -->
                    <div style="display:flex; flex-wrap:wrap; gap:20px; margin-top:20px;">
                        <div style="flex:1;min-width:45%;"><h6>IC 序列</h6><div id="ic-chart-${subId}-${idx}" style="width:100%; height:350px;"></div></div>
                        <div style="flex:1;min-width:45%;"><h6>IC 自相关衰减</h6><div id="ic-acf-chart-${subId}-${idx}" style="width:100%; height:350px;"></div></div>
                    </div>
                    ${icDecayHtml}
                    ${rollingIcHtml}
                    <!-- 产品选择、加载按钮和复权复选框 -->
                    <div style="margin-top:16px;">
                        <label>选择产品：</label>
                        <select id="product-select-${subId}-${idx}" class="form-select" style="width:200px; display:inline-block; margin-left:8px;">${productOptions}</select>
                        <button class="btn btn-sm btn-outline-primary" data-sub="${subId}" data-idx="${idx}" data-factor-name="${factor.name}">加载因子和收益</button>
                        <label style="margin-left:12px;">
                            <input type="checkbox" id="adjust-price-${subId}-${idx}"> 复权价格
                        </label>
                        <label style="margin-left:12px;">
                            <input type="checkbox" id="show-volume-${subId}-${idx}" onchange="window.icRedrawComparison(${subId},${idx})"> 📊 成交量
                        </label>
                        <label style="margin-left:8px;">
                            <input type="checkbox" id="show-oi-${subId}-${idx}" onchange="window.icRedrawComparison(${subId},${idx})"> 📈 持仓量
                        </label>
                    </div>
                    <!-- 价格 / 因子值 / 收益率 三联图容器 -->
                    <div style="margin-top:8px;">
                        <p style="font-size:11px;color:#888;margin:0 0 4px 0;">💡 点击图中 <b style="color:#0078d4;">因子值</b> 曲线上的数据点可查看该时刻的截面分布</p>
                        <div id="factor-chart-${subId}-${idx}" style="width:100%;"></div>
                    </div>
                </div>
            `;
        });
        tabsHtml += '</ul>';
        panesHtml += '</div>';
        container.innerHTML = tabsHtml + panesHtml;
        // 初始化 Bootstrap 选项卡
        if (typeof bootstrap !== 'undefined') {
            const tabButtons = document.querySelectorAll(`#factor-tab-${subId} button[data-bs-toggle="tab"]`);
            tabButtons.forEach(btn => { new bootstrap.Tab(btn); btn.addEventListener('click', (e) => { e.preventDefault(); bootstrap.Tab.getOrCreateInstance(btn).show(); }); });
        }
        // 绘制 IC 图表
        factors.forEach((factor, idx) => {
            if (factor.ic_series && factor.ic_series.dates && factor.ic_series.values) {
                drawChart(`ic-chart-${subId}-${idx}`, factor.ic_series, 'IC');
            }
            // 绘制自相关衰减图
            if (factor.autocorr && factor.autocorr.length > 0) {
                drawAutocorrChart(`ic-acf-chart-${subId}-${idx}`, factor.autocorr);
            }
            // 绘制 IC 衰减分析图
            if (factor.ic_decay && factor.ic_decay.length > 0) {
                drawICDecayChart(`ic-decay-chart-${subId}-${idx}`, factor.ic_decay);
            }
            // 绘制滚动窗口 IC 图
            if (factor.rolling_ic && factor.rolling_ic.dates && factor.rolling_ic.dates.length > 0) {
                drawRollingICChart(`ic-rolling-chart-${subId}-${idx}`, factor.rolling_ic);
            }
        });
        // 绑定加载按钮事件
        document.querySelectorAll(`[data-sub="${subId}"]`).forEach(btn => {
            btn.removeEventListener('click', loadHandler);
            btn.addEventListener('click', loadHandler);
        });
        async function loadHandler(e) {
            const sub = e.currentTarget.getAttribute('data-sub');
            const idx = e.currentTarget.getAttribute('data-idx');
            const factorName = e.currentTarget.getAttribute('data-factor-name');
            await loadFactorAndReturn(sub, idx, factorName);
        }
    }

    // 加载因子值和收益率并绘图
    async function loadFactorAndReturn(subId, factorIdx, factorName) {
        const select = document.getElementById(`product-select-${subId}-${factorIdx}`);
        const product = select ? select.value : null;
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

        const factorInfo = factorList.find(f => f.name === factorName);
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
                        product: product
                    })
                }).then(r => _safeJson(r, 'get_factor_series')),
                fetch('/get_return_series', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        submission_id: subId,
                        factor_name: factorName,
                        factor_family_alias: factorFamilyAlias,
                        product: product,
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

            const factorDates = factorData.dates;
            // get_price_series expects ms timestamps; convert ISO strings (daily) if needed
            const factorDatesMs = factorDates.map(d => typeof d === 'string' ? new Date(d + 'T00:00:00Z').getTime() : d);
            const adjustCheckbox = document.getElementById(`adjust-price-${subId}-${factorIdx}`);
            const adjusted = adjustCheckbox ? adjustCheckbox.checked : false;
            const priceData = await fetch('/get_price_series', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    submission_id: subId,
                    product: product,
                    factor_family_alias: factorFamilyAlias,
                    factor_name: factorName,
                    factor_dates: factorDatesMs,
                    adjusted: adjusted,
                    start_date: submission.start_date,
                    end_date: submission.end_date
                })
            }).then(r => r.json());

            if (priceData.error) {
                var priceErr = 'get_price_series 错误: ' + priceData.error;
                if (priceData.traceback) {
                    factorChartDiv.innerHTML = '<div style="color:#d00; text-align:left;">' + priceErr + '</div>' +
                        `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:11px;overflow:auto;white-space:pre-wrap;margin-top:8px;">${priceData.traceback.replace(/</g,'&lt;')}</pre>`;
                    return;
                }
                throw new Error(priceErr);
            }

            if (priceData.dates && priceData.OPEN && factorData.dates && factorData.values && returnData.dates && returnData.values) {
                // 缓存数据以便 Volume/OI 复选框切换时重绘
                const cacheKey = `${subId}-${factorIdx}`;
                window._icComparisonCache = window._icComparisonCache || {};
                window._icComparisonCache[cacheKey] = { priceData, factorData, returnData, product, factorName };
                factorChartDiv.style.height = '800px';
                drawComparisonChart(`factor-chart-${subId}-${factorIdx}`, priceData, factorData, returnData, product, factorName, subId, product);
            } else {
                factorChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">价格、因子或收益率数据无效</div>';
            }
        } catch (err) {
            console.error('加载错误:', err);
            factorChartDiv.innerHTML = `<div style="color:#d00; text-align:center;">请求失败: ${err.message}</div>`;
        }
    }

    // 运行 IC 测试（核心修改）
    window.runIC = async function(subId) {
        const btn = document.getElementById(`run-ic-btn-${subId}`);
        const statusSpan = document.getElementById(`ic-status-${subId}`);
        const resultDiv = document.getElementById(`ic-result-${subId}`);
        if (!btn || !statusSpan || !resultDiv) return;

        // 获取强制重新计算复选框的状态
        const recalcCheckbox = document.getElementById(`recalc-checkbox-${subId}`);
        const re_calc = recalcCheckbox ? recalcCheckbox.checked : false;

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
            const response = await fetch('/run_ic_test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    submission_id: subId,
                    factor_family_alias: factorFamilyAlias,
                    paths: submission.paths,
                    factors: selectedFactors,  // 发送因子列表
                    re_calc: re_calc,
                    ic_decay_lags: ic_decay_lags,
                    rolling_window: rolling_window
                })
            });
            const data = await response.json();
            btn.disabled = false;
            if (!data.success) {
                statusSpan.innerText = '✗ IC测试失败: ' + data.error;
                statusSpan.style.color = '#d40000';
                if (data.traceback) {
                    resultDiv.innerHTML = `<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:12px;overflow:auto;white-space:pre-wrap;">${data.traceback.replace(/</g,'&lt;')}</pre>`;
                }
                return;
            }
            statusSpan.innerText = '✓ IC测试完成' + (data.paths_hash ? (' (路径哈希: ' + data.paths_hash + ')') : '');
            statusSpan.style.color = '#28a745';
            resultDiv.innerHTML = buildPrettyTable(data);
            // 创建次级选项卡容器
            const factorTabsId = `factor-tabs-${subId}`;
            let existingTabs = document.getElementById(factorTabsId);
            if (existingTabs) existingTabs.remove();
            const tabsContainer = document.createElement('div');
            tabsContainer.id = factorTabsId;
            tabsContainer.className = 'factor-tabs-container';
            resultDiv.appendChild(tabsContainer);
            renderFactorTabs(subId, data.factors);
            // 表格列头点击切换到对应因子选项卡
            const table = resultDiv.querySelector('.ic-table');
            if (table) {
                const headers = table.querySelectorAll('thead th:not(.idx-col)');
                headers.forEach((th, index) => {
                    th.style.cursor = 'pointer';
                    th.addEventListener('click', () => {
                        const tabId = `factor-tab-${subId}-${index}`;
                        const tabTrigger = document.getElementById(tabId);
                        if (tabTrigger && typeof bootstrap !== 'undefined') {
                            bootstrap.Tab.getOrCreateInstance(tabTrigger).show();
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
            tbody.innerHTML = '<tr><td colspan="2" style="color:#888;text-align:center;">暂无因子数据，请先选择因子家族。</td></tr>';
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
            rows += `<tr>
                <td><label><input type="checkbox" class="factor-checkbox" data-factor-alias="${f.alias}" checked> ${f.name}</label></td>
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

    // 弃用旧的内联面板生成，保留兼容性（返回空字符串）
    function buildFactorConfigPanel(subId, factors) {
        return '';
    }

    // 渲染主选项卡（外部调用）
    window.renderICTabs = async function(submissions) {
        const container = document.getElementById('ic-tab-container');
        if (!container) return;
        if (!submissions || submissions.length === 0) {
            container.innerHTML = '<div style="color:#888; padding:8px; border:1px dashed #ccc; border-radius:4px;">暂无测试器，请先添加测试器。</div>';
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
            tabsHtml += `<li class="nav-item"><button class="nav-link ${activeClass}" id="${tabId}" data-bs-toggle="tab" data-bs-target="#${panelId}" type="button" role="tab">${sub.label || sub.factor_tester_serial || ('测试器' + (idx+1))}</button></li>`;
            panelsHtml += `
                <div class="tab-pane fade ${showClass}" id="${panelId}" role="tabpanel">
                    <div class="ic-card">
                        <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 12px;">
                            <button class="btn btn-primary btn-sm" id="run-ic-btn-${sub.id}" onclick="runIC('${sub.id}')">运行IC测试</button>
                            <label style="font-size: 13px;">
                                <input type="checkbox" id="recalc-checkbox-${sub.id}"> 强制重新计算（忽略缓存）
                            </label>
                            <span id="ic-status-${sub.id}" class="ic-status"></span>
                        </div>
                        <!-- IC 衰减 & 滚动窗口 参数 -->
                        <div style="display:flex; gap:16px; flex-wrap:wrap; align-items:center; margin-bottom:10px; padding:8px 12px; background:#f8fafc; border-radius:6px; border:1px solid #e5e7eb;">
                            <span style="font-size:12px; font-weight:600; color:#555;">扩展分析:</span>
                            <label style="font-size:12px; margin-bottom:0; display:flex; align-items:center; gap:4px;">
                                IC衰减滞后期
                                <input type="text" id="ic-decay-lags-${sub.id}" value="" placeholder="1,2,3,5,10,20"
                                       style="width:110px; font-size:12px; padding:2px 6px;" title="逗号分隔的滞后期数，计算各周期IC统计量">
                            </label>
                            <label style="font-size:12px; margin-bottom:0; display:flex; align-items:center; gap:4px;">
                                滚动窗口
                                <input type="number" id="ic-rolling-window-${sub.id}" value="" placeholder="如60"
                                       min="2" max="1000" style="width:70px; font-size:12px; padding:2px 6px;" title="滚动窗口大小（期数），计算每窗 IC Mean 和 IR">
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

    document.addEventListener('DOMContentLoaded', async () => {
        initFreqDrawerButtons();
        if (window.submissions && window.submissions.length) {
            await window.renderICTabs(window.submissions);
        }
    });

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

    async function openFactorDistribution(subId, factorName, tsMs, product) {
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

})();