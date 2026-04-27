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

    function drawComparisonChart(containerId, priceData, factorData, returnData, productName, factorName) {
        if (typeof Highcharts === 'undefined') return;
        const container = document.getElementById(containerId);
        if (!container) return;

        const _parseTs = ts => typeof ts === 'string' ? new Date(ts + 'T00:00:00').getTime() : ts;
        const isDaily = factorData.dates.length > 0 && typeof factorData.dates[0] === 'string';
        const _fmtHeader = isDaily
            ? x => Highcharts.dateFormat('%Y-%m-%d', x)
            : x => Highcharts.dateFormat('%Y-%m-%d %H:%M', x);
        const ohlcData     = priceData.dates.map((ts, i) => [_parseTs(ts), priceData.OPEN[i], priceData.HIGH[i], priceData.LOW[i], priceData.CLOSE[i]]);
        const factorValues = factorData.dates.map((ts, i) => [_parseTs(ts), factorData.values[i]]);
        const returnValues = returnData.dates.map((ts, i) => [_parseTs(ts), returnData.values[i]]);

        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: `${productName} — ${factorName}` },
            xAxis: { type: 'datetime', crosshair: true },
            yAxis: [
                {   // 价格轴
                    labels: { format: '{value:.2f}', align: 'right', x: -8 },
                    title: { text: '价格' },
                    height: '50%',
                    lineWidth: 1,
                    resize: { enabled: true }
                },
                {   // 因子值轴
                    labels: { format: '{value:.4f}', align: 'right', x: -8 },
                    title: { text: '因子值' },
                    top: '52%',
                    height: '26%',
                    offset: 0,
                    lineWidth: 1
                },
                {   // 收益率轴
                    labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; }, align: 'right', x: -8 },
                    title: { text: '收益率' },
                    top: '80%',
                    height: '20%',
                    offset: 0,
                    lineWidth: 1
                }
            ],
            // split: true — 每个面板（yAxis 段）各自显示独立的 tooltip 气泡
            tooltip: {
                split: true,
                formatter: function() {
                    // 返回数组：第一项为 header（时间），后续每项对应一条 series
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
                        return `${pt.series.name}: <b>${pt.y}</b>`;
                    }));
                }
            },
            series: [
                {
                    name: `${productName} 价格`,
                    type: 'candlestick',
                    data: ohlcData,
                    yAxis: 0,
                    dataGrouping: { enabled: false }
                },
                {
                    name: `因子值`,
                    id: 'factor',
                    type: 'line',
                    data: factorValues,
                    yAxis: 1,
                    color: '#FF5722',
                    dataGrouping: { enabled: false },
                    connectNulls: true,
                    marker: { enabled: true, radius: 2 }
                },
                {
                    name: `下一期收益率`,
                    id: 'return',
                    type: 'line',
                    data: returnValues,
                    yAxis: 2,
                    color: '#4CAF50',
                    dataGrouping: { enabled: false },
                    connectNulls: true,
                    marker: { enabled: true, radius: 2 }
                }
            ],
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: true }
        });
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
                let display = (val === null || val === undefined || val === '') ? '—' : (typeof val === 'number' ? (Number.isInteger(val) ? val : val.toFixed(6)) : String(val));
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
            panesHtml += `
                <div class="tab-pane fade ${showClass}" id="${paneId}" role="tabpanel">
                    <!-- IC 序列图 -->
                    <div style="display:flex; flex-wrap:wrap; gap:20px; margin-top:20px;">
                        <div style="width:100%;"><h6>IC 序列</h6><div id="ic-chart-${subId}-${idx}" style="width:100%; height:350px;"></div></div>
                    </div>
                    <!-- 产品选择、加载按钮和复权复选框 -->
                    <div style="margin-top:16px;">
                        <label>选择产品：</label>
                        <select id="product-select-${subId}-${idx}" class="form-select" style="width:200px; display:inline-block; margin-left:8px;">${productOptions}</select>
                        <button class="btn btn-sm btn-outline-primary" data-sub="${subId}" data-idx="${idx}" data-factor-name="${factor.name}">加载因子和收益</button>
                        <label style="margin-left:12px;">
                            <input type="checkbox" id="adjust-price-${subId}-${idx}"> 复权价格
                        </label>
                    </div>
                    <!-- 价格 / 因子值 / 收益率 三联图容器 -->
                    <div style="margin-top:8px;">
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
                factorChartDiv.style.height = '800px';
                drawComparisonChart(`factor-chart-${subId}-${factorIdx}`, priceData, factorData, returnData, product, factorName);
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
        try {
            const response = await fetch('/run_ic_test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    submission_id: subId,
                    factor_family_alias: factorFamilyAlias,
                    paths: submission.paths,
                    factors: selectedFactors,  // 发送因子列表
                    re_calc: re_calc   // 新增参数
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
})();