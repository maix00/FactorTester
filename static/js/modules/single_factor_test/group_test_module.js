/**
 * 分组测试模块独立脚本
 */
(function() {
    // 时区：后端返回 UTC epoch，useUTC=false 按浏览器本地时区显示
    if (typeof Highcharts !== 'undefined') {
        Highcharts.setOptions({ global: { useUTC: false } });
    }

    // ---------- 显示日期修正提示 ----------
    function showDateHint(input, message) {
        var container = input.closest('div');
        if (!container) return;
        var hint = container.querySelector('.date-hint');
        if (!hint) {
            hint = document.createElement('span');
            hint.className = 'date-hint';
            hint.style.cssText = 'font-size:12px;color:#28a745;margin-left:8px;font-weight:500;';
            container.appendChild(hint);
        }
        hint.textContent = message;
        setTimeout(function() { hint.remove(); }, 3000);
    }

    // ---------- 日期输入框验证（blur 时自动修正超出范围的日期） ----------
    function bindDateValidation() {
        ['start', 'end'].forEach(function(prefix) {
            var yearEl  = document.getElementById('group_' + prefix + '_year');
            var monthEl = document.getElementById('group_' + prefix + '_month');
            var dayEl   = document.getElementById('group_' + prefix + '_day');
            if (!yearEl || !monthEl || !dayEl) return;

            [yearEl, monthEl, dayEl].forEach(function(el) {
                // input：只允许数字
                el.addEventListener('input', function() {
                    if (!/^\d*$/.test(this.value)) this.value = this.value.replace(/\D/g, '');
                });

                // blur：修正月份范围，再修正日期范围（同时间模块逻辑）
                el.addEventListener('blur', function() {
                    var y = parseInt(yearEl.value, 10);
                    var m = parseInt(monthEl.value, 10);
                    var d = parseInt(dayEl.value, 10);
                    var DU = window.DateUtils;
                    var p = function(n) { return DU ? DU.pad(n) : (n < 10 ? '0'+n : ''+n); };

                    // 修正年份
                    if (!isNaN(y)) {
                        if (y < 1900) { y = 1900; yearEl.value = '1900'; }
                        else if (y > 2100) { y = 2100; yearEl.value = '2100'; }
                    }

                    // 修正月份 1-12
                    if (!isNaN(m)) {
                        if (m < 1)  m = 1;
                        if (m > 12) m = 12;
                        monthEl.value = p(m);
                    }

                    // 修正日期 1-maxDay
                    if (!isNaN(y) && !isNaN(m) && !isNaN(d)) {
                        var maxDay = DU ? DU.getMaxDay(y, m) : new Date(y, m, 0).getDate();
                        if (d < 1)      d = 1;
                        if (d > maxDay) d = maxDay;
                        dayEl.value = p(d);
                    }
                });
            });
        });
    }

    // ---------- 组合年月日为日期字符串（自动修正超出月末的日期） ----------
    function buildValidDate(year, month, day) {
        var y = parseInt(year, 10);
        var m = parseInt(month, 10);
        var d = parseInt(day, 10);
        if (!y || !m || !d) return null;
        var maxDay = window.DateUtils ? window.DateUtils.getMaxDay(y, m) : new Date(y, m, 0).getDate();
        var clampedDay = Math.min(d, maxDay);
        return y + '-' + (m < 10 ? '0' + m : m) + '-' + (clampedDay < 10 ? '0' + clampedDay : clampedDay);
    }

    // ---------- 获取当前上下文（从 group test 自己的两级选项卡） ----------
    function getCurrentContext() {
        // 优先从 group test 自己的选项卡获取
        var activeGroupSubTab = document.querySelector('#groupTab .nav-link.active');
        if (activeGroupSubTab) {
            var panelId = activeGroupSubTab.getAttribute('data-bs-target');
            if (panelId) {
                var match = panelId.match(/group-panel-(\d+)/);
                if (match) {
                    var subId = match[1];
                    var panel = document.querySelector(panelId);
                    if (panel) {
                        var activeFactorTab = panel.querySelector('.factor-tabs-container .nav-link.active');
                        if (activeFactorTab) {
                            var factorName = activeFactorTab.textContent.trim();
                            var factorInfo = window.factorList ? window.factorList.find(function(f) { return f.name === factorName || f.alias === factorName; }) : null;
                            if (factorInfo) {
                                return { submission_id: subId, factor_alias: factorInfo.alias };
                            }
                        }
                    }
                }
            }
        }
        // 回退到 IC 测试的当前选项卡
        var activeIcTab = document.querySelector('#icTab .nav-link.active');
        if (!activeIcTab) return null;
        var icPanelId = activeIcTab.getAttribute('data-bs-target');
        if (!icPanelId) return null;
        var icMatch = icPanelId.match(/ic-panel-(\d+)/);
        if (!icMatch) return null;
        var icSubId = icMatch[1];
        var icPanel = document.querySelector(icPanelId);
        if (!icPanel) return null;
        var activeICFactorTab = icPanel.querySelector('.factor-tabs-container .nav-link.active');
        if (!activeICFactorTab) return null;
        var icFactorName = activeICFactorTab.textContent.trim();
        var icFactorInfo = window.factorList ? window.factorList.find(function(f) { return f.name === icFactorName || f.alias === icFactorName; }) : null;
        if (!icFactorInfo) return null;
        return { submission_id: icSubId, factor_alias: icFactorInfo.alias };
    }

    // ---------- 多周期收益率频率复选框 ----------
    var RETURN_FREQ_OPTIONS = ['1d', '2d', '3d', '5d', '10d', '20d'];
    function renderReturnFreqCheckboxes() {
        var container = document.getElementById('return_freqs_checkboxes');
        if (!container) return;
        var html = '';
        RETURN_FREQ_OPTIONS.forEach(function(rf) {
            html += '<label style="display:flex;align-items:center;gap:3px;margin-bottom:0;cursor:pointer;font-weight:normal;font-size:12px;white-space:nowrap;">' +
                '<input type="checkbox" class="return-freq-cb" value="' + rf + '"> ' + rf +
                '</label>';
        });
        container.innerHTML = html;
    }

    function getSelectedReturnFreqs() {
        var cbs = document.querySelectorAll('#return_freqs_checkboxes .return-freq-cb:checked');
        var freqs = [];
        cbs.forEach(function(cb) { freqs.push(cb.value); });
        return freqs;
    }

    /** 渲染多周期对比结果表格 */
    function renderMultiHorizonTable(results, n_groups) {
        var container = document.getElementById('multi_horizon_container');
        if (!container) return;
        if (!results || !results.length) {
            container.style.display = 'none';
            return;
        }
        container.style.display = 'block';

        // 收集所有指标名
        var allMetricNames = [];
        results.forEach(function(r) {
            if (r.ls_metrics) {
                Object.keys(r.ls_metrics).forEach(function(k) {
                    if (allMetricNames.indexOf(k) < 0) allMetricNames.push(k);
                });
            }
        });

        var metricNamesCN = {
            'Total Return': '总收益率', 'Annual Return': '年化收益率', 'Volatility': '年化波动率',
            'Sharpe Ratio': '夏普比率', 'Max Drawdown': '最大回撤', 'Calmar Ratio': 'Calmar比率',
            'Win Rate': '胜率', 'Mean Return': '均值收益率', 'Skewness': '偏度', 'Kurtosis': '峰度',
            'Avg Turnover': '平均换手率'
        };

        // 表头：指标名 | 频率1 | 频率2 | ...
        var headHtml = '<tr><th>指标 (LS)</th>';
        results.forEach(function(r) {
            headHtml += '<th>' + (r.return_freq || '?') + '</th>';
        });
        headHtml += '</tr>';
        document.getElementById('multi_horizon_head').innerHTML = headHtml;

        // 表体：每行一个指标
        var bodyHtml = '';
        allMetricNames.forEach(function(name) {
            var cnName = metricNamesCN[name] || name;
            bodyHtml += '<tr><td style="font-weight:600;">' + cnName + '</td>';
            results.forEach(function(r) {
                var val = (r.ls_metrics && r.ls_metrics[name] !== undefined) ? r.ls_metrics[name] : null;
                var display;
                if (val === null || val === undefined) {
                    display = '—';
                } else if (name === 'Avg Turnover' || name === 'Avg Turnover Accel' || name === 'Up Ratio') {
                    display = (val * 100).toFixed(1) + '%';
                } else if (name === 'Avg Position Changes') {
                    display = val.toFixed(1);
                } else if (name.includes('Rate') || name.includes('Return') || name.includes('Drawdown')) {
                    display = val.toFixed(2) + '%';
                } else if (name.includes('Ratio') || name === 'Skewness' || name === 'Kurtosis') {
                    display = val.toFixed(4);
                } else {
                    display = val.toFixed(4);
                }
                bodyHtml += '<td>' + display + '</td>';
            });
            bodyHtml += '</tr>';
        });
        document.getElementById('multi_horizon_body').innerHTML = bodyHtml;
    }

    // ---------- 清空测试结果 ----------
    function clearResults() {
        var chartContainer = document.getElementById('group_chart_container');
        var metricsContainer = document.getElementById('group_metrics_container');
        var multiHorizonContainer = document.getElementById('multi_horizon_container');
        if (chartContainer) chartContainer.style.display = 'none';
        if (metricsContainer) metricsContainer.style.display = 'none';
        if (multiHorizonContainer) multiHorizonContainer.style.display = 'none';
        closeSnapshotDrawer();
        var status = document.getElementById('group_test_status');
        if (status) status.innerHTML = '';
    }

    // ---------- 绘制分组累计收益曲线 ----------
    var _groupChart = null;  // 当前图表引用

    function drawGroupChart(groups) {
        var container = document.getElementById('group_chart_container');
        if (!container || !groups || groups.length === 0) {
            if (container) container.style.display = 'none';
            return;
        }
        container.style.display = 'block';
        
        var series = groups.map(function(group) {
            var opts = {
                name: group.name,
                type: 'line',
                data: group.cumulative_returns
                    .map(function(val, idx) { return val !== null ? [group.timestamps[idx], val] : null; })
                    .filter(function(pt) { return pt !== null; }),
                tooltip: { valueDecimals: 4 }
            };
            if (group.is_ls) {
                opts.color = '#000';
                opts.dashStyle = 'Dash';
                opts.lineWidth = 2;
            }
            return opts;
        });
        
        // 判断是否为日内频率：相邻 timestamps 差值 < 1天
        var isIntraday = false;
        if (groups.length > 0 && groups[0].timestamps && groups[0].timestamps.length >= 2) {
            var ts = groups[0].timestamps;
            isIntraday = (ts[1] - ts[0]) < 86400000; // < 1天
        }

        _groupChart = Highcharts.stockChart(container, {
            chart: { 
                zoomType: 'x',
                events: {
                    click: function(e) {
                        // 点击图表获取最近数据点的分组快照
                        var xVal = e.xAxis[0].value;
                        fetchGroupSnapshot(xVal);
                    }
                }
            },
            title: { text: '分组累计收益（初始净值 = 1）' },
            xAxis: { type: 'datetime' },
            yAxis: { title: { text: '净值' }, crosshair: true },
            plotOptions: {
                series: {
                    cursor: 'pointer',
                    point: {
                        events: {
                            click: function() {
                                fetchGroupSnapshot(this.x);
                            }
                        }
                    }
                }
            },
            tooltip: {
                shared: true,
                valueDecimals: 4,
                useHTML: true,
                formatter: function () {
                    var d = new Date(this.x);
                    var dateStr = isIntraday
                        ? d.getFullYear() + '-' +
                          String(d.getMonth() + 1).padStart(2, '0') + '-' +
                          String(d.getDate()).padStart(2, '0') + ' ' +
                          String(d.getHours()).padStart(2, '0') + ':' +
                          String(d.getMinutes()).padStart(2, '0')
                        : d.getFullYear() + '-' +
                          String(d.getMonth() + 1).padStart(2, '0') + '-' +
                          String(d.getDate()).padStart(2, '0');
                    var s = '<b>' + dateStr + '</b>';
                    this.points.forEach(function (p) {
                        var decimals = p.series.tooltipOptions.valueDecimals;
                        if (typeof decimals !== 'number') decimals = 4;
                        var val = typeof p.y === 'number' ? p.y.toFixed(decimals) : p.y;
                        s += '<br/>' + p.series.name + ': ' + val;
                    });
                    return s;
                }
            },
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

    // ---------- 快照导航状态 ----------
    var _snapshotTimestamps = [];  // 所有可用时间点（epoch ms）
    var _snapshotCurrentMs = null; // 当前显示的时间点

    // ---------- 获取并展示分组快照 ----------
    function fetchGroupSnapshot(timestampMs) {
        var context = getCurrentContext();
        if (!context) return;

        timestampMs = Math.round(timestampMs);
        _snapshotCurrentMs = timestampMs;

        // 加载中：禁用导航按钮并显示加载提示
        var prevBtn = document.getElementById('snapshot-prev-btn');
        var nextBtn = document.getElementById('snapshot-next-btn');
        if (prevBtn) { prevBtn.disabled = true; prevBtn.textContent = '⏳ 加载中...'; prevBtn.style.opacity = '0.6'; }
        if (nextBtn) { nextBtn.disabled = true; nextBtn.textContent = '⏳ 加载中...'; nextBtn.style.opacity = '0.6'; }

        fetch('/get_group_snapshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                submission_id: context.submission_id,
                timestamp_ms: timestampMs
            })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (!data.success) {
                document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — 错误';
                document.getElementById('snapshot_head').innerHTML = '';
                document.getElementById('snapshot_body').innerHTML = '<tr><td colspan="10" style="color:#d40000;">' + data.error + '</td></tr>';
                document.getElementById('snapshot_flow_stats').innerHTML = '';
                _updateSnapshotNavButtons(null);
                openSnapshotDrawer();
                return;
            }
            _snapshotTimestamps = data.all_timestamps_ms || [];
            // 使用后端返回的精确时间戳（closest_ms），而非前端不精确的传入值
            _snapshotCurrentMs = data.timestamp_ms;
            renderGroupSnapshot(data, data.timestamp_ms);
            _updateSnapshotNavButtons(data);
            openSnapshotDrawer();
        })
        .catch(function(err) {
            document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — 错误';
            document.getElementById('snapshot_head').innerHTML = '';
            document.getElementById('snapshot_body').innerHTML = '<tr><td colspan="10" style="color:#d40000;">请求失败: ' + err.message + '</td></tr>';
            document.getElementById('snapshot_flow_stats').innerHTML = '';
            _updateSnapshotNavButtons(null);
            openSnapshotDrawer();
        });
    }

    /** 更新前/后导航按钮状态 */
    function _updateSnapshotNavButtons(data) {
        var prevBtn = document.getElementById('snapshot-prev-btn');
        var nextBtn = document.getElementById('snapshot-next-btn');
        if (!prevBtn || !nextBtn) return;

        // 恢复按钮文字（可能被加载状态覆盖）
        prevBtn.textContent = '◀ 前一个';
        nextBtn.textContent = '后一个 ▶';

        if (!data) {
            prevBtn.disabled = true;
            nextBtn.disabled = true;
            prevBtn.style.opacity = '0.4';
            nextBtn.style.opacity = '0.4';
            return;
        }

        prevBtn.disabled = !data.has_prev;
        nextBtn.disabled = !data.has_next;
        prevBtn.style.opacity = data.has_prev ? '1' : '0.4';
        nextBtn.style.opacity = data.has_next ? '1' : '0.4';
    }

    /** 导航到上一个/下一个时点 */
    function navigateSnapshot(direction) {
        if (!_snapshotTimestamps.length) return;
        var idx = _snapshotTimestamps.indexOf(_snapshotCurrentMs);
        if (idx < 0) return;
        var newIdx = idx + (direction === 'next' ? 1 : -1);
        if (newIdx < 0 || newIdx >= _snapshotTimestamps.length) return;
        fetchGroupSnapshot(_snapshotTimestamps[newIdx]);
    }

    function openSnapshotDrawer() {
        var overlay = document.getElementById('group-snapshot-drawer');
        if (overlay) overlay.classList.add('open');
    }

    function closeSnapshotDrawer() {
        var overlay = document.getElementById('group-snapshot-drawer');
        if (overlay) overlay.classList.remove('open');
    }

    /** 绑定快照抽屉事件（关闭按钮 + 遮罩点击 + 前/后导航） */
    function bindSnapshotDrawerEvents() {
        var overlay = document.getElementById('group-snapshot-drawer');
        var closeBtn = document.getElementById('group-snapshot-drawer-close');
        var prevBtn = document.getElementById('snapshot-prev-btn');
        var nextBtn = document.getElementById('snapshot-next-btn');
        if (closeBtn) closeBtn.addEventListener('click', closeSnapshotDrawer);
        if (prevBtn) prevBtn.addEventListener('click', function() { navigateSnapshot('prev'); });
        if (nextBtn) nextBtn.addEventListener('click', function() { navigateSnapshot('next'); });
        if (overlay) overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeSnapshotDrawer();
        });
    }

    /** 渲染分组快照抽屉内容 */
    function renderGroupSnapshot(data, timestampMs) {
        // 标题：显示时刻
        var d = new Date(timestampMs);
        var timeStr = d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0') + ' ' +
            String(d.getHours()).padStart(2, '0') + ':' +
            String(d.getMinutes()).padStart(2, '0') + ':' +
            String(d.getSeconds()).padStart(2, '0');
        document.getElementById('snapshot_title').innerHTML = '📋 分组持仓快照 — ' + timeStr;

        var groups = data.groups || [];

        // 表头：每组一列（不含 LS）
        var headHtml = '<tr><th></th>';
        groups.forEach(function(g) {
            headHtml += '<th>' + g.name + ' <span style="font-weight:normal;color:#888;">(' + g.count + '品种)</span></th>';
        });
        headHtml += '</tr>';
        document.getElementById('snapshot_head').innerHTML = headHtml;

        // 出入标记最多的行数
        var maxRows = Math.max.apply(null, groups.map(function(g) {
            return Math.max(g.products_in.length, g.products_out.length, g.products.length);
        }));

        var bodyHtml = '';
        for (var i = 0; i < maxRows; i++) {
            bodyHtml += '<tr>';
            bodyHtml += '<td style="color:#888;font-size:11px;">' + (i === 0 ? '持仓' : '') + '</td>';
            groups.forEach(function(g) {
                var p = i < g.products.length ? g.products[i] : '';
                bodyHtml += '<td>' + p + '</td>';
            });
            bodyHtml += '</tr>';
        }

        // 分隔行
        bodyHtml += '<tr style="border-top:2px solid #e5e7eb;"><td colspan="' + (groups.length + 1) + '" style="font-weight:600;color:#28a745;padding-top:8px;">📥 新进（相对于上一时点）</td></tr>';
        var maxIn = Math.max.apply(null, groups.map(function(g) { return g.products_in.length; }));
        for (var j = 0; j < Math.max(maxIn, 1); j++) {
            bodyHtml += '<tr>';
            bodyHtml += '<td style="color:#888;font-size:11px;"></td>';
            groups.forEach(function(g) {
                var p = j < g.products_in.length ? g.products_in[j] : '';
                bodyHtml += '<td style="color:#28a745;">' + p + '</td>';
            });
            bodyHtml += '</tr>';
        }

        // 退出行
        bodyHtml += '<tr style="border-top:2px solid #e5e7eb;"><td colspan="' + (groups.length + 1) + '" style="font-weight:600;color:#d40000;padding-top:8px;">📤 退出（相对于上一时点）</td></tr>';
        var maxOut = Math.max.apply(null, groups.map(function(g) { return g.products_out.length; }));
        for (var k = 0; k < Math.max(maxOut, 1); k++) {
            bodyHtml += '<tr>';
            bodyHtml += '<td style="color:#888;font-size:11px;"></td>';
            groups.forEach(function(g) {
                var p = k < g.products_out.length ? g.products_out[k] : '';
                bodyHtml += '<td style="color:#d40000;">' + p + '</td>';
            });
            bodyHtml += '</tr>';
        }

        document.getElementById('snapshot_body').innerHTML = bodyHtml;

        // 流动统计
        var totalChanged = 0, totalCount = 0;
        groups.forEach(function(g) {
            totalChanged += g.products_in.length + g.products_out.length;
            totalCount += g.count;
        });
        var avgTurnover = totalCount > 0 ? (totalChanged / (2.0 * totalCount) * 100).toFixed(1) : '0.0';

        var statsHtml = '<b>总体流动统计：</b>';
        statsHtml += '全组换手率 ≈ ' + avgTurnover + '% &nbsp;|&nbsp;';
        statsHtml += '总进出品种数 = ' + totalChanged;
        if (!data.has_prev) {
            statsHtml += ' &nbsp;<span style="color:#888;">（无上一时点数据，无法计算进出）</span>';
        }
        document.getElementById('snapshot_flow_stats').innerHTML = statsHtml;
    }

    // ---------- 渲染统计指标表格 ----------
    function renderMetricsTable(metrics) {
        var container = document.getElementById('group_metrics_container');
        if (!container || !metrics || Object.keys(metrics).length === 0) {
            if (container) container.style.display = 'none';
            return;
        }
        container.style.display = 'block';
        
        var firstGroup = Object.values(metrics)[0];
        var metricNames = Object.keys(firstGroup);
        var metricNamesCN = {
            'Total Return': '总收益率', 'Annual Return': '年化收益率', 'Volatility': '年化波动率',
            'Sharpe Ratio': '夏普比率', 'Max Drawdown': '最大回撤', 'Calmar Ratio': 'Calmar比率',
            'Win Rate': '胜率', 'Mean Return': '均值收益率', 'Skewness': '偏度', 'Kurtosis': '峰度',
            'Avg Turnover': '平均换手率'
        };
        var metricDescs = {
            'Total Return': '整个回测期间的累计净收益率',
            'Annual Return': '年化收益率，基于几何平均折算',
            'Volatility': '收益率的年化标准差',
            'Sharpe Ratio': '夏普比率：衡量单位风险的超额回报',
            'Max Drawdown': '最大回撤：净值从峰值到谷底的最大跌幅',
            'Calmar Ratio': 'Calmar比率：年化收益率与最大回撤的比值',
            'Win Rate': '胜率：正收益周期占总周期的比例',
            'Mean Return': '单期收益率的算术平均值',
            'Skewness': '偏度：收益率分布的偏斜程度',
            'Kurtosis': '峰度：收益率分布的尾部厚度',
            'Avg Turnover': '平均换手率：相邻两期持仓变动的比例',
            'Avg Turnover Accel': '成交加速度：短期成交加速相对长期的变化',
            'Up Ratio': '上涨占比：上涨波幅相对总波幅的比例',
            'Avg Position Changes': '平均持仓变化数：平均每期新增或退出的品种数',
            'Avg Turnover Accel': '成交加速度：衡量交易活跃度的变化趋势',
            'Up Ratio': '上涨占比：累计上涨幅度占累计总波动幅度的比例',
            'Avg Position Changes': '平均持仓变化数：单期平均新增或退出的品种数',
        };
        var metricMathExprs = {
            'Total Return': '$$R_{\\text{total}} = \\prod_t (1+r_t) - 1$$',
            'Annual Return': '$$R_{\\text{ann}} = (1+R_{\\text{total}})^{252/n} - 1$$',
            'Volatility': '$$\\sigma_{\\text{ann}} = \\sigma_{\\text{daily}} \\cdot \\sqrt{252}$$',
            'Sharpe Ratio': '$$\\text{Sharpe} = \\frac{R_{\\text{ann}}}{\\sigma_{\\text{ann}}}$$',
            'Max Drawdown': '$$\\text{MDD} = \\max_t \\left( \\frac{\\text{Peak}_t - \\text{NAV}_t}{\\text{Peak}_t} \\right)$$',
            'Calmar Ratio': '$$\\text{Calmar} = \\frac{R_{\\text{ann}}}{|\\text{MDD}|}$$',
            'Win Rate': '$$\\text{WinRate} = \\frac{N_{\\text{positive}}}{N_{\\text{total}}}$$',
            'Mean Return': '$$\\bar{r} = \\frac{1}{n}\\sum_{t=1}^n r_t$$',
            'Skewness': '$$S = \\frac{1}{n}\\sum_{t=1}^n \\left(\\frac{r_t - \\bar{r}}{\\sigma}\\right)^3$$',
            'Kurtosis': '$$K = \\frac{1}{n}\\sum_{t=1}^n \\left(\\frac{r_t - \\bar{r}}{\\sigma}\\right)^4 - 3$$',
            'Avg Turnover': '$$\\text{Turnover} = \\frac{|\\text{持仓变动}|}{\\text{平均持仓数}}$$',
            'Avg Turnover Accel': '$$\\text{Accel} = \\frac{\\text{MA}(\\text{TO}, N_s)}{\\text{MA}(\\text{TO}, N_l)} - 1$$',
            'Up Ratio': '$$\\text{UpRatio} = \\frac{\\sum \\max(r_i, 0)}{\\sum |r_i|}$$',
            'Avg Position Changes': '$$\\bar{C} = \\frac{1}{n}\\sum_{t=1}^n (|\\text{new}_t| + |\\text{exit}_t|)$$',
        };

        // 收集分组标签
        var groupLabels = [];
        for (var groupIdx in metrics) {
            if (!metrics.hasOwnProperty(groupIdx)) continue;
            groupLabels.push(groupIdx);
        }
        
        // 转置：行 = 指标名，列 = 分组
        // 表头：第一列「指标」，后面每个分组一列
        var theadHtml = '<tr><th>指标</th>';
        groupLabels.forEach(function(g) {
            var isLS = (g === 'LS');
            theadHtml += '<th' + (isLS ? ' style="background:#f0f0f0;"' : '') + '>' + (isLS ? 'Long-Short' : ('第' + (parseInt(g)+1) + '组')) + '</th>';
        });
        theadHtml += '</tr>';
        document.getElementById('metrics_head').innerHTML = theadHtml;
        
        // 表体：每行一个指标
        var tbodyHtml = '';
        metricNames.forEach(function(name) {
            var cnName = metricNamesCN[name] || name;
            tbodyHtml += '<tr><td class="metric-name-cell" data-metric="' + name.replace(/"/g, '&quot;') + '" style="cursor:pointer;position:relative;">' + cnName + '</td>';
            groupLabels.forEach(function(g) {
                var isLS = (g === 'LS');
                var val = metrics[g][name];
                var style = isLS ? ' style="background:#f0f0f0;"' : '';
                if (typeof val === 'number') {
                    if (name === 'Avg Turnover' || name === 'Avg Turnover Accel' || name === 'Up Ratio') {
                        val = (val * 100).toFixed(1) + '%';
                    } else if (name === 'Avg Position Changes') {
                        val = val.toFixed(1);
                    } else if (name.includes('Rate') || name.includes('Return') || name.includes('Drawdown')) {
                        val = val.toFixed(2) + '%';
                    } else if (name.includes('Ratio')) {
                        val = val.toFixed(4);
                    } else {
                        val = val.toFixed(4);
                    }
                } else if (val === null || val === undefined) {
                    val = '—';
                }
                tbodyHtml += '<td' + style + '>' + val + '</td>';
            });
            tbodyHtml += '</tr>';
        });
        document.getElementById('metrics_body').innerHTML = tbodyHtml;

        // 绑定指标名 hover 弹出描述和数学公式
        bindMetricHoverPopup(metricNamesCN, metricDescs, metricMathExprs);
    }

    /** 为指标名列绑定 hover 浮窗 */
    function bindMetricHoverPopup(metricNamesCN, metricDescs, metricMathExprs) {
        // 创建全局浮窗元素（只创建一次）
        var popup = document.getElementById('metric-hover-popup');
        if (!popup) {
            popup = document.createElement('div');
            popup.id = 'metric-hover-popup';
            popup.style.cssText = 'display:none;position:fixed;z-index:9999;background:#fff;border:1px solid #d0d5dd;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,0.18);padding:18px 20px;max-width:420px;min-width:280px;pointer-events:none;';
            document.body.appendChild(popup);
        }

        var cells = document.querySelectorAll('#metrics_body .metric-name-cell');
        cells.forEach(function(cell) {
            cell.addEventListener('mouseenter', function(e) {
                var metricName = this.getAttribute('data-metric');
                var cnName = metricNamesCN[metricName] || metricName;
                var desc = metricDescs[metricName] || '';
                var mathExpr = metricMathExprs[metricName] || '';

                var html = '<div style="font-size:15px;font-weight:700;color:#0f4c81;margin-bottom:10px;padding-bottom:8px;border-bottom:2px solid #e5e7eb;">' + cnName + '</div>';
                if (mathExpr) {
                    html += '<div style="font-size:18px;text-align:center;margin:10px 0;padding:8px;background:#f8fafc;border-radius:6px;">' + mathExpr + '</div>';
                }
                if (desc) {
                    html += '<div style="font-size:13px;color:#555;line-height:1.7;margin-top:8px;">' + desc + '</div>';
                }

                popup.innerHTML = html;
                popup.style.display = 'block';

                // 定位浮窗：在单元格右侧
                var rect = this.getBoundingClientRect();
                var left = rect.right + 12;
                var top = rect.top - 10;
                // 防止溢出屏幕右边
                if (left + 420 > window.innerWidth) {
                    left = rect.left - 432;
                }
                // 防止溢出屏幕底部
                var popupHeight = popup.offsetHeight || 200;
                if (top + popupHeight > window.innerHeight) {
                    top = window.innerHeight - popupHeight - 10;
                }
                if (top < 10) top = 10;
                popup.style.left = left + 'px';
                popup.style.top = top + 'px';

                // 触发 MathJax 渲染
                if (window.MathJax && window.MathJax.typesetPromise) {
                    MathJax.typesetPromise([popup])
                        .then(function() {
                            if (window.fitMathJaxToContainer) {
                                window.fitMathJaxToContainer(popup);
                            }
                        })
                        .catch(function(err) { console.warn('MathJax render error:', err); });
                }
            });

            cell.addEventListener('mouseleave', function() {
                popup.style.display = 'none';
                popup.innerHTML = '';
            });
        });
    }

    // ---------- 运行分组测试 ----------
    function runGroupTest() {
        var context = getCurrentContext();
        if (!context) {
            alert('请先在 IC 测试模块中运行 IC 测试，并点击某个因子的选项卡');
            return;
        }
        var currentSubmissionId = context.submission_id;
        var currentFactorAlias = context.factor_alias;
        
        var n_groups = parseInt(document.getElementById('group_count').value, 10);

        // 读取费率模式
        var feeMode = 'none';
        var feeModeEl = document.querySelector('input[name="fee_mode"]:checked');
        if (feeModeEl) feeMode = feeModeEl.value;

        var fee = 0.0;
        var fee_map = {};
        var use_closetoday = _useCloseToday;

        if (feeMode === 'uniform') {
            fee = parseFloat(document.getElementById('fee_rate').value) || 0.0;
        } else if (feeMode === 'per_product') {
            fee_map = buildFeeMap();
            if (!Object.keys(fee_map).length) {
                alert('按品种费率模式下请先点击"获取费率"加载品种费率数据。');
                return;
            }
        }
        
        // 优先用本模块的分离输入框（年/月/日）
        var sy = document.getElementById('group_start_year').value;
        var sm = document.getElementById('group_start_month').value;
        var sd = document.getElementById('group_start_day').value;
        var ey = document.getElementById('group_end_year').value;
        var em = document.getElementById('group_end_month').value;
        var ed = document.getElementById('group_end_day').value;
        
        var start_date = (sy && sm && sd) ? buildValidDate(sy, sm, sd) : null;
        var end_date = (ey && em && ed) ? buildValidDate(ey, em, ed) : null;
        
        // fallback：从时间范围模块读取
        if (!start_date) {
            var timeSy = document.getElementById('start_year') ? document.getElementById('start_year').value : null;
            var timeSm = document.getElementById('start_month') ? document.getElementById('start_month').value : null;
            var timeSd = document.getElementById('start_day') ? document.getElementById('start_day').value : null;
            if (timeSy && timeSm && timeSd) start_date = buildValidDate(timeSy, timeSm, timeSd);
        }
        if (!end_date) {
            var timeEy = document.getElementById('end_year') ? document.getElementById('end_year').value : null;
            var timeEm = document.getElementById('end_month') ? document.getElementById('end_month').value : null;
            var timeEd = document.getElementById('end_day') ? document.getElementById('end_day').value : null;
            if (timeEy && timeEm && timeEd) end_date = buildValidDate(timeEy, timeEm, timeEd);
        }
        
        // 最终 fallback：从 submission 中获取
        if (!start_date || !end_date) {
            var submission = window.submissions ? window.submissions.find(function(s) { return s.id == currentSubmissionId; }) : null;
            if (submission) {
                if (!start_date) start_date = submission.start_date;
                if (!end_date) end_date = submission.end_date;
            }
        }
        
        var statusSpan = document.getElementById('group_test_status');
        
        if (!start_date || !end_date) {
            statusSpan.innerHTML = '✗ 请设置时间范围';
            statusSpan.style.color = '#d40000';
            return;
        }
        
        if (start_date > end_date) {
            statusSpan.innerHTML = '✗ 起始日期不能晚于终止日期';
            statusSpan.style.color = '#d40000';
            return;
        }
        
        // 收集多周期收益率频率
        var return_freqs = getSelectedReturnFreqs();

        statusSpan.innerHTML = '分组测试运行中...';
        statusSpan.style.color = '#0078d4';

        // 隐藏旧结果
        var multiHorizonContainer = document.getElementById('multi_horizon_container');
        if (multiHorizonContainer) multiHorizonContainer.style.display = 'none';

        fetch('/run_group_test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                submission_id: currentSubmissionId,
                factor_alias: currentFactorAlias,
                n_groups: n_groups,
                fee: fee,
                fee_map: fee_map,
                use_closetoday: use_closetoday,
                start_date: start_date,
                end_date: end_date,
                return_freqs: return_freqs.length > 0 ? return_freqs : null
            })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (!data.success) {
                statusSpan.innerHTML = '✗ 分组测试失败: ' + data.error;
                statusSpan.style.color = '#d40000';
                if (data.traceback) {
                    var chartContainer = document.getElementById('group_chart_container');
                    if (chartContainer) {
                        chartContainer.style.display = 'block';
                        chartContainer.innerHTML = '<pre style="background:#fff3f3;border:1px solid #f99;padding:10px;font-size:11px;overflow:auto;white-space:pre-wrap;margin-top:8px;color:#a00;">' + data.traceback.replace(/</g,'&lt;') + '</pre>';
                    }
                }
                return;
            }

            // 多周期对比模式
            if (data.multi_horizon) {
                statusSpan.innerHTML = '✓ 多周期对比完成（' + data.results.length + ' 个频率）';
                statusSpan.style.color = '#28a745';
                // 隐藏单频率图表和指标表
                var chartContainer = document.getElementById('group_chart_container');
                var metricsContainer = document.getElementById('group_metrics_container');
                if (chartContainer) chartContainer.style.display = 'none';
                if (metricsContainer) metricsContainer.style.display = 'none';
                closeSnapshotDrawer();
                // 清空缓存
                _lastGrossData = null;
                _lastMetrics = null;
                // 渲染多周期对比表格
                renderMultiHorizonTable(data.results, data.n_groups);
                return;
            }

            statusSpan.innerHTML = '✓ 分组测试完成';
            statusSpan.style.color = '#28a745';
            // 缓存原始数据，供成本敏感性滑条使用
            _lastGrossData = data.groups;  // 每组含 gross_returns / fee_costs
            _lastMetrics = data.metrics;
            _lastNgroups = data.n_groups;
            _lastTimestamps = data.groups.length > 0 ? data.groups[0].timestamps : [];
            // 初次渲染使用原始数据
            drawGroupChart(data.groups);
            renderMetricsTable(data.metrics);
            // 重置滑条到0
            var slider = document.getElementById('fee_sensitivity_slider');
            if (slider) { slider.value = 0; updateSensitivityLabel(0); }
        })
        .catch(function(err) {
            statusSpan.innerHTML = '请求失败: ' + err.message;
            statusSpan.style.color = '#d40000';
            console.error(err);
        });
    }

    // ---------- 成本敏感性：缓存数据 ----------
    var _lastGrossData = null;   // 上次返回的 groups（含 gross_returns / fee_costs）
    var _lastMetrics = null;
    var _lastTimestamps = [];
    var _lastNgroups = 0;

    /** 更新敏感性滑条标签 */
    function updateSensitivityLabel(val) {
        var lbl = document.getElementById('fee_sensitivity_label');
        if (lbl) lbl.textContent = parseFloat(val).toFixed(3) + '%';
    }

    /** 根据新费率重算累积净值（统一费率模式） */
    function recalcWithFee(newFeePct) {
        if (!_lastGrossData || _lastGrossData.length === 0) return;
        var feeRatio = parseFloat(newFeePct) / 100.0;  // % → 小数
        var halfFee = feeRatio / 2.0;

        var nGroups = _lastNgroups;
        var recalcGroups = [];

        // 前 n_groups 组：做多组
        for (var g = 0; g < nGroups; g++) {
            var src = _lastGrossData[g];
            if (!src || !src.gross_returns) {
                recalcGroups.push(src);
                continue;
            }
            var cumVals = [];
            var wealth = 1.0;
            var gross = src.gross_returns;
            var prevFee = src.fee_costs || [];  // 原始费率成本，供参考
            for (var i = 0; i < gross.length; i++) {
                var gRet = gross[i];
                // 近似：净收益 = (1 - half_fee) * (1 + gross) - 1
                //         ≈ gross - half_fee （费率很小时）
                // 使用更精确的形式（与后台一致）：net = (1-fee)*(1+gross)-1
                var net = (1.0 - feeRatio) * (1.0 + gRet) - 1.0;
                if (isNaN(net) || !isFinite(net)) net = 0.0;
                wealth *= (1.0 + net);
                cumVals.push(roundVal(wealth));
            }
            recalcGroups.push({
                name: src.name,
                timestamps: src.timestamps,
                cumulative_returns: cumVals,
                gross_returns: src.gross_returns,
                fee_costs: src.fee_costs,
                is_ls: false
            });
        }

        // Long-Short 组
        var lsSrc = _lastGrossData[nGroups];
        if (lsSrc && lsSrc.is_ls) {
            var topGross = _lastGrossData[0] ? _lastGrossData[0].gross_returns || [] : [];
            var botGross = _lastGrossData[nGroups - 1] ? _lastGrossData[nGroups - 1].gross_returns || [] : [];
            var longCap = 0.5, shortCap = 0.5, totalCap = 1.0;
            var lsCum = [];
            for (var i = 0; i < Math.min(topGross.length, botGross.length); i++) {
                var longGross = topGross[i];
                var shortGross = -botGross[i];
                var longNet = (1.0 - feeRatio) * (1.0 + longGross) - 1.0;
                var shortNet = (1.0 - feeRatio) * (1.0 + shortGross) - 1.0;
                if (isNaN(longNet) || !isFinite(longNet)) longNet = 0.0;
                if (isNaN(shortNet) || !isFinite(shortNet)) shortNet = 0.0;
                longCap *= (1.0 + longNet);
                shortCap *= (1.0 + shortNet);
                totalCap = longCap + shortCap;
                lsCum.push(roundVal(totalCap));
            }
            recalcGroups.push({
                name: 'Long-Short',
                timestamps: _lastTimestamps,
                cumulative_returns: lsCum,
                is_ls: true
            });
        }

        drawGroupChart(recalcGroups);

        // 重算指标表
        calcAndRenderMetricsFromGroups(recalcGroups, nGroups);
    }

    function roundVal(v) {
        if (isNaN(v) || !isFinite(v)) return null;
        return Math.round(v * 1e8) / 1e8;
    }

    /** 从重算后的 groups 计算各组指标（简化版，只更新费率敏感的指标） */
    function calcAndRenderMetricsFromGroups(recalcGroups, nGroups) {
        if (!_lastMetrics) return;
        // 用重算的累积净值反推每期净收益，再算指标
        var newMetrics = {};
        var t = _lastTimestamps;

        for (var g = 0; g < nGroups; g++) {
            var cumVals = recalcGroups[g].cumulative_returns;
            var returns = [];
            for (var i = 1; i < cumVals.length; i++) {
                returns.push(cumVals[i] / cumVals[i-1] - 1.0);
            }
            newMetrics[String(g)] = calcMetricsFromReturns(returns);
        }

        // LS
        var lsCum = recalcGroups[nGroups] ? recalcGroups[nGroups].cumulative_returns : null;
        if (lsCum) {
            var lsReturns = [];
            for (var i = 1; i < lsCum.length; i++) {
                lsReturns.push(lsCum[i] / lsCum[i-1] - 1.0);
            }
            newMetrics['LS'] = calcMetricsFromReturns(lsReturns);
        }

        // 保留 Avg Turnover（不受费率影响）
        if (_lastMetrics) {
            for (var k in _lastMetrics) {
                if (_lastMetrics.hasOwnProperty(k) && newMetrics[k] && _lastMetrics[k]['Avg Turnover'] !== undefined) {
                    newMetrics[k]['Avg Turnover'] = _lastMetrics[k]['Avg Turnover'];
                }
            }
        }

        renderMetricsTable(newMetrics);
    }

    /** 从收益率序列计算指标 */
    function calcMetricsFromReturns(returns) {
        if (!returns || returns.length === 0) return {};
        var n = returns.length;
        var cum = 1.0;
        var cumMax = 1.0;
        var maxDD = 0.0;
        var winCount = 0;
        var sum = 0.0;
        var sumSq = 0.0;

        for (var i = 0; i < n; i++) {
            var r = returns[i];
            if (isNaN(r) || !isFinite(r)) continue;
            cum *= (1.0 + r);
            if (cum > cumMax) cumMax = cum;
            var dd = (cumMax - cum) / cumMax;
            if (dd > maxDD) maxDD = dd;
            if (r > 0) winCount++;
            sum += r;
            sumSq += r * r;
        }

        var mean = sum / n;
        var variance = (sumSq / n) - (mean * mean);
        var std = Math.sqrt(Math.max(variance, 0));
        var totalRet = (cum - 1.0) * 100;
        var annualRet = (Math.pow(cum, 252 / n) - 1) * 100;
        var vol = std * Math.sqrt(252) * 100;
        var sharpe = std > 0 ? (mean * 252) / (std * Math.sqrt(252)) : 0;
        var calmar = maxDD > 0 ? annualRet / (maxDD * 100) : 0;
        var winRate = (winCount / n) * 100;

        var skew = 0.0, kurt = 0.0;
        if (std > 0) {
            for (var i = 0; i < n; i++) {
                var z = (returns[i] - mean) / std;
                skew += z * z * z;
                kurt += z * z * z * z;
            }
            skew /= n;
            kurt = kurt / n - 3;
        }

        return {
            'Total Return': roundVal(totalRet),
            'Annual Return': roundVal(annualRet),
            'Volatility': roundVal(vol),
            'Sharpe Ratio': roundVal(sharpe),
            'Max Drawdown': roundVal(maxDD * 100),
            'Calmar Ratio': roundVal(calmar),
            'Win Rate': roundVal(winRate),
            'Mean Return': roundVal(mean * 100),
            'Skewness': roundVal(skew),
            'Kurtosis': roundVal(kurt),
        };
    }

    // ---------- 绑定"使用当前时间范围"按钮 ----------
    function bindUseTimeRange() {
        var btn = document.getElementById('use_time_range_btn');
        if (!btn) return;
        btn.addEventListener('click', function() {
            var startYear = document.getElementById('start_year') ? document.getElementById('start_year').value : null;
            var startMonth = document.getElementById('start_month') ? document.getElementById('start_month').value : null;
            var startDay = document.getElementById('start_day') ? document.getElementById('start_day').value : null;
            var endYear = document.getElementById('end_year') ? document.getElementById('end_year').value : null;
            var endMonth = document.getElementById('end_month') ? document.getElementById('end_month').value : null;
            var endDay = document.getElementById('end_day') ? document.getElementById('end_day').value : null;
            
            if (startYear && startMonth && startDay) {
                var ds = buildValidDate(startYear, startMonth, startDay);
                if (ds) {
                    var parts = ds.split('-');
                    document.getElementById('group_start_year').value = parts[0];
                    document.getElementById('group_start_month').value = parseInt(parts[1], 10);
                    document.getElementById('group_start_day').value = parseInt(parts[2], 10);
                }
            }
            if (endYear && endMonth && endDay) {
                var de = buildValidDate(endYear, endMonth, endDay);
                if (de) {
                    var parts = de.split('-');
                    document.getElementById('group_end_year').value = parts[0];
                    document.getElementById('group_end_month').value = parseInt(parts[1], 10);
                    document.getElementById('group_end_day').value = parseInt(parts[2], 10);
                }
            }
        });
    }

    // ---------- 从时间模块同步时间到分组测试时间输入框 ----------
    function syncFromTimeModule() {
        var IDs = [
            ['start_year','group_start_year'], ['start_month','group_start_month'], ['start_day','group_start_day'],
            ['end_year','group_end_year'], ['end_month','group_end_month'], ['end_day','group_end_day']
        ];
        IDs.forEach(function(pair) {
            var src = document.getElementById(pair[0]);
            var dst = document.getElementById(pair[1]);
            if (src && dst && src.value) dst.value = src.value;
        });
    }

    function bindTimeSyncListeners() {
        ['start_year','start_month','start_day','end_year','end_month','end_day'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.addEventListener('change', syncFromTimeModule);
        });
    }

    // ---------- 监听 IC 模块及自身选项卡切换，自动清空结果 ----------
    function bindICModuleEvents() {
        document.addEventListener('shown.bs.tab', function(event) {
            var target = event.target;
            if (target.closest('#icTab') || target.closest('#groupTab') || target.closest('.factor-tabs-container')) {
                clearResults();
            }
        });
    }

    // ---------- 手续费表相关状态与函数 ----------
    var _useCloseToday = false;
    var _feeTableData = [];          // 原始费率数据（从后端获取的，不可变）
    var _feeModifications = {};      // 用户修改：{variety_code: {open_ratio, close_ratio}}

    /** 获取当前费率修改（供单因子设置快照 collectSnapshot 调用） */
    window._getFeeModifications = function() {
        return JSON.parse(JSON.stringify(_feeModifications));
    };

    /** 应用费率修改（供单因子设置快照 applySnapshot 调用） */
    window._applyFeeModifications = function(mods) {
        _feeModifications = {};
        if (mods && typeof mods === 'object') {
            Object.keys(mods).forEach(function(code) {
                _feeModifications[code] = mods[code];
            });
        }
        if (_feeTableData.length) renderFeeTable();
    };

    /** 从 /get_fee_table 拉取今日费率 */
    function fetchFeeTable(forceRefresh) {
        var statusEl = document.getElementById('drawer_fee_fetch_status');
        if (statusEl) { statusEl.textContent = '加载中...'; statusEl.style.color = '#0078d4'; }
        fetch('/get_fee_table', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_refresh: !!forceRefresh })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) {
                if (statusEl) { statusEl.textContent = '获取失败: ' + data.error; statusEl.style.color = '#d40000'; }
                return;
            }
            _feeTableData = data.rows || [];
            _feeModifications = {};  // 新数据覆盖后清空修改
            renderFeeTable();
            updateFeeSummary();
            if (statusEl) { statusEl.textContent = '✓ 已加载 ' + _feeTableData.length + ' 个品种'; statusEl.style.color = '#28a745'; }
        })
        .catch(function(err) {
            if (statusEl) { statusEl.textContent = '请求失败: ' + err.message; statusEl.style.color = '#d40000'; }
        });
    }

    /** 获取某品种的当前显示值（优先使用修改值） */
    function _getEffectiveRow(row) {
        var code = (row.variety_code || '').toLowerCase();
        var mod = _feeModifications[code] || {};
        var openR  = (mod.open_ratio  !== undefined) ? mod.open_ratio  : (parseFloat(row.open_ratio) || 0);
        var closeR = (mod.close_ratio !== undefined) ? mod.close_ratio : (_useCloseToday ? (parseFloat(row.closetoday_ratio) || 0) : (parseFloat(row.close_ratio) || 0));
        return { code: code, openR: openR, closeR: closeR };
    }

    /** 渲染品种费率表（可编辑单元格） */
    function renderFeeTable() {
        var tbody = document.getElementById('fee_table_body');
        if (!tbody) return;
        var closeColEl = document.getElementById('fee_col_close');
        if (closeColEl) closeColEl.textContent = _useCloseToday ? '平今比率' : '平仓比率';
        if (!_feeTableData.length) {
            tbody.innerHTML = '<tr><td colspan="7" style="padding:16px;text-align:center;color:#888;">暂无数据</td></tr>';
            return;
        }
        var html = '';
        _feeTableData.forEach(function(row) {
            var code = (row.variety_code || '');
            var codeLower = code.toLowerCase();
            var eff = _getEffectiveRow(row);
            var total  = (eff.openR + eff.closeR) * 100;
            var openModified  = !!(_feeModifications[codeLower] && _feeModifications[codeLower].open_ratio  !== undefined);
            var closeModified = !!(_feeModifications[codeLower] && _feeModifications[codeLower].close_ratio !== undefined);
            var openClass  = openModified  ? 'fee-cell-modified' : '';
            var closeClass = closeModified ? 'fee-cell-modified' : '';

            html += '<tr>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;font-weight:600;">' + code + '</td>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;">' + (row.variety_name || '') + '</td>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;">' + (row.exchange || '') + '</td>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;">' + (row.multiplier || '') + '</td>';
            html += '<td class="' + openClass + '" contenteditable="true" data-variety="' + codeLower + '" data-field="open_ratio" style="padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;">' + eff.openR.toFixed(6) + '</td>';
            html += '<td class="' + closeClass + '" contenteditable="true" data-variety="' + codeLower + '" data-field="close_ratio" style="padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;">' + eff.closeR.toFixed(6) + '</td>';
            html += '<td style="padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;">';
            html += total > 0 ? total.toFixed(4) + '%' : '—';
            html += '</td>';
            html += '</tr>';
        });
        tbody.innerHTML = html;

        // 绑定可编辑单元格事件
        tbody.querySelectorAll('[contenteditable="true"]').forEach(function(cell) {
            cell.addEventListener('blur', _onFeeCellBlur);
            cell.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') { e.preventDefault(); this.blur(); }
                if (e.key === 'Escape') { this.blur(); }
            });
        });
    }

    /** 可编辑单元格 blur 处理 */
    function _onFeeCellBlur() {
        var variety = this.getAttribute('data-variety');
        var field = this.getAttribute('data-field');
        var rawVal = (this.textContent || '').trim();
        var val = parseFloat(rawVal);
        if (isNaN(val) || val < 0) {
            // 恢复原始值
            var row = _feeTableData.find(function(r) { return (r.variety_code || '').toLowerCase() === variety; });
            if (row) {
                var orig = _getEffectiveRow(row);
                this.textContent = (field === 'open_ratio' ? orig.openR : orig.closeR).toFixed(6);
            }
            return;
        }

        // 对比原始值
        var row = _feeTableData.find(function(r) { return (r.variety_code || '').toLowerCase() === variety; });
        if (!row) return;
        var origVal = field === 'open_ratio'
            ? (parseFloat(row.open_ratio) || 0)
            : (_useCloseToday ? (parseFloat(row.closetoday_ratio) || 0) : (parseFloat(row.close_ratio) || 0));

        if (Math.abs(val - origVal) < 1e-9) {
            // 恢复为原始值，清除修改
            this.textContent = origVal.toFixed(6);
            this.classList.remove('fee-cell-modified');
            if (_feeModifications[variety]) {
                delete _feeModifications[variety][field];
                if (Object.keys(_feeModifications[variety]).length === 0) delete _feeModifications[variety];
            }
        } else {
            // 记录修改
            this.textContent = val.toFixed(6);
            this.classList.add('fee-cell-modified');
            if (!_feeModifications[variety]) _feeModifications[variety] = {};
            _feeModifications[variety][field] = val;
        }
        updateFeeSummary();

        // 刷新该行的双边合计列
        _refreshTotalColumn(variety);
    }

    /** 刷新某品种的双边合计列 */
    function _refreshTotalColumn(variety) {
        var row = _feeTableData.find(function(r) { return (r.variety_code || '').toLowerCase() === variety; });
        if (!row) return;
        var eff = _getEffectiveRow(row);
        var total = (eff.openR + eff.closeR) * 100;
        var cells = document.querySelectorAll('#fee_table_body td[data-variety="' + variety + '"]');
        // 该行最后一个 td 是合计列（没有 contenteditable 属性）
        var allCellsInRow = [];
        var tr = cells.length > 0 ? cells[0].parentElement : null;
        if (tr) {
            var lastTd = tr.querySelector('td:last-child');
            if (lastTd) lastTd.innerHTML = total > 0 ? total.toFixed(4) + '%' : '—';
        }
    }

    /** 更新抽屉外部的费率摘要 */
    function updateFeeSummary() {
        var summaryEl = document.getElementById('group-fee-summary');
        if (!summaryEl) return;
        var total = _feeTableData.length;
        var modifiedCount = Object.keys(_feeModifications).length;
        if (total === 0) {
            summaryEl.textContent = '(暂无数据)';
        } else if (modifiedCount === 0) {
            summaryEl.textContent = '(' + total + '个)';
        } else {
            summaryEl.textContent = '(' + total + '个, ' + modifiedCount + '个已修改)';
            summaryEl.style.color = '#d97706';
        }
    }

    /** 从品种费率表构建 fee_map（合并修改值） */
    function buildFeeMap() {
        var map = {};
        _feeTableData.forEach(function(row) {
            var code = (row.variety_code || '').toLowerCase();
            if (!code) return;
            var mod = _feeModifications[code] || {};
            map[code] = {
                open_ratio:        (mod.open_ratio  !== undefined) ? mod.open_ratio  : (parseFloat(row.open_ratio)        || 0),
                close_ratio:       (mod.close_ratio !== undefined) ? mod.close_ratio : (parseFloat(row.close_ratio)       || 0),
                closetoday_ratio:  parseFloat(row.closetoday_ratio)  || 0,
                open_fixed:        parseFloat(row.open_fixed)        || 0,
                close_fixed:       parseFloat(row.close_fixed)       || 0,
                closetoday_fixed:  parseFloat(row.closetoday_fixed)  || 0,
            };
        });
        return map;
    }

    /** 恢复所有费率为原始值 */
    function resetAllFees() {
        _feeModifications = {};
        renderFeeTable();
        updateFeeSummary();
    }

    /** 更新平今/平昨状态文字与切换按钮文字 */
    function updateClosetodayUI() {
        var stateEl = document.getElementById('closetoday_state_text');
        var ctBtn   = document.getElementById('use_closetoday_btn');
        if (stateEl) {
            stateEl.textContent = _useCloseToday ? '平今仓' : '平昨仓';
            stateEl.style.color = _useCloseToday ? '#d97706' : '#0078d4';
        }
        if (ctBtn) {
            ctBtn.textContent = _useCloseToday ? '切换为平昨仓' : '切换为平今仓';
            ctBtn.classList.toggle('btn-outline-secondary', !_useCloseToday);
            ctBtn.classList.toggle('btn-outline-warning', _useCloseToday);
        }
    }

    // ---------- 费率抽屉开关 ----------
    function openFeeDrawer() {
        var overlay = document.getElementById('group-fee-drawer');
        var badge = document.getElementById('user-badge');
        if (overlay) overlay.classList.add('open');
        if (badge) badge.style.display = 'none';
    }
    function closeFeeDrawer() {
        var overlay = document.getElementById('group-fee-drawer');
        var badge = document.getElementById('user-badge');
        if (overlay) overlay.classList.remove('open');
        if (badge) badge.style.display = '';
    }

    /** 绑定费率相关按钮事件 */
    function bindFeeControls() {
        // 费率模式单选按钮
        document.querySelectorAll('input[name="fee_mode"]').forEach(function(radio) {
            radio.addEventListener('change', function() {
                var mode = this.value;
                var uniformWrap     = document.getElementById('fee_uniform_wrap');
                var perProductWrap  = document.getElementById('fee_per_product_wrap');
                if (uniformWrap)    uniformWrap.style.display    = (mode === 'uniform')     ? 'flex' : 'none';
                if (perProductWrap) perProductWrap.style.display  = (mode === 'per_product') ? 'flex' : 'none';
            });
        });

        // 打开费率抽屉
        var trigger = document.getElementById('group-fee-drawer-trigger');
        if (trigger) trigger.addEventListener('click', openFeeDrawer);

        // 关闭费率抽屉
        var closeBtn = document.getElementById('group-fee-drawer-close');
        if (closeBtn) closeBtn.addEventListener('click', closeFeeDrawer);

        // 点击遮罩层关闭
        var overlay = document.getElementById('group-fee-drawer');
        if (overlay) overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeFeeDrawer();
        });

        // 抽屉内获取费率按钮
        var fetchBtn = document.getElementById('drawer_fetch_fee_btn');
        if (fetchBtn) fetchBtn.addEventListener('click', function() { fetchFeeTable(false); });

        // 抽屉内恢复原始值按钮
        var resetBtn = document.getElementById('drawer_reset_fee_btn');
        if (resetBtn) resetBtn.addEventListener('click', resetAllFees);

        // 平今/平昨切换按钮
        var ctBtn = document.getElementById('use_closetoday_btn');
        if (ctBtn) ctBtn.addEventListener('click', function() {
            _useCloseToday = !_useCloseToday;
            updateClosetodayUI();
            if (_feeTableData.length) renderFeeTable();
        });

        // 成本敏感性滑条（仅统一费率模式有效）
        var _sliderDebounceTimer = null;
        var slider = document.getElementById('fee_sensitivity_slider');
        if (slider) {
            function onSliderInput() {
                var feeModeEl = document.querySelector('input[name="fee_mode"]:checked');
                var mode = feeModeEl ? feeModeEl.value : 'none';
                if (mode !== 'uniform') return;  // 仅在统一费率模式下生效
                var val = parseFloat(slider.value);
                updateSensitivityLabel(val);
                // 防抖：50ms 内的连续滑动只执行最后一次
                if (_sliderDebounceTimer) clearTimeout(_sliderDebounceTimer);
                _sliderDebounceTimer = setTimeout(function() {
                    recalcWithFee(val);
                }, 50);
            }
            slider.addEventListener('input', onSliderInput);
            slider.addEventListener('change', function() {
                if (_sliderDebounceTimer) clearTimeout(_sliderDebounceTimer);
                var feeModeEl = document.querySelector('input[name="fee_mode"]:checked');
                var mode = feeModeEl ? feeModeEl.value : 'none';
                if (mode !== 'uniform') return;
                var val = parseFloat(this.value);
                updateSensitivityLabel(val);
                recalcWithFee(val);
            });
        }
    }

    // ---------- 初始化 ----------
    function init() {
        renderReturnFreqCheckboxes();
        bindDateValidation();
        bindUseTimeRange();
        bindICModuleEvents();
        bindTimeSyncListeners();
        bindFeeControls();
        bindSnapshotDrawerEvents();
        syncFromTimeModule();
        document.addEventListener('timeRangeDefaultLoaded', syncFromTimeModule, { once: true });
        setTimeout(syncFromTimeModule, 0);
        var runBtn = document.getElementById('run_group_test_btn');
        if (runBtn) runBtn.addEventListener('click', runGroupTest);

        // 如果已有 submissions，渲染两级选项卡
        if (window.submissions && window.submissions.length > 0) {
            window.renderGroupTabs(window.submissions);
        }
    }

    // 暴露给外部调用：渲染分组测试的两级选项卡（submission → factor）
    window.renderGroupTabs = function(submissions) {
        var container = document.getElementById('group-tab-container');
        var runBtn = document.getElementById('run_group_test_btn');
        if (!container) return;
        if (!submissions || submissions.length === 0) {
            container.innerHTML = '<div style="color:#888; padding:8px; border:1px dashed #ccc; border-radius:4px; font-size:13px;">暂无提交记录，请先在产品类别筛选模块提交产品。</div>';
            if (runBtn) runBtn.style.display = 'none';
            return;
        }
        if (runBtn) runBtn.style.display = '';

        var factorList = window.factorList || [];
        var tabsHtml = '<ul class="nav nav-tabs" id="groupTab" role="tablist">';
        var panelsHtml = '<div class="tab-content" id="groupTabContent">';
        submissions.forEach(function(sub, idx) {
            var activeClass = idx === 0 ? 'active' : '';
            var showClass = idx === 0 ? 'show active' : '';
            var tabId = 'group-tab-' + sub.id;
            var panelId = 'group-panel-' + sub.id;
            tabsHtml += '<li class="nav-item"><button class="nav-link ' + activeClass + '" id="' + tabId + '" data-bs-toggle="tab" data-bs-target="#' + panelId + '" type="button" role="tab">' + (sub.label || ('测试器' + (idx+1))) + '</button></li>';

            // 第二级：因子选项卡
            var factorTabsHtml = '';
            var factorPanesHtml = '';
            if (factorList.length > 0) {
                factorTabsHtml = '<ul class="nav nav-tabs factor-tabs-container" style="margin-top:12px;">';
                factorPanesHtml = '<div class="tab-content">';
                factorList.forEach(function(f, fi) {
                    var fActive = fi === 0 ? 'active' : '';
                    var fShow = fi === 0 ? 'show active' : '';
                    var fTabId = 'group-factor-tab-' + sub.id + '-' + fi;
                    var fPaneId = 'group-factor-pane-' + sub.id + '-' + fi;
                    factorTabsHtml += '<li class="nav-item"><button class="nav-link ' + fActive + '" id="' + fTabId + '" data-bs-toggle="tab" data-bs-target="#' + fPaneId + '" type="button" role="tab">' + (f.alias || f.name) + '</button></li>';
                    factorPanesHtml += '<div class="tab-pane fade ' + fShow + '" id="' + fPaneId + '" role="tabpanel">' +
                        '<div style="color:#888;padding:16px;text-align:center;">已选择因子 <b>' + (f.alias || f.name) + '</b>，配置好参数后点击下方"运行分组测试"</div>' +
                        '</div>';
                });
                factorTabsHtml += '</ul>';
                factorPanesHtml += '</div>';
            }

            panelsHtml += '<div class="tab-pane fade ' + showClass + '" id="' + panelId + '" role="tabpanel">' +
                factorTabsHtml + factorPanesHtml +
                '</div>';
        });
        tabsHtml += '</ul>';
        panelsHtml += '</div>';
        container.innerHTML = tabsHtml + panelsHtml;

        // 初始化 Bootstrap 选项卡
        if (typeof bootstrap !== 'undefined') {
            var tabTriggers = document.querySelectorAll('#groupTab button[data-bs-toggle="tab"]');
            tabTriggers.forEach(function(trigger) {
                var tab = new bootstrap.Tab(trigger);
                trigger.addEventListener('click', function(e) { e.preventDefault(); tab.show(); });
            });
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
