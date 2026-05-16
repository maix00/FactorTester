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

    function getCurrentContext() {
        var ctx = window.SingleFactorSubmissionContext;
        var activeFactorBtn = document.querySelector('.group-factor-nav-btn.active');
        if (activeFactorBtn) {
            var submissionId = activeFactorBtn.getAttribute('data-submission-id');
            var factorAlias = activeFactorBtn.getAttribute('data-factor-alias');
            var factorList = Array.isArray(window.factorList) ? window.factorList : [];
            var matchedFactor = factorList.find(function(f) {
                return f.alias === factorAlias || f.name === factorAlias;
            }) || null;
            return {
                submission_id: submissionId,
                submission: ctx ? ctx.findSubmissionById(submissionId) : null,
                factor_alias: factorAlias,
                factor: matchedFactor,
            };
        }
        if (!ctx) return null;
        return ctx.getActiveFactorContext({
            tabSelector: '#groupTab .nav-link.active',
            panelPrefix: 'group-panel',
            factorTabSelector: '.group-factor-nav-btn.active',
        }) || ctx.getActiveFactorContext({
            tabSelector: '#icTab .nav-link.active',
            panelPrefix: 'ic-panel',
        });
    }

    function getActiveGroupSubmissionId() {
        var activeBtn = document.querySelector('.group-submission-nav-btn.active');
        if (activeBtn) return activeBtn.getAttribute('data-submission-id');
        var ctx = window.SingleFactorSubmissionContext;
        var activeTab = document.querySelector('#groupTab .nav-link.active');
        if (!ctx || !activeTab) return null;
        return ctx.getSubmissionIdFromTab(activeTab, 'group-panel');
    }

    function pageHasICModule() {
        return !!document.getElementById('ic_test_module');
    }

    function getMissingGroupContextMessage() {
        if (pageHasICModule()) {
            return '请先选择产品组/测试器和因子；如果因子列表尚未出现，请先在 IC 测试模块运行 IC 测试。';
        }
        return '请先选择测试器和因子';
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
        var MH_METRIC_DIR = {
            'Total Return': 1, 'Annual Return': 1, 'Sharpe Ratio': 1, 'Calmar Ratio': 1,
            'Win Rate': 1, 'Mean Return': 1, 'Skewness': 1,
            'Volatility': -1, 'Max Drawdown': -1, 'Kurtosis': -1,
            'Avg Turnover': -1, 'Avg Turnover Accel': -1, 'Avg Position Changes': -1, 'Up Ratio': 1
        };
        function mhBestColIdx(vals, metricName) {
            var dir = MH_METRIC_DIR[metricName];
            var best = -1, bestVal = null;
            for (var i = 0; i < vals.length; i++) {
                if (vals[i] === null || vals[i] === undefined) continue;
                if (best === -1 || (dir >= 0 ? vals[i] > bestVal : vals[i] < bestVal)) {
                    best = i; bestVal = vals[i];
                }
            }
            return best;
        }
        var bodyHtml = '';
        allMetricNames.forEach(function(name) {
            var cnName = metricNamesCN[name] || name;
            // 收集原始数值找最佳
            var rawVals = results.map(function(r) { return (r.ls_metrics && r.ls_metrics[name] !== undefined) ? r.ls_metrics[name] : null; });
            var best = mhBestColIdx(rawVals, name);
            bodyHtml += '<tr><td style="font-weight:600;">' + cnName + '</td>';
            results.forEach(function(r, ri) {
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
                var cellClass = (ri === best) ? ' class="group-best-cell"' : '';
                bodyHtml += '<td' + cellClass + '>' + display + '</td>';
            });
            bodyHtml += '</tr>';
        });
        document.getElementById('multi_horizon_body').innerHTML = bodyHtml;
    }

    // ---------- 多时段品种策略提示面板 ----------
    function updateStrategyPanel(multiSessionActive, usedMode) {
        var panel = document.getElementById('strategy_info_panel');
        var icon = document.getElementById('strategy_icon');
        var title = document.getElementById('strategy_title');
        var body = document.getElementById('strategy_body');
        if (!panel || !icon || !title || !body) return;

        if (multiSessionActive) {
            panel.style.display = 'block';
            panel.style.background = '#fff8e6';
            panel.style.borderLeftColor = '#e6a817';
            icon.textContent = '⚠️';
            title.textContent = '检测到含不同交易时段的产品';
            var modeLabel = {
                'each_period': '每期等权再平衡',
                'buy_and_hold': '组内持仓不动',
                'recycle': '退出资金优先补新仓'
            }[usedMode] || usedMode;
            body.innerHTML = '所选再平衡模式 <b>' + modeLabel + '</b> 仅在 <u>所有产品均有信号</u> 的期数中生效。<br>'
                + '在部分产品无信号（含 NaN）的混合期数中，自动切换为 <b>多时段品种策略</b>：<br>'
                + '• 保护无信号品种的持仓不动<br>'
                + '• 仅对有信号的品种进行交易和再平衡<br>'
                + '• 离场品种的资金回收后重新分配到新入场品种（扣除手续费）<br>'
                + '• 若某组只有新增、没有可回收资金，则该组当期冻结，不强行开新仓';
        } else {
            panel.style.display = 'block';
            panel.style.background = '#eef7ee';
            panel.style.borderLeftColor = '#2e7d32';
            icon.textContent = '✅';
            title.textContent = '所有产品具有统一的交易时段';
            body.textContent = '所有产品在所有期数中均有信号，您选择的再平衡模式将在每期中正常生效。';
        }
    }

    function updateRebalanceModeDescription() {
        var select = document.getElementById('rebalance_mode');
        var target = document.getElementById('rebalance_mode_description');
        if (!select || !target) return;
        var descriptions = {
            each_period: '每一期都把当前组内成员重新调成等权。适合比较“每期按最新排序重新建仓”的理论表现，换手通常最高。',
            buy_and_hold: '组内成员不变时保持原有持仓比例；只有成员进出组时才交易。更接近低换手的持有逻辑，也是默认模式。',
            recycle: '留存成员的持仓不动；有成员退出时，把释放出的资金优先分给新进成员。适合观察“旧仓尽量不动、只用退出资金补新仓”的过渡方式。',
        };
        target.textContent = descriptions[select.value] || '';
    }

    // ---------- 清空测试结果 ----------
    function clearResults(options) {
        options = options || {};
        var chartContainer = document.getElementById('group_chart_container');
        var metricsContainer = document.getElementById('group_metrics_container');
        var multiHorizonContainer = document.getElementById('multi_horizon_container');
        if (chartContainer) chartContainer.style.display = 'none';
        if (metricsContainer) metricsContainer.style.display = 'none';
        if (multiHorizonContainer) multiHorizonContainer.style.display = 'none';
        closeSnapshotDrawer();
        if (options.clearStatus) {
            var status = document.getElementById('group_test_status');
            if (status) status.innerHTML = '';
        }
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

        // 每组列等宽：标签列 40px，剩余平分
        var colWidth = groups.length > 0 ? (100 / groups.length).toFixed(2) + '%' : '100%';

        // 表头：每组一列（不含 LS）
        var headHtml = '<tr><th style="width:40px;"></th>';
        groups.forEach(function(g) {
            headHtml += '<th style="width:' + colWidth + ';">' + g.name + ' <span style="font-weight:normal;color:#888;">(' + g.count + '品种)</span></th>';
        });
        headHtml += '</tr>';
        document.getElementById('snapshot_head').innerHTML = headHtml;

        // helper：渲染一个产品对象 {name, desc} → HTML
        function _renderProduct(p) {
            if (!p) return '';
            if (typeof p === 'string') return p;
            if (p.desc && p.desc !== p.name) {
                return '<span title="' + p.name + '">' + p.name + ' <span style="color:#888;font-size:11px;">' + p.desc + '</span></span>';
            }
            return p.name || '';
        }

        // 出入标记最多的行数
        var maxRows = Math.max.apply(null, groups.map(function(g) {
            return Math.max(g.products_in.length, g.products_out.length, g.products.length);
        }));

        var tdStyleFull = 'style="width:' + colWidth + ';"';
        var tdStyleWidth = 'width:' + colWidth + ';';

        var bodyHtml = '';
        for (var i = 0; i < maxRows; i++) {
            bodyHtml += '<tr>';
            bodyHtml += '<td style="color:#888;font-size:11px;">' + (i === 0 ? '持仓' : '') + '</td>';
            groups.forEach(function(g) {
                var p = i < g.products.length ? g.products[i] : null;
                bodyHtml += '<td ' + tdStyleFull + '>' + _renderProduct(p) + '</td>';
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
                var p = j < g.products_in.length ? g.products_in[j] : null;
                bodyHtml += '<td style="color:#28a745;' + tdStyleWidth + '">' + _renderProduct(p) + '</td>';
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
                var p = k < g.products_out.length ? g.products_out[k] : null;
                bodyHtml += '<td style="color:#d40000;' + tdStyleWidth + '">' + _renderProduct(p) + '</td>';
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
            'Annual Return': '$$R_{\\text{ann}} = (1+R_{\\text{total}})^{N_{\\text{year}}/n} - 1$$',
            'Volatility': '$$\\sigma_{\\text{ann}} = \\sigma_{\\text{period}} \\cdot \\sqrt{N_{\\text{year}}}$$',
            'Sharpe Ratio': '$$\\text{Sharpe} = \\frac{\\bar r_{\\text{period}} \\cdot N_{\\text{year}}}{\\sigma_{\\text{period}} \\cdot \\sqrt{N_{\\text{year}}}}$$',
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
        var theadHtml = '<tr><th class="group-ranking-trigger" title="查看整体排序能力">指标</th>';
        groupLabels.forEach(function(g) {
            var isLS = (g === 'LS');
            if (isLS) {
                theadHtml += '<th style="background:#f0f0f0;">Long-Short</th>';
            } else {
                theadHtml += '<th class="group-detail-trigger" data-group-index="' + g + '" title="查看该组详情">第' + (parseInt(g)+1) + '组</th>';
            }
        });
        theadHtml += '</tr>';
        document.getElementById('metrics_head').innerHTML = theadHtml;
        
        // 最佳值方向：1 = 越大越好，-1 = 越小越好
        var METRIC_DIR = {
            'Total Return': 1, 'Annual Return': 1, 'Sharpe Ratio': 1, 'Calmar Ratio': 1,
            'Win Rate': 1, 'Mean Return': 1, 'Skewness': 1,
            'Volatility': -1, 'Max Drawdown': -1, 'Kurtosis': -1,
            'Avg Turnover': -1, 'Avg Turnover Accel': -1, 'Avg Position Changes': -1, 'Up Ratio': 1
        };
        // 辅助：找最佳值索引（传入 metricName 避免闭包混淆）
        function bestColIdx(values, metricName) {
            var dir = METRIC_DIR[metricName];
            if (dir === undefined) return -1;
            var best = -1, bestVal = null;
            for (var i = 0; i < values.length; i++) {
                if (values[i] === null || values[i] === undefined) continue;
                if (best === -1 || (dir >= 0 ? values[i] > bestVal : values[i] < bestVal)) {
                    best = i; bestVal = values[i];
                }
            }
            return best;
        }

        // 表体：每行一个指标
        var tbodyHtml = '';
        metricNames.forEach(function(name) {
            var cnName = metricNamesCN[name] || name;
            // 收集原始数值找最佳
            var rawVals = [];
            groupLabels.forEach(function(g) {
                rawVals.push(metrics[g][name]);
            });
            var best = bestColIdx(rawVals, name);

            tbodyHtml += '<tr><td class="metric-name-cell" data-metric="' + name.replace(/"/g, '&quot;') + '" style="cursor:pointer;position:relative;">' + cnName + '</td>';
            groupLabels.forEach(function(g, gi) {
                var isLS = (g === 'LS');
                var val = metrics[g][name];
                var cellClass = (gi === best) ? ' class="group-best-cell"' : '';
                var style = isLS ? ' style="background:#f0f0f0;"' : '';
                if (cellClass && isLS) style = ' class="group-best-cell" style="background:#e8f5e9;"';
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
                tbodyHtml += '<td' + (cellClass || style) + '>' + val + '</td>';
            });
            tbodyHtml += '</tr>';
        });
        document.getElementById('metrics_body').innerHTML = tbodyHtml;

        // 绑定指标名 hover 弹出描述和数学公式
        bindMetricHoverPopup(metricNamesCN, metricDescs, metricMathExprs);
        bindGroupDetailHeaders();
    }

    function bindGroupDetailHeaders() {
        document.querySelectorAll('#metrics_head .group-detail-trigger').forEach(function(th) {
            th.addEventListener('click', function() {
                openGroupDetail(parseInt(th.getAttribute('data-group-index'), 10));
            });
        });
        var rankingHead = document.querySelector('#metrics_head .group-ranking-trigger');
        if (rankingHead) {
            rankingHead.addEventListener('click', openGroupRankingDetail);
        }
    }

    function renderGroupDetailTable(rows, type) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>时间</th><th>收益</th><th>产品</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            var d = new Date(row.timestamp);
            var time = isNaN(d.getTime()) ? row.timestamp : d.toLocaleString();
            html += '<tr><td>' + time + '</td><td>' + (row.return * 100).toFixed(3) + '%</td><td>' + formatGroupProducts(row.products || []) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderGroupFrequency(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>产品</th><th>入组次数</th><th>频率</th></tr></thead><tbody>';
        rows.slice(0, 12).forEach(function(row) {
            html += '<tr><td>' + formatGroupProduct(row.product) + '</td><td>' + row.count + '</td><td>' + (row.frequency * 100).toFixed(1) + '%</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderPositiveRuns(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无连续正收益段</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>开始</th><th>结束</th><th>期数</th><th>区段收益</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + formatCompactTime(row.start) + '</td><td>' + formatCompactTime(row.end) + '</td><td>'
                + row.period_count + '</td><td>' + fmtPct(row.return) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderIntradayRows(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>时间</th><th>样本</th><th>均值</th><th>累计</th><th>t-like</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + row.time + '</td><td>' + row.count + '</td><td>' + fmtPct(row.mean) + '</td><td>'
                + fmtPct(row.sum) + '</td><td>' + (row.t_like == null ? '—' : Number(row.t_like).toFixed(3)) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderDailyRows(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>日期</th><th>样本</th><th>累计</th><th>均值</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + row.date + '</td><td>' + row.count + '</td><td>' + fmtPct(row.sum)
                + '</td><td>' + fmtPct(row.mean) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderIntradayWindows(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">尚未添加时间窗口</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>窗口</th><th>样本</th><th>累计贡献</th><th>占总收益</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + row.label + '</td><td>' + row.count + '</td><td>' + fmtPct(row.sum) + '</td><td>'
                + fmtPct(row.share_of_total_sum) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function formatGroupProduct(product) {
        if (!product) return '—';
        if (typeof product === 'string') return product;
        var name = product.name || '';
        var desc = product.desc && product.desc !== name ? ' · ' + product.desc : '';
        return name + desc;
    }

    function formatGroupProducts(products) {
        return (products || []).map(formatGroupProduct).join('、');
    }

    function renderGroupDetailHistogram(histogram) {
        var el = document.getElementById('group-detail-histogram');
        if (!el || typeof Highcharts === 'undefined') return;
        Highcharts.chart(el, {
            chart: { type: 'column', backgroundColor: 'transparent' },
            title: { text: null },
            xAxis: {
                categories: (histogram || []).map(function(bin) {
                    return (bin.left * 100).toFixed(2) + '% ~ ' + (bin.right * 100).toFixed(2) + '%';
                }),
                labels: { rotation: -35, style: { fontSize: '10px' } },
            },
            yAxis: { title: { text: '期数' } },
            legend: { enabled: false },
            series: [{ name: '期数', data: (histogram || []).map(function(bin) { return bin.count; }), color: '#4a90d9' }],
            credits: { enabled: false },
        });
    }

    function renderGroupDetailReturnChart(series) {
        var el = document.getElementById('group-detail-return-chart');
        if (!el || typeof Highcharts === 'undefined') return;
        var categories = (series || []).map(function(row) { return formatCompactTime(row.timestamp); });
        var returns = (series || []).map(function(row) { return Number(row.return); });
        var bounds = getRobustAxisBounds(returns);
        var outlierPoints = [];
        (series || []).forEach(function(row, idx) {
            if (row.return < bounds.min || row.return > bounds.max) {
                outlierPoints.push({
                    x: idx,
                    y: row.return < bounds.min ? bounds.min : bounds.max,
                    actualReturn: row.return,
                });
            }
        });
        Highcharts.stockChart(el, {
            chart: { backgroundColor: 'transparent', zoomType: 'x' },
            title: { text: null },
            legend: { enabled: true },
            xAxis: {
                ordinal: false,
                labels: {
                    formatter: function() {
                        var idx = Math.round(this.value);
                        return categories[idx] || '';
                    },
                },
            },
            yAxis: [{
                title: { text: '单期收益' },
                min: bounds.min,
                max: bounds.max,
                labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; } },
            }, {
                title: { text: '累计净值' },
                opposite: true,
            }],
            tooltip: {
                shared: true,
                formatter: function() {
                    var idx = this.points && this.points.length ? this.points[0].point.x : this.point.x;
                    var row = series[idx];
                    return '<b>' + categories[idx] + '</b><br/>'
                        + '单期收益: ' + fmtPct(row.return) + '<br/>'
                        + '累计净值: ' + Number(row.cumulative_return).toFixed(4);
                },
            },
            series: [{
                name: '单期收益',
                type: 'column',
                data: (series || []).map(function(row, idx) {
                    var clipped = Math.min(bounds.max, Math.max(bounds.min, row.return));
                    return { x: idx, y: clipped };
                }),
                color: '#7c9fe6',
            }, {
                name: '累计净值',
                type: 'line',
                yAxis: 1,
                data: (series || []).map(function(row, idx) { return [idx, row.cumulative_return]; }),
                color: '#0f4c81',
            }, {
                name: '离群值',
                type: 'scatter',
                data: outlierPoints,
                color: '#d14343',
                marker: { symbol: 'triangle', radius: 5 },
                enableMouseTracking: false,
                showInNavigator: false,
            }],
            navigator: {
                enabled: true,
                xAxis: {
                    labels: {
                        formatter: function() {
                            var idx = Math.round(this.value);
                            return categories[idx] || '';
                        },
                    },
                },
            },
            scrollbar: { enabled: true },
            rangeSelector: { enabled: false },
            credits: { enabled: false },
        });
    }

    function getRobustAxisBounds(values) {
        var clean = (values || []).filter(function(v) { return Number.isFinite(v); }).sort(function(a, b) { return a - b; });
        if (!clean.length) return { min: -0.01, max: 0.01 };
        function quantile(q) {
            var pos = (clean.length - 1) * q;
            var base = Math.floor(pos);
            var rest = pos - base;
            return clean[base + 1] !== undefined ? clean[base] + rest * (clean[base + 1] - clean[base]) : clean[base];
        }
        var low = quantile(0.01);
        var high = quantile(0.99);
        if (low === high) {
            var pad = Math.max(Math.abs(low) * 0.2, 0.001);
            return { min: low - pad, max: high + pad };
        }
        var pad = (high - low) * 0.15;
        return {
            min: Math.min(0, low - pad),
            max: Math.max(0, high + pad),
        };
    }

    function formatCompactTime(timestamp) {
        var d = new Date(timestamp);
        if (isNaN(d.getTime())) return timestamp;
        return d.toLocaleString();
    }

    function renderGroupDetail(detail) {
        var summary = detail.summary || {};
        var labels = {
            'Total Return': '总收益',
            'Annual Return': '年化',
            'Sharpe Ratio': '夏普',
            'Max Drawdown': '最大回撤',
            'Win Rate': '胜率',
            'Avg Turnover': '换手率',
        };
        document.getElementById('group-detail-summary').innerHTML = Object.keys(labels).map(function(key) {
            var value = summary[key];
            var display = value == null ? '—' : (
                key.indexOf('Return') >= 0 || key.indexOf('Drawdown') >= 0 || key === 'Win Rate'
                    ? Number(value).toFixed(2) + '%'
                    : key === 'Avg Turnover'
                        ? (Number(value) * 100).toFixed(1) + '%'
                        : Number(value).toFixed(4)
            );
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">' + labels[key] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
        document.getElementById('group-detail-frequency').innerHTML = renderGroupFrequency(detail.entry_frequency);
        document.getElementById('group-detail-top-periods').innerHTML = renderGroupDetailTable(detail.top_periods);
        document.getElementById('group-detail-bottom-periods').innerHTML = renderGroupDetailTable(detail.bottom_periods);
        var q = (detail.distribution || {}).quantiles || {};
        document.getElementById('group-detail-quantiles').textContent =
            'P05 ' + fmtPct(q.p05) + ' · P50 ' + fmtPct(q.p50) + ' · P95 ' + fmtPct(q.p95);
        document.getElementById('group-detail-frequency-summary').textContent =
            (detail.entry_frequency && detail.entry_frequency.length)
                ? '哪些产品最常进入该组 · ' + formatGroupProduct(detail.entry_frequency[0].product) + ' ' + (detail.entry_frequency[0].frequency * 100).toFixed(1) + '%'
                : '哪些产品最常进入该组';
        document.getElementById('group-detail-distribution-summary').textContent =
            '收益直方图与分位数 · P50 ' + fmtPct(q.p50) + ' · P95 ' + fmtPct(q.p95);
        renderPositiveRunAnalysis(detail.positive_run_analysis || {});
        renderIntradayAnalysis(detail.intraday_analysis || {});
        renderDailyAnalysis(detail.daily_analysis || {});
        renderRobustnessSummary(detail.robustness_summary || {}, detail.period_robustness || {});
        renderGroupDetailReturnChart(detail.return_series || []);
        renderGroupDetailHistogram((detail.distribution || {}).histogram || []);
    }

    function renderPositiveRunAnalysis(analysis) {
        var top1 = analysis.top1_positive_contribution_ratio;
        var top3 = analysis.top3_positive_contribution_ratio;
        var concentrated = !!analysis.is_concentrated;
        document.getElementById('group-detail-positive-run-summary').textContent =
            concentrated
                ? '疑似依赖少数正收益段'
                : '检查收益是否集中在少数连续正收益段';
        var overview = document.getElementById('group-detail-positive-run-overview');
        if (!analysis.run_count) {
            overview.textContent = '没有检测到连续正收益段。';
        } else {
            overview.textContent =
                '共 ' + analysis.run_count + ' 段连续正收益；最强 1 段贡献 ' + fmtPct(top1)
                + ' 的正收益，最强 3 段贡献 ' + fmtPct(top3)
                + '。去掉最强 1 段后累计收益 ' + fmtPct(analysis.return_without_top1_run)
                + '，去掉最强 3 段后累计收益 ' + fmtPct(analysis.return_without_top3_runs)
                + (concentrated ? '。当前表现明显依赖少数正收益段。' : '。');
        }
        document.getElementById('group-detail-positive-runs').innerHTML = renderPositiveRuns(analysis.top_runs);
    }

    function renderIntradayAnalysis(analysis) {
        var top = analysis.top_times || [];
        var bottom = analysis.bottom_times || [];
        var best = top[0];
        _groupIntradayRows = analysis.rows || [];
        _groupIntradayWindows = [];
        document.getElementById('group-detail-intraday-summary').textContent =
            best ? '哪些分钟真正贡献了收益 · 最高 ' + best.time + ' ' + fmtPct(best.sum) : '哪些分钟真正贡献了收益';
        renderSelectedIntradayWindows();
        document.getElementById('group-detail-intraday-top').innerHTML = renderIntradayRows(top);
        document.getElementById('group-detail-intraday-bottom').innerHTML = renderIntradayRows(bottom);
    }

    function renderDailyAnalysis(analysis) {
        var top = analysis.top_days || [];
        var bottom = analysis.bottom_days || [];
        var best = top[0];
        document.getElementById('group-detail-daily-summary').textContent =
            best ? '哪些交易日主导了结果 · 最高 ' + best.date + ' ' + fmtPct(best.sum) : '哪些交易日主导了结果';
        document.getElementById('group-detail-daily-overview').textContent =
            '去掉贡献最高 1 日后累计收益 ' + fmtPct(analysis.return_without_top1_day)
            + '；去掉贡献最高 5 日后累计收益 ' + fmtPct(analysis.return_without_top5_days) + '。';
        document.getElementById('group-detail-daily-top').innerHTML = renderDailyRows(top);
        document.getElementById('group-detail-daily-bottom').innerHTML = renderDailyRows(bottom);
    }

    function renderRobustnessSummary(summary, periodRobustness) {
        var top1 = periodRobustness.without_top1pct || {};
        var top5 = periodRobustness.without_top5pct || {};
        var issueLabels = {
            positive_runs: '少数连续正收益段',
            top_day: '单一交易日',
            top_periods: '头部时段',
        };
        var issues = (summary.issues || []).map(function(key) { return issueLabels[key] || key; });
        document.getElementById('group-detail-robustness-summary').textContent =
            summary.is_fragile ? '存在集中性风险' : '未见明显集中性风险';
        document.getElementById('group-detail-robustness-overview').textContent =
            '去掉最好 1% 时段后累计收益 ' + fmtPct(top1.remaining_return)
            + '；去掉最好 5% 时段后累计收益 ' + fmtPct(top5.remaining_return)
            + (issues.length ? '。当前主要风险来自：' + issues.join('、') + '。' : '。');
    }

    var _groupIntradayRows = [];
    var _groupIntradayWindows = [];

    function summarizeIntradayWindow(start, end) {
        var rows = (_groupIntradayRows || []).filter(function(row) {
            return row.time >= start && row.time <= end;
        });
        var total = (_groupIntradayRows || []).reduce(function(sum, row) { return sum + (row.sum || 0); }, 0);
        var contribution = rows.reduce(function(sum, row) { return sum + (row.sum || 0); }, 0);
        var count = rows.reduce(function(sum, row) { return sum + (row.count || 0); }, 0);
        return {
            label: start + '-' + end,
            count: count,
            sum: contribution,
            share_of_total_sum: total !== 0 ? contribution / total : null,
        };
    }

    function renderSelectedIntradayWindows() {
        var target = document.getElementById('group-detail-intraday-windows');
        if (target) target.innerHTML = renderIntradayWindows(_groupIntradayWindows);
    }

    function addSelectedIntradayWindow() {
        var startEl = document.getElementById('group-intraday-window-start');
        var endEl = document.getElementById('group-intraday-window-end');
        if (!startEl || !endEl || !startEl.value || !endEl.value || startEl.value > endEl.value) return;
        _groupIntradayWindows.push(summarizeIntradayWindow(startEl.value, endEl.value));
        renderSelectedIntradayWindows();
    }

    function fmtPct(value) {
        return value == null ? '—' : (value * 100).toFixed(3) + '%';
    }

    async function openGroupDetail(groupIndex) {
        var context = getCurrentContext();
        if (!context || !context.submission_id) return;
        var overlay = document.getElementById('group-detail-overlay');
        var loading = document.getElementById('group-detail-loading');
        var content = document.getElementById('group-detail-content');
        document.getElementById('group-detail-title').textContent = '第' + (groupIndex + 1) + '组详情';
        overlay.classList.add('open');
        loading.style.display = '';
        content.style.display = 'none';
        try {
            var resp = await fetch('/get_group_detail', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ submission_id: context.submission_id, group_index: groupIndex }),
            });
            var data = await resp.json();
            if (!data.success) throw new Error(data.error || '加载失败');
            renderGroupDetail(data.detail || {});
            loading.style.display = 'none';
            content.style.display = '';
        } catch (err) {
            loading.textContent = '加载失败: ' + (err.message || err);
        }
    }

    function renderGroupRankingAdjacent(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>组间</th><th>平均差</th><th>为正占比</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>第' + (row.from_group + 1) + '组 - 第' + (row.to_group + 1) + '组</td><td>'
                + fmtPct(row.mean_spread) + '</td><td>' + fmtPct(row.positive_ratio) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderGroupRankingDetail(detail) {
        var topBottom = detail.top_bottom || {};
        var labels = [
            ['monotonic_period_ratio', '单调期占比', true],
            ['descending_period_ratio', '严格降序占比', true],
            ['mean_rank_correlation', '平均秩相关', false],
            ['mean_non_empty_group_count', '平均有效组数', false],
            ['full_group_period_ratio', '全组可比期占比', true],
            ['top_bottom_mean', '首尾组平均差', true],
            ['top_bottom_positive', '首尾差为正占比', true],
        ];
        var values = {
            monotonic_period_ratio: detail.monotonic_period_ratio,
            descending_period_ratio: detail.descending_period_ratio,
            mean_rank_correlation: detail.mean_rank_correlation,
            mean_non_empty_group_count: detail.mean_non_empty_group_count,
            full_group_period_ratio: detail.full_group_period_ratio,
            top_bottom_mean: topBottom.mean_spread,
            top_bottom_positive: topBottom.positive_ratio,
        };
        document.getElementById('group-ranking-summary').innerHTML = labels.map(function(item) {
            var value = values[item[0]];
            var display = value == null ? '—' : (item[2] ? fmtPct(value) : Number(value).toFixed(4));
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
        document.getElementById('group-ranking-adjacent').innerHTML = renderGroupRankingAdjacent(detail.adjacent_spreads);
        document.getElementById('group-ranking-overview-summary').textContent =
            '整体排序质量 · 单调 ' + fmtPct(detail.monotonic_period_ratio) + ' · 首尾为正 ' + fmtPct(topBottom.positive_ratio);
        document.getElementById('group-ranking-spread-summary').textContent =
            '最高组减最低组的逐期表现 · 均值 ' + fmtPct(topBottom.mean_spread) + ' · 为正 ' + fmtPct(topBottom.positive_ratio);
        renderGroupRankingSpreadChart(topBottom.series || []);
        renderGroupRankingMonotonicChart(detail.monotonic_series || []);
    }

    function renderGroupRankingSpreadChart(series) {
        var el = document.getElementById('group-ranking-spread-chart');
        if (!el || typeof Highcharts === 'undefined') return;
        Highcharts.chart(el, {
            chart: { backgroundColor: 'transparent' },
            title: { text: null },
            xAxis: { type: 'datetime' },
            yAxis: [{
                title: { text: '单期组差' },
                labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; } },
            }, {
                title: { text: '累计净值' },
                opposite: true,
            }],
            tooltip: { shared: true },
            series: [{
                name: '单期 Top-Bottom',
                type: 'column',
                data: series.map(function(row) { return [new Date(row.timestamp).getTime(), row.spread]; }),
                color: '#7c9fe6',
                tooltip: { valueSuffix: '' },
            }, {
                name: '累计净值',
                type: 'line',
                yAxis: 1,
                data: series.map(function(row) { return [new Date(row.timestamp).getTime(), row.cumulative_return]; }),
                color: '#0f4c81',
            }],
            credits: { enabled: false },
        });
    }

    function renderGroupRankingMonotonicChart(series) {
        var el = document.getElementById('group-ranking-monotonic-chart');
        if (!el || typeof Highcharts === 'undefined') return;
        var categories = (series || []).map(function(row) { return formatCompactTime(row.timestamp); });
        Highcharts.chart(el, {
            chart: { type: 'column', backgroundColor: 'transparent' },
            title: { text: null },
            xAxis: {
                categories: categories,
                labels: { step: Math.max(1, Math.ceil(categories.length / 8)) },
            },
            yAxis: {
                min: 0,
                max: 1,
                tickPositions: [0, 1],
                title: { text: null },
                labels: {
                    formatter: function() { return this.value === 1 ? '单调' : '非单调'; },
                },
            },
            legend: { enabled: false },
            tooltip: {
                formatter: function() {
                    var row = series[this.point.index];
                    var state = row.is_descending ? '严格降序' : (row.is_monotonic ? '严格升序' : '非单调');
                    return '<b>' + categories[this.point.index] + '</b><br/>' + state;
                },
            },
            series: [{
                name: '单调性',
                data: (series || []).map(function(row) {
                    return {
                        y: row.is_monotonic ? 1 : 0,
                        color: row.is_descending ? '#2f855a' : (row.is_monotonic ? '#7c9fe6' : '#d0d5dd'),
                    };
                }),
            }],
            credits: { enabled: false },
        });
    }

    async function openGroupRankingDetail() {
        var context = getCurrentContext();
        if (!context || !context.submission_id) return;
        var overlay = document.getElementById('group-ranking-overlay');
        var loading = document.getElementById('group-ranking-loading');
        var content = document.getElementById('group-ranking-content');
        overlay.classList.add('open');
        loading.style.display = '';
        loading.textContent = '加载中...';
        content.style.display = 'none';
        try {
            var resp = await fetch('/get_group_ranking_detail', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ submission_id: context.submission_id }),
            });
            var data = await resp.json();
            if (!data.success) throw new Error(data.error || '加载失败');
            renderGroupRankingDetail(data.detail || {});
            loading.style.display = 'none';
            content.style.display = '';
        } catch (err) {
            loading.textContent = '加载失败: ' + (err.message || err);
        }
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

    async function collectGroupRunPayload(context, factorAlias) {
        var statusSpan = document.getElementById('group_test_status');
        var currentSubmissionId = context && context.submission_id;
        if (!currentSubmissionId || !factorAlias) {
            return { error: '请先选择测试器和因子' };
        }

        var n_groups = parseInt(document.getElementById('group_count').value, 10);
        var feeMode = 'none';
        var feeModeEl = document.querySelector('input[name="fee_mode"]:checked');
        if (feeModeEl) feeMode = feeModeEl.value;

        var fee = 0.0;
        var fee_map = {};
        var use_closetoday = _useCloseToday;
        if (feeMode === 'uniform') {
            fee = parseFloat(document.getElementById('fee_rate').value) || 0.0;
        } else if (feeMode === 'per_product') {
            if (!_feeTableData.length) {
                if (statusSpan) {
                    statusSpan.innerHTML = '正在获取品种费率...';
                    statusSpan.style.color = '#0078d4';
                }
                try {
                    await fetchFeeTable(false);
                } catch (err) {
                    return { error: '获取品种费率失败: ' + err.message };
                }
            }
            fee_map = buildFeeMap();
            if (!Object.keys(fee_map).length) {
                return { error: '未获取到品种费率，请检查费率数据源。' };
            }
        }

        var sy = document.getElementById('group_start_year').value;
        var sm = document.getElementById('group_start_month').value;
        var sd = document.getElementById('group_start_day').value;
        var ey = document.getElementById('group_end_year').value;
        var em = document.getElementById('group_end_month').value;
        var ed = document.getElementById('group_end_day').value;

        var start_date = (sy && sm && sd) ? buildValidDate(sy, sm, sd) : null;
        var end_date = (ey && em && ed) ? buildValidDate(ey, em, ed) : null;

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

        if (!start_date || !end_date) {
            var submission = window.submissions ? window.submissions.find(function(s) { return String(s.id) === String(currentSubmissionId); }) : null;
            if (submission) {
                if (!start_date) start_date = submission.start_date;
                if (!end_date) end_date = submission.end_date;
            }
        }

        if (!start_date || !end_date) return { error: '请设置时间范围' };
        if (start_date > end_date) return { error: '起始日期不能晚于终止日期' };

        var return_freqs = getSelectedReturnFreqs();
        return {
            payload: {
                submission_id: currentSubmissionId,
                factor_alias: factorAlias,
                n_groups: n_groups,
                fee: fee,
                fee_map: fee_map,
                use_closetoday: use_closetoday,
                start_date: start_date,
                end_date: end_date,
                return_freqs: return_freqs.length > 0 ? return_freqs : null,
                rebalance_mode: document.getElementById('rebalance_mode')?.value || 'buy_and_hold'
            },
            statusEl: statusSpan,
        };
    }

    function applyGroupTestResult(data, statusText) {
        if (data.multi_horizon) {
            updateStrategyPanel(data.multi_session_active, data.rebalance_mode);
            var chartContainer = document.getElementById('group_chart_container');
            var metricsContainer = document.getElementById('group_metrics_container');
            if (chartContainer) chartContainer.style.display = 'none';
            if (metricsContainer) metricsContainer.style.display = 'none';
            closeSnapshotDrawer();
            _lastGrossData = null;
            _lastMetrics = null;
            renderMultiHorizonTable(data.results, data.n_groups);
            return;
        }

        updateStrategyPanel(data.multi_session_active, data.rebalance_mode);
        _lastGrossData = data.groups;
        _lastMetrics = data.metrics;
        _lastNgroups = data.n_groups;
        _lastTimestamps = data.groups.length > 0 ? data.groups[0].timestamps : [];
        drawGroupChart(data.groups);
        renderMetricsTable(data.metrics);
        var slider = document.getElementById('fee_sensitivity_slider');
        if (slider) { slider.value = 0; updateSensitivityLabel(0); }
    }

    function postGroupTest(payload) {
        return fetch('/run_group_test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function(res) { return res.json(); });
    }

    // ---------- 运行分组测试 ----------
    async function runGroupTest() {
        var context = getCurrentContext();
        if (!context) {
            alert(getMissingGroupContextMessage());
            return;
        }
        var built = await collectGroupRunPayload(context, context.factor_alias);
        var statusSpan = built.statusEl || document.getElementById('group_test_status');
        if (built.error) {
            statusSpan.innerHTML = '✗ ' + built.error;
            statusSpan.style.color = '#d40000';
            return;
        }

        statusSpan.innerHTML = '分组测试运行中...';
        statusSpan.style.color = '#0078d4';
        var multiHorizonContainer = document.getElementById('multi_horizon_container');
        if (multiHorizonContainer) multiHorizonContainer.style.display = 'none';

        postGroupTest(built.payload)
        .then(function(data) {
            if (!data.success) {
                var errorText = data.needs_ic_test && pageHasICModule()
                    ? '当前测试器还没有 IC 测试结果。请先在 IC 测试模块运行一次 IC 测试，再运行分组测试。'
                    : data.error;
                statusSpan.innerHTML = '✗ 分组测试失败: ' + errorText;
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

            statusSpan.innerHTML = data.multi_horizon ? ('✓ 多周期对比完成（' + data.results.length + ' 个频率）') : '✓ 分组测试完成';
            statusSpan.style.color = '#28a745';
            cacheGroupResult(context.submission_id, context.factor_alias, data);
            markGroupFactorStatus(context.submission_id, context.factor_alias, data.success ? 'done' : 'error');
            applyGroupTestResult(data);
        })
        .catch(function(err) {
            statusSpan.innerHTML = '请求失败: ' + err.message;
            statusSpan.style.color = '#d40000';
            console.error(err);
        });
    }

    async function runAllGroupTestsForCurrentSubmission() {
        var submissionId = getActiveGroupSubmissionId();
        if (!submissionId) {
            alert('请先选择一个 FactorTester 选项卡');
            return;
        }
        var factors = Array.isArray(window.factorList) ? window.factorList : [];
        if (!factors.length) {
            alert('暂无可运行因子');
            return;
        }
        var firstContext = {
            submission_id: submissionId,
        };
        var statusSpan = document.getElementById('group_test_status');
        var runBtn = document.getElementById('run_group_test_btn');
        var runAllBtn = document.getElementById('run_all_group_tests_btn');
        if (runBtn) runBtn.disabled = true;
        if (runAllBtn) runAllBtn.disabled = true;
        clearCachedGroupResultsForSubmission(submissionId);
        clearGroupFactorStatuses(submissionId);
        clearResults({ clearStatus: true });
        try {
            for (var i = 0; i < factors.length; i++) {
                var factor = factors[i];
                var factorAlias = factor.alias || factor.name;
                var built = await collectGroupRunPayload(firstContext, factorAlias);
                if (built.error) {
                    if (statusSpan) {
                        statusSpan.innerHTML = '✗ ' + built.error;
                        statusSpan.style.color = '#d40000';
                    }
                    return;
                }
                if (statusSpan) {
                    statusSpan.innerHTML = '分组测试运行中... ' + (i + 1) + '/' + factors.length + ' · ' + factorAlias;
                    statusSpan.style.color = '#0078d4';
                }
                markGroupFactorStatus(submissionId, factorAlias, '');
                try {
                    var data = await postGroupTest(built.payload);
                    if (!data.success) {
                        markGroupFactorStatus(submissionId, factorAlias, 'error');
                        cacheGroupResult(submissionId, factorAlias, data);
                        if (statusSpan) {
                            var errorText = data.needs_ic_test && pageHasICModule()
                                ? '当前测试器还没有 IC 测试结果。请先在 IC 测试模块运行一次 IC 测试。'
                                : (data.error || '未知错误');
                            statusSpan.innerHTML = '✗ ' + factorAlias + ' 分组测试失败: ' + errorText;
                            statusSpan.style.color = '#d40000';
                        }
                        return;
                    }
                    cacheGroupResult(submissionId, factorAlias, data);
                    markGroupFactorStatus(submissionId, factorAlias, 'done');
                } catch (err) {
                    markGroupFactorStatus(submissionId, factorAlias, 'error');
                    if (statusSpan) {
                        statusSpan.innerHTML = '✗ ' + factorAlias + ' 请求失败: ' + err.message;
                        statusSpan.style.color = '#d40000';
                    }
                    return;
                }
            }
            var activeBtn = document.querySelector('.group-factor-nav-btn[data-submission-id="' + cssEscape(String(submissionId)) + '"].active');
            var activeAlias = activeBtn ? activeBtn.getAttribute('data-factor-alias') : (factors[0].alias || factors[0].name);
            var result = getCachedGroupResult(submissionId, activeAlias);
            if (result && result.success) applyGroupTestResult(result);
            if (statusSpan) {
                statusSpan.innerHTML = '✓ 已完成当前测试器全部 ' + factors.length + ' 个因子的分组测试';
                statusSpan.style.color = '#28a745';
            }
        } finally {
            if (runBtn) runBtn.disabled = false;
            if (runAllBtn) runAllBtn.disabled = false;
        }
    }

    // ---------- 成本敏感性：缓存数据 ----------
    var _lastGrossData = null;   // 上次返回的 groups（含 gross_returns / fee_costs）
    var _lastMetrics = null;
    var _lastTimestamps = [];
    var _lastNgroups = 0;
    var _groupResultsBySubmission = {};
    var _activeGroupSubmissionId = null;
    var _activeGroupFactorBySubmission = {};

    function cacheGroupResult(submissionId, factorAlias, data) {
        if (!submissionId || !factorAlias || !data) return;
        if (!_groupResultsBySubmission[submissionId]) _groupResultsBySubmission[submissionId] = {};
        _groupResultsBySubmission[submissionId][factorAlias] = data;
    }

    function getCachedGroupResult(submissionId, factorAlias) {
        return _groupResultsBySubmission[submissionId] && _groupResultsBySubmission[submissionId][factorAlias];
    }

    function clearCachedGroupResultsForSubmission(submissionId) {
        if (!submissionId) return;
        _groupResultsBySubmission[submissionId] = {};
    }

    function markGroupFactorStatus(submissionId, factorAlias, status) {
        var btn = document.querySelector('.group-factor-nav-btn[data-submission-id="' + cssEscape(String(submissionId)) + '"][data-factor-alias="' + cssEscape(String(factorAlias)) + '"]');
        if (!btn) return;
        btn.setAttribute('data-run-status', status || '');
        var badge = btn.querySelector('.group-factor-run-status');
        if (badge) {
            badge.textContent = status === 'done' ? '✓' : (status === 'error' ? '!' : '');
            badge.style.color = status === 'error' ? '#d40000' : '#28a745';
        }
    }

    function clearGroupFactorStatuses(submissionId) {
        document.querySelectorAll('.group-factor-nav-btn[data-submission-id="' + cssEscape(String(submissionId)) + '"]').forEach(function(btn) {
            btn.setAttribute('data-run-status', '');
            var badge = btn.querySelector('.group-factor-run-status');
            if (badge) badge.textContent = '';
        });
    }

    function cssEscape(value) {
        if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(value);
        return value.replace(/["\\]/g, '\\$&');
    }

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
            newMetrics[String(g)] = calcMetricsFromReturns(returns, t.slice(1));
        }

        // LS
        var lsCum = recalcGroups[nGroups] ? recalcGroups[nGroups].cumulative_returns : null;
        if (lsCum) {
            var lsReturns = [];
            for (var i = 1; i < lsCum.length; i++) {
                lsReturns.push(lsCum[i] / lsCum[i-1] - 1.0);
            }
            newMetrics['LS'] = calcMetricsFromReturns(lsReturns, t.slice(1));
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

    function inferPeriodsPerYearFromTimestamps(timestamps) {
        if (!timestamps || timestamps.length < 2) return 252;
        var dayCounts = {};
        timestamps.forEach(function(ts) {
            var d = new Date(ts);
            if (isNaN(d.getTime())) return;
            var key = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
            dayCounts[key] = (dayCounts[key] || 0) + 1;
        });
        var counts = Object.keys(dayCounts).map(function(key) { return dayCounts[key]; }).sort(function(a, b) { return a - b; });
        if (!counts.length) return 252;
        var median = counts[Math.floor(counts.length / 2)];
        if (median > 1) return median * 252;
        var days = Object.keys(dayCounts).sort();
        if (days.length < 2) return 252;
        var start = new Date(days[0] + 'T00:00:00');
        var end = new Date(days[days.length - 1] + 'T00:00:00');
        var businessDays = 0;
        for (var cur = new Date(start); cur <= end; cur.setDate(cur.getDate() + 1)) {
            var dow = cur.getDay();
            if (dow !== 0 && dow !== 6) businessDays++;
        }
        return businessDays > 0 ? Math.max(1, days.length / businessDays * 252) : 252;
    }

    /** 从收益率序列计算指标 */
    function calcMetricsFromReturns(returns, timestamps) {
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
        var annualPeriods = inferPeriodsPerYearFromTimestamps(timestamps);
        var annualRet = (Math.pow(cum, annualPeriods / n) - 1) * 100;
        var vol = std * Math.sqrt(annualPeriods) * 100;
        var sharpe = std > 0 ? (mean * annualPeriods) / (std * Math.sqrt(annualPeriods)) : 0;
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

    // ---------- 监听 IC 模块及自身选项卡切换 ----------
    function bindICModuleEvents() {
        // 分组测试结果按 submission + factor 缓存，切换选项卡时不主动清空。
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
        return fetch('/get_fee_table', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_refresh: !!forceRefresh })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) {
                if (statusEl) { statusEl.textContent = '获取失败: ' + data.error; statusEl.style.color = '#d40000'; }
                throw new Error(data.error || '获取失败');
            }
            _feeTableData = data.rows || [];
            renderFeeTable();
            updateFeeSummary();
            if (statusEl) { statusEl.textContent = '✓ 已加载 ' + _feeTableData.length + ' 个品种'; statusEl.style.color = '#28a745'; }
            return data;
        })
        .catch(function(err) {
            if (statusEl) { statusEl.textContent = '请求失败: ' + err.message; statusEl.style.color = '#d40000'; }
            throw err;
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
                var uniformWrap     = document.getElementById('fee_uniform_row');
                if (uniformWrap)    uniformWrap.style.display    = (mode === 'uniform')     ? 'flex' : 'none';
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
        if (fetchBtn) fetchBtn.addEventListener('click', function() { fetchFeeTable(false).catch(function() {}); });

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
        bindGroupDetailOverlay();
        bindGroupSectionToggles();
        updateRebalanceModeDescription();
        syncFromTimeModule();
        document.addEventListener('timeRangeDefaultLoaded', syncFromTimeModule, { once: true });
        setTimeout(syncFromTimeModule, 0);
        var runBtn = document.getElementById('run_group_test_btn');
        if (runBtn) runBtn.addEventListener('click', runGroupTest);
        var runAllBtn = document.getElementById('run_all_group_tests_btn');
        if (runAllBtn) runAllBtn.addEventListener('click', runAllGroupTestsForCurrentSubmission);
        var rebalanceSelect = document.getElementById('rebalance_mode');
        if (rebalanceSelect) rebalanceSelect.addEventListener('change', updateRebalanceModeDescription);
        var addIntradayWindowBtn = document.getElementById('group-intraday-window-add');
        if (addIntradayWindowBtn) addIntradayWindowBtn.addEventListener('click', addSelectedIntradayWindow);

        // 如果已有 submissions，渲染两级选项卡
        if (window.submissions && window.submissions.length > 0) {
            window.renderGroupTabs(window.submissions);
        }
    }

    function bindGroupDetailOverlay() {
        var overlay = document.getElementById('group-detail-overlay');
        var closeBtn = document.getElementById('group-detail-close');
        if (closeBtn) closeBtn.addEventListener('click', function() {
            if (overlay) overlay.classList.remove('open');
        });
        if (overlay) overlay.addEventListener('click', function(event) {
            if (event.target === overlay) overlay.classList.remove('open');
        });
        var rankingOverlay = document.getElementById('group-ranking-overlay');
        var rankingCloseBtn = document.getElementById('group-ranking-close');
        if (rankingCloseBtn) rankingCloseBtn.addEventListener('click', function() {
            if (rankingOverlay) rankingOverlay.classList.remove('open');
        });
        if (rankingOverlay) rankingOverlay.addEventListener('click', function(event) {
            if (event.target === rankingOverlay) rankingOverlay.classList.remove('open');
        });
    }

    function bindGroupSectionToggles() {
        document.querySelectorAll('.group-detail-section-toggle').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var section = btn.closest('.group-detail-section');
                if (section) section.classList.toggle('open');
            });
        });
    }

    // 暴露给外部调用：渲染分组测试的三级工作区（submission → factor → settings）
    window.renderGroupTabs = function(submissions) {
        var container = document.getElementById('group-tab-container');
        var runBtn = document.getElementById('run_group_test_btn');
        var runAllBtn = document.getElementById('run_all_group_tests_btn');
        if (!container) return;
        if (!submissions || submissions.length === 0) {
            container.innerHTML = '<div style="color:#888; padding:8px; border:1px dashed #ccc; border-radius:4px; font-size:13px;">暂无提交记录，请先在产品类别筛选模块提交产品。</div>';
            if (runBtn) runBtn.style.display = 'none';
            if (runAllBtn) runAllBtn.style.display = 'none';
            return;
        }
        if (runBtn) runBtn.style.display = '';
        if (runAllBtn) runAllBtn.style.display = '';

        var factorList = window.factorList || [];
        var activeSubmission = submissions.find(function(sub) {
            return String(sub.id) === String(_activeGroupSubmissionId);
        }) || submissions[0];
        _activeGroupSubmissionId = activeSubmission ? String(activeSubmission.id) : null;

        var submissionsHtml = '<div class="group-nav-column"><div class="group-nav-title">产品组 / 测试器</div>';
        submissions.forEach(function(sub, idx) {
            var isActive = String(sub.id) === String(_activeGroupSubmissionId);
            var tabLabel = sub.product_group || sub.label || ('测试器' + (idx+1));
            var subMeta = sub.product_group ? '产品组' : (sub.factor_tester_serial || 'FactorTester');
            submissionsHtml += '<button type="button" class="group-submission-nav-btn' + (isActive ? ' active' : '') + '" data-submission-id="' + escGrp(sub.id) + '">'
                + '<span>' + (sub.product_group ? '📦 ' : '') + escGrp(tabLabel) + '</span>'
                + '<small style="color:#667085;font-size:11px;">' + escGrp(subMeta) + '</small>'
                + '</button>';
        });
        submissionsHtml += '</div>';

        var factorsHtml = '<div class="group-factor-sidebar"><div class="group-nav-title">因子列表</div>';
        if (factorList.length > 0 && _activeGroupSubmissionId) {
            var activeFactorAlias = getActiveFactorAliasForSubmission(_activeGroupSubmissionId) || (factorList[0].alias || factorList[0].name || '');
            _activeGroupFactorBySubmission[_activeGroupSubmissionId] = activeFactorAlias;
            factorList.forEach(function(f) {
                var alias = f.alias || f.name || '';
                var isFactorActive = alias === activeFactorAlias;
                var cached = getCachedGroupResult(_activeGroupSubmissionId, alias);
                var status = cached ? (cached.success ? 'done' : 'error') : '';
                factorsHtml += '<button type="button" class="group-factor-nav-btn' + (isFactorActive ? ' active' : '') + '" data-submission-id="' + escGrp(_activeGroupSubmissionId) + '" data-factor-alias="' + escGrp(alias) + '" data-run-status="' + status + '">'
                    + '<span>' + escGrp(alias) + '</span>'
                    + '<span class="group-factor-run-status" style="font-size:12px;color:' + (status === 'error' ? '#d40000' : '#28a745') + ';font-weight:700;">' + (status === 'done' ? '✓' : (status === 'error' ? '!' : '')) + '</span>'
                    + '</button>';
            });
        } else {
            factorsHtml += '<div style="color:#888;font-size:12px;padding:8px;">暂无因子列表</div>';
        }
        factorsHtml += '</div>';

        container.innerHTML = submissionsHtml + factorsHtml;

        bindGroupFactorTabLongPress();
        bindGroupSubmissionNavigation(submissions);
        bindGroupFactorNavigation();
        restoreActiveGroupResult({ preserveWhenMissingActive: factorList.length === 0 });
    };

    function getActiveFactorAliasForSubmission(submissionId) {
        if (_activeGroupFactorBySubmission[submissionId]) return _activeGroupFactorBySubmission[submissionId];
        var activeBtn = document.querySelector('.group-factor-nav-btn.active[data-submission-id="' + cssEscape(String(submissionId)) + '"]');
        if (activeBtn) return activeBtn.getAttribute('data-factor-alias');
        var cached = _groupResultsBySubmission[submissionId];
        if (cached) {
            var first = Object.keys(cached)[0];
            if (first) return first;
        }
        return null;
    }

    function bindGroupSubmissionNavigation(submissions) {
        document.querySelectorAll('.group-submission-nav-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                _activeGroupSubmissionId = btn.getAttribute('data-submission-id');
                window.renderGroupTabs(submissions);
            });
        });
    }

    function bindGroupFactorNavigation() {
        document.querySelectorAll('.group-factor-nav-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.group-factor-nav-btn').forEach(function(other) {
                    other.classList.remove('active');
                });
                btn.classList.add('active');
                _activeGroupFactorBySubmission[btn.getAttribute('data-submission-id')] = btn.getAttribute('data-factor-alias');
                restoreActiveGroupResult();
            });
        });
    }

    function restoreActiveGroupResult(options) {
        options = options || {};
        var activeBtn = document.querySelector('.group-factor-nav-btn.active');
        if (!activeBtn) {
            if (!options.preserveWhenMissingActive) {
                clearResults({ clearStatus: false });
            }
            return;
        }
        var result = getCachedGroupResult(activeBtn.getAttribute('data-submission-id'), activeBtn.getAttribute('data-factor-alias'));
        clearResults({ clearStatus: !result });
        if (result && result.success) {
            applyGroupTestResult(result);
            var statusSpan = document.getElementById('group_test_status');
            if (statusSpan) {
                statusSpan.innerHTML = result.multi_horizon ? ('✓ 多周期对比完成（' + result.results.length + ' 个频率）') : '✓ 分组测试完成';
                statusSpan.style.color = '#28a745';
            }
        } else if (result && !result.success) {
            var statusEl = document.getElementById('group_test_status');
            if (statusEl) {
                statusEl.innerHTML = '✗ 分组测试失败: ' + (result.error || '未知错误');
                statusEl.style.color = '#d40000';
            }
        }
    }

    // ── 长按因子选项卡辅助函数 ──
    function bindGroupFactorTabLongPress() {
        var helper = window.SingleFactorLibraryHelper;
        if (!helper) return;
        var allFactorTabs = document.querySelectorAll('.group-factor-nav-btn');
        allFactorTabs.forEach(function(btn) {
            helper.bindLongPress(btn, {
                popoverClass: 'group-add-to-library-popover',
                getFactorAlias: function(anchor) {
                    return anchor.getAttribute('data-factor-alias') || anchor.textContent.trim();
                },
                getProductGroup: function(anchor) {
                    return helper.inferScopeFromSubmissionId(anchor.getAttribute('data-submission-id'));
                }
            });
        });
    }

    function escGrp(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
