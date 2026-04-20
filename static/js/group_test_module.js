/**
 * 分组测试模块独立脚本
 */
(function() {
    let currentSubmissionId = null;
    let currentFactorAlias = null;

    // 获取当前选中的 submission 和 factor alias（与 IC 模块联动）
    function getCurrentContext() {
        // 1. 获取 IC 模块中当前激活的选项卡
        const activeIcTab = document.querySelector('#icTab .nav-link.active');
        if (!activeIcTab) return null;
        const panelId = activeIcTab.getAttribute('data-bs-target');
        if (!panelId) return null;
        const panel = document.querySelector(panelId);
        if (!panel) return null;
        
        // 从 panelId 中提取 submission id
        const match = panelId.match(/ic-panel-(\d+)/);
        if (!match) return null;
        const subId = match[1];
        
        // 2. 获取该 submission 面板中当前激活的因子选项卡
        const activeFactorTab = panel.querySelector('.factor-tabs-container .nav-link.active');
        if (!activeFactorTab) return null;
        const factorName = activeFactorTab.textContent.trim();
        
        // 从全局 factorList 中找到 alias
        const factorInfo = window.factorList ? window.factorList.find(f => f.name === factorName || f.alias === factorName) : null;
        if (!factorInfo) return null;
        
        return { submission_id: subId, factor_alias: factorInfo.alias };
    }

    // 清空之前的测试结果
    function clearResults() {
        const chartContainer = document.getElementById('group_chart_container');
        const metricsContainer = document.getElementById('group_metrics_container');
        if (chartContainer) chartContainer.style.display = 'none';
        if (metricsContainer) metricsContainer.style.display = 'none';
        document.getElementById('group_test_status').innerHTML = '';
    }

    // 绘制分组累计收益曲线
    function drawGroupChart(groups) {
        const container = document.getElementById('group_chart_container');
        if (!container || !groups || groups.length === 0) {
            container.style.display = 'none';
            return;
        }
        container.style.display = 'block';
        
        const series = groups.map(group => ({
            name: group.name,
            type: 'line',
            data: group.cumulative_returns
                .map((val, idx) => val !== null ? [group.timestamps[idx], val] : null)
                .filter(pt => pt !== null),
            tooltip: { valueDecimals: 4 }
        }));
        
        Highcharts.stockChart(container, {
            chart: { zoomType: 'x' },
            title: { text: '分组累计收益（初始净值 = 1）' },
            xAxis: { type: 'datetime' },
            yAxis: { title: { text: '净值' }, crosshair: true },
            tooltip: { shared: true, valueDecimals: 4, xDateFormat: '%Y-%m-%d' },
            series: series,
            navigator: { enabled: true },
            scrollbar: { enabled: true },
            rangeSelector: {
                enabled: true,
                selected: undefined,
                buttons: [
                    { type: 'month', count: 1, text: '1M' },
                    { type: 'month', count: 3, text: '3M' },
                    { type: 'month', count: 6, text: '6M' },
                    { type: 'year', count: 1, text: '1Y' },
                    { type: 'all', text: 'All' }
                ]
            }
        });
    }

    // 渲染统计指标表格
    function renderMetricsTable(metrics) {
        const container = document.getElementById('group_metrics_container');
        if (!container || !metrics || Object.keys(metrics).length === 0) {
            container.style.display = 'none';
            return;
        }
        container.style.display = 'block';
        
        // 获取所有指标名称（假设所有分组指标相同）
        const firstGroup = Object.values(metrics)[0];
        const metricNames = Object.keys(firstGroup);
        
        // 表头
        let theadHtml = '<tr><th>分组</th>';
        metricNames.forEach(name => {
            theadHtml += `<th>${name}</th>`;
        });
        theadHtml += '</tr>';
        document.getElementById('metrics_head').innerHTML = theadHtml;
        
        // 表体
        let tbodyHtml = '';
        for (const [groupIdx, groupMetrics] of Object.entries(metrics)) {
            tbodyHtml += '<tr>';
            tbodyHtml += `<td><strong>${groupIdx}</strong></td>`;
            metricNames.forEach(name => {
                let val = groupMetrics[name];
                if (typeof val === 'number') {
                    if (name.includes('Rate') || name.includes('Return') || name.includes('Drawdown')) {
                        val = val.toFixed(2) + '%';
                    } else if (name.includes('Ratio')) {
                        val = val.toFixed(4);
                    } else {
                        val = val.toFixed(4);
                    }
                }
                tbodyHtml += `<td>${val}</td>`;
            });
            tbodyHtml += '</tr>';
        }
        document.getElementById('metrics_body').innerHTML = tbodyHtml;
    }

    // 运行分组测试
    async function runGroupTest() {
        const context = getCurrentContext();
        if (!context) {
            alert('请先在 IC 测试模块中运行 IC 测试，并点击某个因子的选项卡');
            return;
        }
        currentSubmissionId = context.submission_id;
        currentFactorAlias = context.factor_alias;
        
        const n_groups = parseInt(document.getElementById('group_count').value, 10);
        const fee = parseFloat(document.getElementById('fee_rate').value) || 0.0;
        let start_date = document.getElementById('group_start_date').value;
        let end_date = document.getElementById('group_end_date').value;
        
        // 如果未填写时间范围，尝试从 submission 中获取
        if (!start_date || !end_date) {
            const submission = window.submissions ? window.submissions.find(s => s.id == currentSubmissionId) : null;
            if (submission) {
                if (!start_date) start_date = submission.start_date;
                if (!end_date) end_date = submission.end_date;
            }
        }
        
        const statusSpan = document.getElementById('group_test_status');
        statusSpan.innerHTML = '分组测试运行中...';
        statusSpan.style.color = '#0078d4';
        
        try {
            const response = await fetch('/run_group_test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    submission_id: currentSubmissionId,
                    factor_alias: currentFactorAlias,
                    n_groups: n_groups,
                    fee: fee,
                    start_date: start_date,
                    end_date: end_date
                })
            });
            const data = await response.json();
            if (!data.success) {
                statusSpan.innerHTML = '✗ 分组测试失败: ' + data.error;
                statusSpan.style.color = '#d40000';
                return;
            }
            statusSpan.innerHTML = '✓ 分组测试完成';
            statusSpan.style.color = '#28a745';
            
            drawGroupChart(data.groups);
            renderMetricsTable(data.metrics);
        } catch (err) {
            statusSpan.innerHTML = '请求失败: ' + err.message;
            statusSpan.style.color = '#d40000';
            console.error(err);
        }
    }

    // 绑定“使用当前时间范围”按钮
    function bindUseTimeRange() {
        const btn = document.getElementById('use_time_range_btn');
        if (!btn) return;
        btn.addEventListener('click', () => {
            const startYear = document.getElementById('start_year')?.value;
            const startMonth = document.getElementById('start_month')?.value;
            const startDay = document.getElementById('start_day')?.value;
            const endYear = document.getElementById('end_year')?.value;
            const endMonth = document.getElementById('end_month')?.value;
            const endDay = document.getElementById('end_day')?.value;
            if (startYear && startMonth && startDay) {
                document.getElementById('group_start_date').value = `${startYear}-${startMonth.padStart(2,'0')}-${startDay.padStart(2,'0')}`;
            }
            if (endYear && endMonth && endDay) {
                document.getElementById('group_end_date').value = `${endYear}-${endMonth.padStart(2,'0')}-${endDay.padStart(2,'0')}`;
            }
        });
    }

    // 监听 IC 模块的选项卡切换，自动清空结果
    function bindICModuleEvents() {
        document.addEventListener('shown.bs.tab', function(event) {
            const target = event.target;
            if (target.closest('#icTab') || target.closest('.factor-tabs-container')) {
                clearResults();
            }
        });
    }

    // 初始化
    document.addEventListener('DOMContentLoaded', () => {
        bindUseTimeRange();
        bindICModuleEvents();
        const runBtn = document.getElementById('run_group_test_btn');
        if (runBtn) runBtn.addEventListener('click', runGroupTest);
    });
})();