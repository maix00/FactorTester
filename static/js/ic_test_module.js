/**
 * IC 测试模块独立脚本
 * 功能：显示测试器选项卡、运行 IC 测试、展示统计表格和因子次级选项卡、绘制 Highcharts 图表
 * 依赖：Bootstrap, Highcharts, jQuery (如果 Fancytree 未加载则不影响，但本模块需要 jQuery 用于 DOM 操作？实际上原代码使用原生 JS，我们保持一致)
 */
(function() {
    // 全局 submissions 数组（由 category_filter_module 维护，我们需要监听其变化）
    // 由于 submissions 在 category_filter_module.js 中定义，我们需要通过全局变量共享
    // 假设 category_filter_module.js 将 submissions 暴露为 window.submissions
    // 或者我们在此模块中自己维护提交记录？更好的方式是监听自定义事件，或者直接访问全局变量。
    // 原实现中 submissions 在 category_filter_module 中是全局的，并且 renderICTabs 被调用时会传入 submissions。
    // 我们保留原有接口：window.renderICTabs(submissions) 由外部调用（category_filter_module 中提交后调用）。
    // 因此此模块需要暴露 renderICTabs 和 runIC 等函数供外部调用。

    let factorFamilyAlias = window.factorFamilyAlias || '';

    if (typeof Highcharts !== 'undefined') {
        Highcharts.setOptions({
            global: { useUTC: false }
        });
    }

    // 辅助函数：格式化表格单元格
    function fmtCell(v) {
        if (v === null || v === undefined || v === '') return '—';
        if (typeof v === 'number') return Number.isInteger(v) ? v : v.toFixed(6);
        return String(v);
    }

    // 构建 IC 统计表格 HTML
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
                html += '<td class="' + (i === 0 ? 'idx-col' : '') + '">' + fmtCell(row[col]) + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    // 绘制 Highstock 图表（支持时间序列）
    function drawChart(containerId, seriesData, seriesName) {
        if (!seriesData || !seriesData.dates || !seriesData.values) return;
        const container = document.getElementById(containerId);
        if (!container) return;

        // 直接使用时间戳和值
        const data = seriesData.dates.map((ts, i) => [ts, seriesData.values[i]]);

        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: null },
            xAxis: { type: 'datetime' },  // ordinal 默认为 true
            yAxis: { title: { text: seriesName } },
            series: [{ name: seriesName, data: data, type: 'line', dataGrouping: { enabled: false } }],
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: true }  // 可以保留
        });
    }

    // 渲染因子次级选项卡（在 IC 测试结果下方）
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

            tabsHtml += `
                <li class="nav-item" role="presentation">
                    <button style="font-size:12px;" class="nav-link ${activeClass}" id="${tabId}" data-bs-toggle="tab" data-bs-target="#${paneId}" type="button" role="tab">
                        ${factor.alias || factor.name}
                    </button>
                </li>
            `;

            const productOptions = (factor.products && factor.products.length)
                ? factor.products.map(p => `<option value="${p}">${p}</option>`).join('')
                : '<option value="">无可用产品</option>';

            panesHtml += `
                <div class="tab-pane fade ${showClass}" id="${paneId}" role="tabpanel">
                    <div style="display:flex; flex-wrap:wrap; gap:20px; margin-top:20px;">
                        <div style="width:100%;">
                            <h6 style="font-size:13px; margin:0;">IC 序列</h6>
                            <div id="ic-chart-${subId}-${idx}" style="width:100%; height:350px;"></div>
                        </div>
                    </div>
                    <div style="margin-top:16px;">
                        <label style="font-size:13px;">选择产品：</label>
                        <select id="product-select-${subId}-${idx}" class="form-select" style="width:200px; display:inline-block; margin-left:8px; font-size:12px;">
                            ${productOptions}
                        </select>
                        <button class="btn btn-sm btn-outline-primary" data-sub="${subId}" data-idx="${idx}" data-factor-name="${factor.name}" style="margin-left:8px;">加载因子和收益</button>
                    </div>
                    <div style="display:flex; flex-wrap:wrap; gap:20px; margin-top:20px;">
                        <div style="width:100%;">
                            <h6 style="font-size:13px; margin:0;">因子值序列</h6>
                            <div id="factor-chart-${subId}-${idx}" style="width:100%; height:350px;">
                                <div style="color:#888; text-align:center; padding:40px;">请选择产品并点击加载</div>
                            </div>
                        </div>
                        <div style="width:100%;">
                            <h6 style="font-size:13px; margin:0;">收益率序列</h6>
                            <div id="return-chart-${subId}-${idx}" style="width:100%; height:350px;">
                                <div style="color:#888; text-align:center; padding:40px;">请选择产品并点击加载</div>
                            </div>
                        </div>
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
            tabButtons.forEach(btn => {
                const tab = new bootstrap.Tab(btn);
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    tab.show();
                });
            });
        }

        // 绘制每个因子的 IC 图表（数据已存在）
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

        function loadHandler(e) {
            const sub = e.currentTarget.getAttribute('data-sub');
            const idx = e.currentTarget.getAttribute('data-idx');
            const factorName = e.currentTarget.getAttribute('data-factor-name');
            loadFactorAndReturn(sub, idx, factorName);
        }
    }

    // 加载因子值和收益率并绘图
    async function loadFactorAndReturn(subId, factorIdx, factorName) {
        const select = document.getElementById(`product-select-${subId}-${factorIdx}`);
        const product = select ? select.value : null;
        if (!product || product === '') {
            alert('请选择一个产品');
            return;
        }

        // 获取当前提交对象
        const submission = window.submissions?.find(s => s.id == subId);
        if (!submission) {
            console.error('未找到提交记录');
            // 显示错误提示...
            return;
        }

        const factorChartDiv = document.getElementById(`factor-chart-${subId}-${factorIdx}`);
        const returnChartDiv = document.getElementById(`return-chart-${subId}-${factorIdx}`);
        factorChartDiv.innerHTML = '<div style="color:#888; text-align:center; padding:40px;">加载因子值...</div>';
        returnChartDiv.innerHTML = '<div style="color:#888; text-align:center; padding:40px;">加载收益率...</div>';

        try {
            const [factorData, returnData] = await Promise.all([
                fetch('/get_factor_series', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        submission_id: subId, 
                        factor_name: factorName,
                        factor_family_alias: factorFamilyAlias,
                        product: product 
                    })
                }).then(r => r.json()),
                fetch('/get_return_series', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        submission_id: subId, 
                        factor_name: factorName,
                        factor_family_alias: factorFamilyAlias,
                        product: product,
                        paths: submission.paths,
                    })
                }).then(r => r.json())
            ]);

            if (factorData.dates && factorData.values) {
                drawChart(`factor-chart-${subId}-${factorIdx}`, factorData, '因子值');
            } else {
                factorChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">加载因子值失败</div>';
            }
            if (returnData.dates && returnData.values) {
                drawChart(`return-chart-${subId}-${factorIdx}`, returnData, '收益率');
            } else {
                returnChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">加载收益率失败</div>';
            }
        } catch (err) {
            factorChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">请求失败</div>';
            returnChartDiv.innerHTML = '<div style="color:#d00; text-align:center;">请求失败</div>';
            console.error('加载错误:', err);
        }
    }

    // 运行 IC 测试
    window.runIC = async function(subId) {
        const btn = document.getElementById(`run-ic-btn-${subId}`);
        const statusSpan = document.getElementById(`ic-status-${subId}`);
        const resultDiv = document.getElementById(`ic-result-${subId}`);
        if (!btn || !statusSpan || !resultDiv) return;

        btn.disabled = true;
        statusSpan.innerText = 'IC测试运行中...';
        statusSpan.style.color = '#0078d4';
        resultDiv.innerHTML = '';

        // 从全局 submissions 获取该提交的路径
        const submission = window.submissions ? window.submissions.find(s => s.id == subId) : null;
        if (!submission) {
            statusSpan.innerText = '错误：未找到提交';
            btn.disabled = false;
            return;
        }

        try {
            const response = await fetch('/run_ic_test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    submission_id: subId,
                    factor_family_alias: factorFamilyAlias,
                    paths: submission.paths,
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

            // 渲染因子次级选项卡
            renderFactorTabs(subId, data.factors);

            // 为统计表格的每个因子列头添加点击事件，点击后切换到对应的因子选项卡
            const table = resultDiv.querySelector('.ic-table');
            if (table) {
                const headers = table.querySelectorAll('thead th:not(.idx-col)');
                headers.forEach((th, index) => {
                    th.style.cursor = 'pointer';
                    th.title = '点击切换到对应因子';
                    th.addEventListener('click', () => {
                        const tabId = `factor-tab-${subId}-${index}`;
                        const tabTrigger = document.getElementById(tabId);
                        if (tabTrigger && typeof bootstrap !== 'undefined') {
                            const tab = new bootstrap.Tab(tabTrigger);
                            tab.show();
                        }
                    });
                });
            }

            // 隐藏原有的 Highcharts 大容器（因为 IC 图表已经移到次级选项卡内）
            const chartContainer = document.getElementById(`chart-container-${subId}`);
            if (chartContainer) chartContainer.style.display = 'none';
        } catch (err) {
            btn.disabled = false;
            statusSpan.innerText = '前端错误: ' + err.message;
            statusSpan.style.color = '#d40000';
        }
    };

    // 渲染主选项卡（供外部调用，例如 category_filter_module 提交后调用）
    window.renderICTabs = function(submissions) {
        const container = document.getElementById('ic-tab-container');
        if (!container) return;
        if (!submissions || submissions.length === 0) {
            container.innerHTML = '<div style="color:#888; padding:8px; border:1px dashed #ccc; border-radius:4px;">暂无测试器，请先添加测试器。</div>';
            return;
        }

        let tabsHtml = '<ul class="nav nav-tabs" id="icTab" role="tablist">';
        let panelsHtml = '<div class="tab-content" id="icTabContent">';

        submissions.forEach((sub, idx) => {
            const activeClass = idx === 0 ? 'active' : '';
            const showClass = idx === 0 ? 'show active' : '';
            const tabId = `ic-tab-${sub.id}`;
            const panelId = `ic-panel-${sub.id}`;

            tabsHtml += `
                <li class="nav-item" role="presentation">
                    <button style="font-size:12px;" class="nav-link ${activeClass}" id="${tabId}" data-bs-toggle="tab" data-bs-target="#${panelId}" type="button" role="tab">
                        ${sub.factor_tester_serial || ('测试器' + (idx + 1))}
                    </button>
                </li>
            `;

            panelsHtml += `
                <div class="tab-pane fade ${showClass}" id="${panelId}" role="tabpanel">
                    <div class="ic-card">
                        <button class="btn btn-primary btn-sm" id="run-ic-btn-${sub.id}" onclick="runIC('${sub.id}')">运行IC测试</button>
                        <span id="ic-status-${sub.id}" class="ic-status" style="color:#0078d4;"></span>
                        <div id="ic-result-${sub.id}"></div>
                        <div id="chart-container-${sub.id}" style="width:100%; height:460px; margin-top:14px;"></div>
                    </div>
                </div>
            `;
        });

        tabsHtml += '</ul>';
        panelsHtml += '</div>';
        container.innerHTML = tabsHtml + panelsHtml;

        // 激活 Bootstrap 选项卡
        if (typeof bootstrap !== 'undefined') {
            const tabTriggers = document.querySelectorAll('#icTab button[data-bs-toggle="tab"]');
            tabTriggers.forEach(trigger => {
                const tab = new bootstrap.Tab(trigger);
                trigger.addEventListener('click', (e) => {
                    e.preventDefault();
                    tab.show();
                });
            });
        }
    };

    // 如果全局已有 submissions，立即渲染（可选，但通常由 category_filter 模块在提交后调用）
    if (window.submissions && window.submissions.length) {
        window.renderICTabs(window.submissions);
    }
})();

// 在文件最后，IIFE 之外
document.addEventListener('DOMContentLoaded', function() {
    if (window.submissions && window.submissions.length) {
        window.renderICTabs(window.submissions);
    }
});