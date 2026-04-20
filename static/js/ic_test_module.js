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

        // 构建 OHLC 数据
        const ohlcData = priceData.dates.map((ts, i) => [
            ts,
            priceData.OPEN[i],
            priceData.HIGH[i],
            priceData.LOW[i],
            priceData.CLOSE[i]
        ]);
        // 因子值数据
        const factorValues = factorData.dates.map((ts, i) => [ts, factorData.values[i]]);
        // 收益率数据
        const returnValues = returnData.dates.map((ts, i) => [ts, returnData.values[i]]);

        Highcharts.stockChart(container, {
            chart: { zoomType: 'xy' },
            title: { text: `${productName} - 价格 vs ${factorName} vs 收益率` },
            xAxis: { type: 'datetime' },
            yAxis: [
                {   // 价格轴（左侧）
                    labels: { format: '{value:.2f}' },
                    title: { text: '价格' },
                    height: '50%',
                    resize: { enabled: true }
                },
                {   // 因子值轴（右侧，独占一段）
                    labels: { format: '{value:.4f}' },
                    title: { text: '因子值' },
                    top: '55%',          // 从 55% 开始
                    height: '25%',       // 占 25% 高度
                    opposite: true,
                    offset: 0
                },
                {   // 收益率轴（右侧，独占另一段）
                    labels: {
                        formatter: function() {
                            // 假设收益率数据为小数（0.05 → 5.00%）
                            return (this.value * 100).toFixed(2) + '%';
                        }
                    },
                    title: { text: '下一期收益率' },
                    top: '82%',          // 从 82% 开始
                    height: '15%',       // 占 15% 高度
                    opposite: true,
                    offset: 0
                }
            ],
            tooltip: {
                shared: true,
                formatter: function() {
                    const points = this.points;
                    let result = '';
                    points.forEach(point => {
                        if (point.series.type === 'candlestick') {
                            result += `<b>${point.series.name}</b><br/>
                                    开盘: ${point.point.open.toFixed(2)}<br/>
                                    最高: ${point.point.high.toFixed(2)}<br/>
                                    最低: ${point.point.low.toFixed(2)}<br/>
                                    收盘: ${point.point.close.toFixed(2)}<br/>`;
                        } else if (point.series.userOptions.id === 'factor') {
                            result += `<b>${point.series.name}</b><br/>
                                    因子值: ${point.y.toFixed(4)}<br/>`;
                        } else if (point.series.userOptions.id === 'return') {
                            result += `<b>${point.series.name}</b><br/>
                                    收益率: ${(point.y * 100).toFixed(2)}%<br/>`;
                        }
                        result += `<span style="color:#666">时间: ${Highcharts.dateFormat('%Y-%m-%d %H:%M:%S', point.x)}</span><br/><br/>`;
                    });
                    return result;
                }
            },
            series: [{
                name: `${productName} 价格`,
                type: 'candlestick',
                data: ohlcData,
                yAxis: 0
            }, {
                name: `因子值`,
                type: 'line',
                data: factorValues,
                yAxis: 1,
                color: '#FF5722',
                id: 'factor'
            }, {
                name: `下一期收益率`,
                type: 'line',
                data: returnValues,
                yAxis: 2,
                color: '#4CAF50',
                id: 'return'
            }],
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
        const data = seriesData.dates.map((ts, i) => [ts, seriesData.values[i]]);
        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: null },
            xAxis: { type: 'datetime', ordinal: true },
            yAxis: { title: { text: seriesName }, crosshair: true },
            tooltip: { shared: true, valueDecimals: 4, xDateFormat: '%Y-%m-%d %H:%M:%S' },
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
                    <!-- 因子值序列和收益率序列容器 -->
                    <div style="display:flex; flex-wrap:wrap; gap:20px; margin-top:20px;">
                        <div style="width:100%;"><div id="factor-chart-${subId}-${idx}" style="width:100%; height:800px;"><div style="color:#888; text-align:center; padding:40px;">请选择产品并点击加载</div></div></div>
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
        factorChartDiv.innerHTML = '<div style="color:#888; text-align:center; padding:40px;">加载价格与因子值...</div>';

        const submission = window.submissions ? window.submissions.find(s => s.id == subId) : null;
        if (!submission) { 
            factorChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">未找到提交记录</div>'; 
            return; 
        }

        const factorInfo = factorList.find(f => f.name === factorName);
        const freq = (factorInfo && factorInfo.freq !== 'N') ? factorInfo.freq : '1D';

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
                }).then(r => r.json()),
                fetch('/get_return_series', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        submission_id: subId,
                        factor_name: factorName,
                        factor_family_alias: factorFamilyAlias,
                        product: product,
                        paths: submission.paths
                    })
                }).then(r => r.json())
            ]);

            const factorDates = factorData.dates;
            const adjustCheckbox = document.getElementById(`adjust-price-${subId}-${factorIdx}`);
            const adjusted = adjustCheckbox ? adjustCheckbox.checked : false;
            const priceData = await fetch('/get_price_series', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    submission_id: subId,
                    product: product,
                    factor_family_alias: factorFamilyAlias,
                    factor_name: factorName,
                    factor_dates: factorDates,
                    adjusted: adjusted,
                    start_date: submission.start_date,
                    end_date: submission.end_date
                })
            }).then(r => r.json());

            if (priceData.dates && priceData.OPEN && factorData.dates && factorData.values && returnData.dates && returnData.values) {
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

        // 收集选中的因子及频率
        const selectedFactors = [];
        const checkboxes = document.querySelectorAll(`#factor-config-${subId} .factor-checkbox:checked`);
        if (checkboxes.length === 0) {
            statusSpan.innerText = '请至少选择一个因子';
            statusSpan.style.color = '#d40000';
            return;
        }
        checkboxes.forEach(cb => {
            const alias = cb.getAttribute('data-factor-alias');
            const freqSelect = document.querySelector(`#factor-config-${subId} .factor-freq-select[data-factor-alias="${alias}"]`);
            const return_freq = freqSelect ? freqSelect.value : 'N';
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

    // 生成因子配置面板 HTML
    function buildFactorConfigPanel(subId, factors) {
        if (!factors || factors.length === 0) return '<div class="ic-empty">暂无因子数据，请先选择因子家族。</div>';
        let rows = '';
        factors.forEach(f => {
            rows += `<tr>
                <td><label><input type="checkbox" class="factor-checkbox" data-factor-alias="${f.alias}" checked> ${f.name}</label></td>
                <td><select class="factor-freq-select" data-factor-alias="${f.alias}" style="width:120px;">
                    <option value="N">原生频率 (${f.freq || 'N'})</option>
                    <option value="1min">1分钟</option><option value="5min">5分钟</option><option value="15min">15分钟</option>
                    <option value="30min">30分钟</option><option value="1H">1小时</option><option value="1D">1天</option>
                </select></td>
            </tr>`;
        });
        return `
            <div class="factor-config-panel" id="factor-config-${subId}">
                <div class="factor-config-header" onclick="document.getElementById('factor-config-content-${subId}').classList.toggle('expanded')">
                    <span>📊 因子配置 (点击展开/折叠)</span>
                    <span>▼</span>
                </div>
                <div class="factor-config-content" id="factor-config-content-${subId}">
                    <div class="factor-config-actions">
                        <button class="btn btn-sm btn-outline-primary" id="select-all-${subId}">全选</button>
                        <button class="btn btn-sm btn-outline-primary" id="deselect-all-${subId}">全不选</button>
                        <button class="btn btn-sm btn-outline-primary" id="reset-freq-${subId}">重置频率为原生</button>
                    </div>
                    <table class="factor-config-table">
                        <thead><tr><th>因子名称</th><th>收益率频率</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
            <script>
                document.getElementById('select-all-${subId}').onclick = () => { document.querySelectorAll('#factor-config-${subId} .factor-checkbox').forEach(cb => cb.checked = true); };
                document.getElementById('deselect-all-${subId}').onclick = () => { document.querySelectorAll('#factor-config-${subId} .factor-checkbox').forEach(cb => cb.checked = false); };
                document.getElementById('reset-freq-${subId}').onclick = () => {
                    document.querySelectorAll('#factor-config-${subId} .factor-freq-select').forEach(sel => sel.value = 'N');
                };
            </script>
        `;
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
        let tabsHtml = '<ul class="nav nav-tabs" id="icTab" role="tablist">';
        let panelsHtml = '<div class="tab-content" id="icTabContent">';
        submissions.forEach((sub, idx) => {
            const activeClass = idx === 0 ? 'active' : '';
            const showClass = idx === 0 ? 'show active' : '';
            const tabId = `ic-tab-${sub.id}`;
            const panelId = `ic-panel-${sub.id}`;
            tabsHtml += `<li class="nav-item"><button class="nav-link ${activeClass}" id="${tabId}" data-bs-toggle="tab" data-bs-target="#${panelId}" type="button" role="tab">${sub.factor_tester_serial || ('测试器' + (idx+1))}</button></li>`;
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
                        ${buildFactorConfigPanel(sub.id, factorList)}
                        <div id="ic-result-${sub.id}"></div>
                        <div id="chart-container-${sub.id}" style="width:100%; height:460px; margin-top:14px;"></div>
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
    };

    // 页面加载完成后，如果已有 submissions，则渲染
    document.addEventListener('DOMContentLoaded', async () => {
        if (window.submissions && window.submissions.length) {
            await window.renderICTabs(window.submissions);
        }
    });

    // 供参数模块调用，刷新因子列表和 IC 选项卡
    window.refreshICModule = async function() {
        console.log('刷新 IC 模块因子列表');
        await fetchFactorList();  // 重新获取因子列表
        if (window.submissions && window.submissions.length) {
            await window.renderICTabs(window.submissions);
        }
        window.factorList = factorList;
    };

    window.factorList = factorList;
})();