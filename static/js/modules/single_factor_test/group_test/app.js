(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GroupTest] bootstrap missing'); return; }

    // 确保 GT.ui 在全局代码使用前已初始化
    GT.ui = GT.ui || {};

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

        function isFiniteNumber(v) {
            return typeof v === 'number' && isFinite(v) && !isNaN(v);
        }

        // pct is already in percent units (e.g. 0.12 means 0.12%).
        function formatPercentAdaptive(pct, metricName) {
            if (!isFiniteNumber(pct)) return '—';
            var abs = Math.abs(pct);

            // Mean Return is often tiny; show basis points when small to avoid all zeros.
            if (metricName === 'Mean Return' && abs < 0.1) {
                var bp = pct * 100; // 1% = 100 bp
                var decBp = Math.abs(bp) >= 1 ? 2 : 3;
                return bp.toFixed(decBp) + ' bp';
            }

            var dec;
            if (abs >= 10) dec = 2;
            else if (abs >= 1) dec = 3;
            else if (abs >= 0.1) dec = 4;
            else if (abs >= 0.01) dec = 5;
            else dec = 6;
            return pct.toFixed(dec) + '%';
        }

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
                    display = formatPercentAdaptive(val, name);
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

    function buildContinuousTimeAxis(rows, timestampGetter) {
        var labels = (rows || []).map(function(row) {
            return formatCompactTime(timestampGetter(row));
        });
        return {
            labels: labels,
            labelAt: function(value) {
                return labels[Math.round(value)] || '';
            },
        };
    }

    function drawGroupChart(groups) {
        var container = document.getElementById('group_chart_container');
        if (!container || !groups || groups.length === 0) {
            if (container) container.style.display = 'none';
            return;
        }
        container.style.display = 'block';

        // ── 1. 计算 GCD ──
        function gcd(a, b) {
            a = Math.abs(a); b = Math.abs(b);
            while (b) { var t = b; b = a % b; a = t; }
            return a || 1;
        }
        var allDiffs = [];
        var globalMin = Infinity, globalMax = -Infinity;
        var groupRanges = []; // {min, max} for each group
        var i, j;
        for (i = 0; i < groups.length; i++) {
            var gts = groups[i].timestamps || [];
            if (gts.length === 0) continue;
            for (j = 1; j < gts.length; j++) {
                var d = gts[j] - gts[j - 1];
                if (d > 0) allDiffs.push(d);
            }
            groupRanges.push({ min: gts[0], max: gts[gts.length - 1] });
            if (gts[0] < globalMin) globalMin = gts[0];
            if (gts[gts.length - 1] > globalMax) globalMax = gts[gts.length - 1];
        }
        var step = null;
        for (i = 0; i < allDiffs.length; i++) {
            step = (step === null) ? allDiffs[i] : gcd(step, allDiffs[i]);
        }

        // Fallback: 如果没有有效 step，回到去重排序
        if (!step || step <= 0 || globalMin >= globalMax) {
            step = null;
        }

        // ── 2. 构建 timeline：GCD 等间隔，过滤休市 ──
        // 判定某时间点是否被至少一个 group 的覆盖区间包含
        function isCovered(ts) {
            for (var r = 0; r < groupRanges.length; r++) {
                if (ts >= groupRanges[r].min && ts <= groupRanges[r].max) return true;
            }
            return false;
        }

        var timeline = [];
        if (step) {
            for (var t = globalMin; t <= globalMax; t += step) {
                if (isCovered(t)) timeline.push(t);
            }
        } else {
            // 回退：去重排序
            var tset = {};
            for (i = 0; i < groups.length; i++) {
                var tts = groups[i].timestamps || [];
                for (j = 0; j < tts.length; j++) { tset[tts[j]] = true; }
            }
            timeline = Object.keys(tset).map(Number).sort(function(a, b) { return a - b; });
        }

        // 检测是否日内
        var isIntraday = false;
        if (timeline.length >= 2) {
            isIntraday = (timeline[1] - timeline[0]) < 86400000;
        }

        // 格式化时间标签
        function formatDateLabel(ts) {
            var d = new Date(ts);
            if (isIntraday) {
                return d.getFullYear() + '-' +
                    String(d.getMonth() + 1).padStart(2, '0') + '-' +
                    String(d.getDate()).padStart(2, '0') + ' ' +
                    String(d.getHours()).padStart(2, '0') + ':' +
                    String(d.getMinutes()).padStart(2, '0');
            } else {
                return d.getFullYear() + '-' +
                    String(d.getMonth() + 1).padStart(2, '0') + '-' +
                    String(d.getDate()).padStart(2, '0');
            }
        }

        // ── 3. 每个 group 映射到共享 timeline ──
        var series = groups.map(function(group) {
            // 直接用后端返回的 key 作为图例名
            var alias = group.key || group.name;
            var gts = group.timestamps || [];
            var vals = group.cumulative_returns || [];

            // timestamp → value 映射
            var valMap = {};
            for (var k = 0; k < Math.min(gts.length, vals.length); k++) {
                if (vals[k] !== null) valMap[gts[k]] = vals[k];
            }

            // 映射到共享 timeline（有值为数据点，无值为 null，connectNulls 连线）
            var data = [];
            for (var ti = 0; ti < timeline.length; ti++) {
                var ts = timeline[ti];
                data.push([ti, valMap.hasOwnProperty(ts) ? valMap[ts] : null]);
            }

            var opts = {
                name: alias,
                type: 'line',
                data: data,
                tooltip: { valueDecimals: 4 },
                visible: true,
                showInLegend: true,
                connectNulls: true
            };
            if (group.is_ls) {
                opts.color = '#000';
                opts.dashStyle = 'Dash';
                opts.lineWidth = 2;
            }
            return opts;
        });

        // 图表参数：合理间隔标签
        var labelEvery = Math.max(1, Math.floor(timeline.length / 12));

        _groupChart = Highcharts.stockChart(container, {
            chart: {
                zoomType: 'x',
                events: {
                    click: function(e) {
                        var idx = Math.round(e.xAxis[0].value);
                        if (idx >= 0 && idx < timeline.length) {
                            fetchGroupSnapshot(timeline[idx]);
                        }
                    }
                }
            },
            title: { text: '分组累计收益（初始净值 = 1）' },
            legend: {
                enabled: true,
                align: 'center',
                verticalAlign: 'bottom',
                layout: 'horizontal',
                itemStyle: { fontSize: '11px' }
            },
            xAxis: {
                type: 'linear',
                labels: {
                    step: labelEvery,
                    formatter: function() {
                        var idx = Math.round(this.value);
                        if (idx >= 0 && idx < timeline.length) {
                            return formatDateLabel(timeline[idx]);
                        }
                        return '';
                    }
                }
            },
            yAxis: { title: { text: '净值' }, crosshair: false },
            plotOptions: {
                series: {
                    cursor: 'pointer',
                    connectNulls: true,
                    point: {
                        events: {
                            click: function() {
                                var idx = Math.round(this.x);
                                if (idx >= 0 && idx < timeline.length) {
                                    fetchGroupSnapshot(timeline[idx]);
                                }
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
                    var idx = Math.round(this.x);
                    var ts = (idx >= 0 && idx < timeline.length) ? timeline[idx] : null;
                    var dateStr = ts ? formatDateLabel(ts) : '—';
                    var s = '<b>' + dateStr + '</b>';
                    this.points.forEach(function (p) {
                        if (p.y === null || p.y === undefined) return;
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
            rangeSelector: { enabled: false }
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
        // Prefer modular sectioned table if available (Issue #50).
        if (GT && typeof GT.renderSectionedMetricsTable === 'function') {
            var containerMod = document.getElementById('group_metrics_container');
            if (!containerMod || !metrics || Object.keys(metrics).length === 0) {
                if (containerMod) containerMod.style.display = 'none';
                return;
            }
            containerMod.style.display = 'block';
            GT.renderSectionedMetricsTable(metrics, _lastGrossData);
            // Preserve existing bindings that rely on #metrics_head click targets.
            bindGroupDetailHeaders();
            // Hover popup still works because metric-name-cell class is preserved.
            // (Math/desc dictionaries are currently local to legacy renderer; will be migrated later.)
            return;
        }

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

        // headerLabel: 参数就是 group/metrics 的 key（如 "B1"），直接返回
        function headerLabel(key) {
            // fallback: 纯数字 → 第X组（兼容旧数据）
            if (/^\d+$/.test(String(key))) return '第' + (parseInt(key) + 1) + '组';
            return String(key);
        }

        // 转置：行 = 指标名，列 = 分组
        // 表头：第一列「指标」，后面每个分组一列
        var lsMap = {};
        (_lastGrossData || []).forEach(function(g) { if (g && g.key && g.is_ls) lsMap[g.key] = true; });
        var theadHtml = '<tr><th class="group-ranking-trigger" title="查看整体排序能力">指标</th>';
        groupLabels.forEach(function(g) {
            var label = headerLabel(g);
            if (lsMap[g]) {
                theadHtml += '<th class="portfolio-detail-trigger" data-group-key="' + escapeHtml(g) + '" style="background:#f0f0f0;" title="查看组合详情">' + label + '</th>';
            } else if (/^\d+$/.test(String(g))) {
                theadHtml += '<th class="group-detail-trigger" data-group-index="' + g + '" title="查看该组详情">' + label + '</th>';
            } else {
                theadHtml += '<th class="portfolio-detail-trigger" data-group-key="' + escapeHtml(g) + '" style="background:#f8fbff;" title="查看组合详情">' + label + '</th>';
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

        function isFiniteNumber(v) {
            return typeof v === 'number' && isFinite(v) && !isNaN(v);
        }

        // pct is already in percent units (e.g. 0.12 means 0.12%).
        function formatPercentAdaptive(pct, metricName) {
            if (!isFiniteNumber(pct)) return '—';
            var abs = Math.abs(pct);

            // Mean Return is often tiny; show basis points when small to avoid all zeros.
            if (metricName === 'Mean Return' && abs < 0.1) {
                var bp = pct * 100; // 1% = 100 bp
                var decBp = Math.abs(bp) >= 1 ? 2 : 3;
                return bp.toFixed(decBp) + ' bp';
            }

            var dec;
            if (abs >= 10) dec = 2;
            else if (abs >= 1) dec = 3;
            else if (abs >= 0.1) dec = 4;
            else if (abs >= 0.01) dec = 5;
            else dec = 6;
            return pct.toFixed(dec) + '%';
        }

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
                var isLS = lsMap[g] || false;
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
                        val = formatPercentAdaptive(val, name);
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
        document.querySelectorAll('#metrics_head .portfolio-detail-trigger').forEach(function(th) {
            th.addEventListener('click', function() {
                openPortfolioDetail(th.getAttribute('data-group-key'));
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

    function renderGroupFrequency(rows, selectable) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        selectable = selectable !== false;
        var hasHighlight = false;
        var feeLabel = isRealFee(rows[0]) ? ' (原始费率)' : '';
        var html = '';
        // 绿色行快捷新建按钮 — 在表格上方
        rows.forEach(function(row) {
            var meanRet = row.mean_return;
            var fee = (row.product && row.product.fee) || {};
            var totalFee = (fee.total != null && isFinite(fee.total)) ? fee.total : 0;
            if (meanRet != null && isFinite(meanRet) && meanRet > totalFee) hasHighlight = true;
        });
        if (selectable && hasHighlight) {
            html += '<div style="margin-bottom:6px;">'
                + '<button type="button" class="btn btn-sm btn-outline-success" id="derived-group-quick-define-btn"'
                + ' style="font-size:12px;padding:3px 10px;border-color:#86efac;color:#16a34a;">'
                + '新建收益率大于费率的派生组</button>'
                + '<span style="font-size:11px;color:#888;margin-left:8px;">自动勾选绿色行（均值收益 > 费率）并创建派生组</span>'
                + '</div>';
        }
        html += '<table class="group-detail-table"><thead><tr>'
            + (selectable ? '<th style="width:34px;"><input type="checkbox" id="derived-select-all-products" title="全选当前显示品种"></th>' : '')
            + '<th>产品</th><th>产品描述</th><th>均值收益</th><th>开仓费率' + feeLabel + '</th><th>平今费率' + feeLabel + '</th><th>平昨费率' + feeLabel + '</th><th>入组次数</th><th>频率</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            var meanRet = row.mean_return;
            var fee = (row.product && row.product.fee) || {};
            var totalFee = (fee.total != null && isFinite(fee.total)) ? fee.total : 0;
            var isHighlight = (meanRet != null && isFinite(meanRet) && meanRet > totalFee);
            var highlight = isHighlight ? ' style="background:rgba(144,238,144,0.25)"' : '';
            var dataHighlight = isHighlight ? ' data-highlight="1"' : '';
            var prod = row.product;
            var name = (prod && prod.name) || '—';
            var desc = (prod && prod.desc && prod.desc !== name) ? prod.desc : '—';
            html += '<tr' + highlight + dataHighlight + '>'
                + (selectable ? '<td><input type="checkbox" class="derived-product-checkbox" data-product-name="' + escapeHtml(name) + '"></td>' : '')
                + '<td>' + escapeHtml(name) + '</td><td style="max-width:120px;white-space:normal;word-break:break-all">' + escapeHtml(desc) + '</td>'
                + '<td>' + fmtFeeRate(meanRet) + '</td>'
                + '<td>' + fmtFeeRate(fee.open) + '</td>'
                + '<td>' + fmtFeeRate(fee.close_today) + '</td>'
                + '<td>' + fmtFeeRate(fee.close_yesterday != null ? fee.close_yesterday : fee.close) + '</td>'
                + '<td>' + (row.count == null ? '—' : row.count) + '</td><td>' + (row.frequency == null ? '—' : (row.frequency * 100).toFixed(1) + '%') + '</td></tr>';
        });
        html += '</tbody></table>';
        return html;
    }

    function getDerivedGroupsForCurrentBase(groupIndex) {
        return _derivedGroups.filter(function(item) { return item.baseGroup === groupIndex; });
    }

    function renderDerivedGroupsPanel(groupIndex) {
        var el = document.getElementById('group-derived-groups-panel');
        if (!el) return;

        var baseGroupId = findBaseGroupIdForResultGroup(groupIndex);
        // 直接从 datamodel 读取当前 base group 下所有派生节点
        var derivedNodes = [];
        if (baseGroupId && GT.datamodel && GT.datamodel.groups) {
            var allNodes = GT.datamodel.groups.getAll();
            for (var i = 0; i < allNodes.length; i++) {
                if (allNodes[i].isDerived && allNodes[i].baseGroupId === baseGroupId) {
                    derivedNodes.push(allNodes[i]);
                }
            }
        }

        var html = '<div class="derived-group-panel" style="border:1px solid #c7d2fe;border-radius:8px;background:#f8faff;padding:8px;">'
            + '<div class="derived-group-toolbar" style="display:flex;align-items:center;gap:8px;padding:4px 0;margin-bottom:6px;border-bottom:1px solid #e2e8f0;">'
            + '<b style="font-size:13px;color:#1e293b;">派生组</b>'
            + '<span style="flex:1;"></span>'
            + '<button type="button" class="btn btn-sm btn-outline-primary" id="derived-group-define-btn" style="font-size:12px;padding:3px 10px;">新建</button>'
            + '</div>';

        if (!derivedNodes.length) {
            html += '<div style="padding:8px;text-align:center;color:#888;font-size:12px;">暂无派生组 · 勾选下方品种后点击「新建」</div>';
        } else {
            for (var d = 0; d < derivedNodes.length; d++) {
                var node = derivedNodes[d];
                var alias = groupDisplayKey(node);
                var products = effectiveDerivedProductNames(node);
                var generated = _derivedGroups.some(function(dg) { return dg.id === node.id && dg.generated; });

                html += '<div class="derived-group-list-row" data-derived-id="' + escapeHtml(node.id) + '"'
                    + ' style="display:flex;align-items:center;padding:4px 6px;border-radius:6px;border-bottom:1px solid #f0f0f0;font-size:12px;">'
                    + '<span style="width:6px;height:6px;border-radius:50%;background:#6366f1;flex-shrink:0;margin-right:8px;"></span>'
                    + '<span style="width:20px;margin-right:2px;flex-shrink:0;"></span>'
                    + '<span style="font-weight:600;color:#4338ca;min-width:32px;font-size:13px;margin-right:8px;">' + escapeHtml(alias) + '</span>'
                    + '<span style="flex:1;"></span>'
                    + '<span class="overlay-dg-product-chip" data-overlay-dg-id="' + escapeHtml(node.id) + '"'
                    + ' style="display:inline-block;cursor:pointer;background:#c7d2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#312e81;margin-right:8px;">'
                    + '📋 ' + products.length + '品种 ▸</span>'
                    + (generated ? '<span style="color:#16a34a;font-size:11px;margin-right:8px;">已生成</span>' : '<span style="color:#f59e0b;font-size:11px;margin-right:8px;">未生成</span>')
                    + '<button type="button" class="btn btn-sm btn-outline-primary derived-group-generate-btn" data-derived-id="' + escapeHtml(node.id) + '" style="font-size:11px;padding:2px 8px;">生成曲线/统计</button>'
                    + '<button type="button" class="btn btn-sm btn-outline-danger derived-group-delete-btn" data-derived-id="' + escapeHtml(node.id) + '" style="margin-left:4px;padding:1px 5px;font-size:11px;border:1px solid #fca5a5;border-radius:3px;background:#fef2f2;color:#dc2626;cursor:pointer;">✕</button>'
                    + '</div>';

                // 可展开产品列表
                if (products.length > 0) {
                    html += '<div class="overlay-dg-product-list" data-overlay-dg-id="' + escapeHtml(node.id) + '"'
                        + ' style="display:none;margin-left:34px;padding:4px 8px;border-left:2px solid #c7d2fe;font-size:11px;">';
                    for (var pi = 0; pi < products.length; pi++) {
                        html += '<div style="padding:2px 0;"><span style="color:#0078d4;font-weight:600;margin-right:8px;">' + escapeHtml(products[pi]) + '</span></div>';
                    }
                    html += '</div>';
                }
            }
        }
        html += '</div>';
        el.innerHTML = html;
        bindDerivedGroupPanelEvents(groupIndex);
    }

    function bindDerivedGroupPanelEvents(groupIndex) {
        var selectAll = document.getElementById('derived-select-all-products');
        if (selectAll) {
            selectAll.addEventListener('change', function() {
                document.querySelectorAll('.derived-product-checkbox').forEach(function(cb) {
                    cb.checked = selectAll.checked;
                });
            });
        }
        var defineBtn = document.getElementById('derived-group-define-btn');
        if (defineBtn) defineBtn.addEventListener('click', function() { defineDerivedGroup(groupIndex); });

        // 绿色行快捷新建：自动勾选「收益率 > 费率」产品并创建派生组
        var quickBtn = document.getElementById('derived-group-quick-define-btn');
        if (quickBtn) {
            quickBtn.addEventListener('click', function() {
                document.querySelectorAll('.derived-product-checkbox').forEach(function(cb) {
                    var row = cb.closest('tr');
                    if (row && row.hasAttribute('data-highlight')) {
                        cb.checked = true;
                    }
                });
                defineDerivedGroup(groupIndex);
            });
        }

        // product chip 展开/折叠产品列表
        document.querySelectorAll('.overlay-dg-product-chip').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var dgId = this.getAttribute('data-overlay-dg-id');
                var list = document.querySelector('.overlay-dg-product-list[data-overlay-dg-id="' + dgId + '"]');
                if (!list) return;
                var isHidden = list.style.display === 'none';
                list.style.display = isHidden ? 'block' : 'none';
                this.innerHTML = '📋 ' + (list.querySelectorAll('div').length) + '品种 ' + (isHidden ? '▾' : '▸');
            });
        });

        document.querySelectorAll('.derived-group-generate-btn').forEach(function(btn) {
            btn.addEventListener('click', function() { generateDerivedGroup(btn.getAttribute('data-derived-id')); });
        });
        document.querySelectorAll('.derived-group-delete-btn').forEach(function(btn) {
            btn.addEventListener('click', function() { deleteDerivedGroup(btn.getAttribute('data-derived-id')); });
        });
    }

    function collectSelectedDerivedProducts() {
        var names = [];
        document.querySelectorAll('.derived-product-checkbox:checked').forEach(function(cb) {
            var name = cb.getAttribute('data-product-name');
            if (name) names.push(name);
        });
        return names;
    }

    function productNamesForTester(testerId) {
        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) !== String(testerId)) continue;
            return (subs[i].products || []).map(function(product) {
                return typeof product === 'string' ? product : (product && (product.name || product.desc)) || '';
            }).filter(Boolean);
        }
        return [];
    }

    function effectiveDerivedProductNames(node, seen) {
        if (!node) return [];
        seen = seen || {};
        if (seen[node.id]) return [];
        seen[node.id] = true;

        var mask = node.productMask || {};
        var selected = Object.keys(mask).filter(function(name) { return mask[name]; });
        if (selected.length) return selected;

        if (node.parentId && GT.datamodel && GT.datamodel.groups) {
            return effectiveDerivedProductNames(GT.datamodel.groups.get(node.parentId), seen);
        }

        if (node.baseGroupId && GT.datamodel && GT.datamodel.groups) {
            var base = GT.datamodel.groups.get(node.baseGroupId);
            if (base && Array.isArray(base.products) && base.products.length) return base.products.slice();
            if (base && base.testerId) return productNamesForTester(base.testerId);
        }
        return [];
    }

    function groupDisplayKey(group, allGroups) {
        if (!group) return '';
        if (!group.isDerived) return group.shortAlias || group.key || group.name || group.id || '';
        allGroups = allGroups || (GT.datamodel && GT.datamodel.groups && GT.datamodel.groups.getAll ? GT.datamodel.groups.getAll() : []);
        var base = GT.datamodel && GT.datamodel.groups ? GT.datamodel.groups.get(group.baseGroupId) : null;
        var baseAlias = base ? (base.shortAlias || base.name || base.id) : (group.baseGroupId || '');
        var siblings = allGroups.filter(function(item) {
            return item && item.isDerived && item.baseGroupId === group.baseGroupId && item.parentId === group.parentId;
        });
        var pos = siblings.findIndex(function(item) { return item.id === group.id; });
        var suffix = pos >= 0 ? String(pos + 1) : (group.name || group.id || '?');
        if (group.parentId) {
            var parent = GT.datamodel && GT.datamodel.groups ? GT.datamodel.groups.get(group.parentId) : null;
            var parentAlias = parent ? groupDisplayKey(parent, allGroups) : baseAlias;
            return parentAlias + ':' + suffix;
        }
        return baseAlias + ':' + suffix;
    }

    function lsDisplayName(ls) {
        if (!ls) return 'Long-Short';
        if (ls.shortAlias) return ls.shortAlias;
        var groups = GT.datamodel && GT.datamodel.groups;
        var longGroup = groups && groups.get ? groups.get(ls.longGroupId) : null;
        var shortGroup = groups && groups.get ? groups.get(ls.shortGroupId) : null;
        var longAlias = groupDisplayKey(longGroup) || 'Long';
        var shortAlias = groupDisplayKey(shortGroup) || 'Short';
        return longAlias + '/' + shortAlias;
    }

    function serializeGroupFeeMap(feeMap) {
        if (!feeMap || typeof feeMap !== 'object') return null;
        var serialized = {};
        Object.keys(feeMap).forEach(function(code) {
            var ov = feeMap[code];
            if (ov && typeof ov === 'object') {
                serialized[String(code).toLowerCase()] = {
                    open: ov.open_ratio != null ? ov.open_ratio : null,
                    close: ov.close_ratio != null ? ov.close_ratio : null,
                    close_today: ov.closetoday_ratio != null ? ov.closetoday_ratio : (ov.close_today_ratio != null ? ov.close_today_ratio : null)
                };
            }
        });
        return Object.keys(serialized).length > 0 ? serialized : null;
    }

    function serializeGroupVariant(group, fallbackName) {
        if (!group) return null;
        var mode = group.feeMode || 'none';
        var displayName = group.shortAlias || group.name || fallbackName || group.id || '';
        return {
            name: displayName,
            key: displayName,
            fee_mode: mode,
            fee_rate: group.feeRate != null ? group.feeRate : null,
            fee_map: (mode === 'per_product' || mode === 'custom') ? serializeGroupFeeMap(group.feeMap) : null,
            use_close_today: group.useCloseToday !== undefined ? !!group.useCloseToday : null,
            rebalance_mode: group.rebalanceMode || 'buy_and_hold'
        };
    }

    function collectDerivedPayloadForBatch(batch) {
        if (!batch || !GT.datamodel || !GT.datamodel.groups) return [];
        var all = GT.datamodel.groups.getAll ? (GT.datamodel.groups.getAll() || []) : [];
        var baseById = {};
        (batch.groups || []).forEach(function(group) {
            if (group && group.id) baseById[group.id] = group;
        });

        var payload = [];
        all.forEach(function(group) {
            if (!group || !group.isDerived || !group.baseGroupId) return;
            var base = baseById[group.baseGroupId];
            if (!base) return;
            var products = effectiveDerivedProductNames(group);
            if (!products.length) return;
            var displayName = group.shortAlias || groupDisplayKey(group, all) || group.name || '派生组';
            payload.push({
                id: group.id,
                key: displayName,
                name: displayName,
                baseGroup: (base.groupIndex || 1) - 1,
                productNames: products,
                fee_mode: group.feeMode || 'none',
                fee_rate: group.feeRate != null ? group.feeRate : null,
                fee_map: serializeGroupFeeMap(group.feeMap),
                useCloseToday: group.useCloseToday !== undefined ? !!group.useCloseToday : false,
                rebalanceMode: group.rebalanceMode || 'each_period',
                rebalance_mode: group.rebalanceMode || 'each_period'
            });
        });
        return payload;
    }

    function defineDerivedGroup(groupIndex) {
        var productNames = collectSelectedDerivedProducts();
        if (!productNames.length) {
            alert('请先勾选至少一个入组产品。');
            return;
        }
        var baseGroupId = findBaseGroupIdForResultGroup(groupIndex);
        if (!baseGroupId) {
            alert('未找到对应基础组，请先在左侧面板创建分组组合。');
            return;
        }
        var productMask = {};
        productNames.forEach(function(pn) { productMask[pn] = true; });
        var newId;
        try {
            newId = GT.datamodel.groups.add({
                name: '',
                isDerived: true,
                baseGroupId: baseGroupId,
                parentId: null,
                productMask: productMask
            });
        } catch (e) {
            alert('创建派生组失败: ' + (e.message || e));
            return;
        }
        renderDerivedGroupsPanel(groupIndex);
    }

    function findBaseGroupIdForResultGroup(groupIndex) {
        if (!GT.datamodel || !GT.datamodel.groups) return null;
        var context = getCurrentContext();
        var all = GT.datamodel.groups.getAll ? (GT.datamodel.groups.getAll() || []) : [];
        var expectedIndex = Number(groupIndex) + 1;
        var matches = all.filter(function(group) {
            if (!group || group.isDerived) return false;
            if (Number(group.groupIndex) !== expectedIndex) return false;
            if (context && context.submission_id && String(group.testerId) !== String(context.submission_id)) return false;
            if (context && context.factor_alias && String(group.factorAlias || '') !== String(context.factor_alias || '')) return false;
            return true;
        });
        if (matches.length === 1) return matches[0].id;
        if (matches.length > 1 && _lastGrossData && _lastGrossData[groupIndex]) {
            var resultKey = _lastGrossData[groupIndex].key;
            var byAlias = matches.filter(function(group) { return group.shortAlias === resultKey; });
            if (byAlias.length === 1) return byAlias[0].id;
        }
        return matches.length ? matches[0].id : null;
    }

    function openAddDerivedFromDetail(groupIndex) {
        var productNames = collectSelectedDerivedProducts();
        if (!productNames.length) {
            alert('请先勾选至少一个入组产品。');
            return;
        }
        var baseGroupId = findBaseGroupIdForResultGroup(groupIndex);
        if (!baseGroupId) {
            alert('无法匹配当前结果对应的基础组，请从分组列表中选择基础组后新建派生组。');
            return;
        }
        var input = document.getElementById('derived-group-name-input');
        var defaultName = '第' + (groupIndex + 1) + '组精选';
        var name = (input && input.value ? input.value.trim() : '') || defaultName;
        _panelMode = 'add';
        _addDraft = {
            addFlow: 'derived',
            preselectedBaseGroupId: baseGroupId,
            preselectedProducts: productNames,
            name: name,
            defaultName: name,
        };
        if (GT.state && GT.state.setActiveDerivedNodeId) GT.state.setActiveDerivedNodeId(null);
        mountTab('add-derived');
        _renderTabActions();
        var overlay = document.getElementById('group-detail-overlay');
        if (overlay) overlay.classList.remove('open');
    }

    function makeUniqueGroupKey(name, ownId) {
        var base = name || ownId || '派生组';
        var key = base;
        var suffix = 2;
        while (_lastMetrics && _lastMetrics[key]) {
            var owner = _derivedGroups.find(function(item) { return item.key === key; });
            if (owner && owner.id === ownId) break;
            key = base + ' #' + suffix++;
        }
        return key;
    }

    function removeGeneratedDerivedArtifacts(id) {
        var node = GT.datamodel && GT.datamodel.groups ? GT.datamodel.groups.get(id) : null;
        var key = node ? groupDisplayKey(node) : null;
        if (_lastGrossData) {
            _lastGrossData = _lastGrossData.filter(function(group) {
                return !(group && group.is_derived && group.derived && group.derived.id === id);
            });
        }
        if (key && _lastMetrics) delete _lastMetrics[key];
    }

    /** 为单个派生组发请求，不画图；返回 {success, def, group, metric} 或 null。 */
    async function _generateDerivedGroupOnce(def, fee, fee_map) {
        var context = getCurrentContext();
        if (!def || !context || !context.submission_id) return null;
        if (def.baseGroup == null) return null;
        try {
            var resp = await GT.api.createDerivedGroup({
                submission_id: context.submission_id,
                group_index: def.baseGroup,
                product_names: def.productNames,
                name: def.name,
                use_closetoday: def.useCloseToday !== undefined ? !!def.useCloseToday : false,
                fee: fee || 0,
                fee_map: fee_map || {}
            });
            if (!resp || !resp.success) return { success: false, def: def, error: (resp && resp.error) || '未知错误' };
            return { success: true, def: def, group: resp.group || {}, metric: resp.metric || {} };
        } catch (err) {
            return { success: false, def: def, error: err.message || '网络错误' };
        }
    }

    /** 将 _generateDerivedGroupOnce 的结果应用到内存数据（不画图）。 */
    function _applyDerivedGroupResult(result) {
        var def = result.def;
        removeGeneratedDerivedArtifacts(def.id);
        def.key = makeUniqueGroupKey(def.name, def.id);
        def.generated = true;
        var group = result.group;
        group.name = def.name;
        group.is_derived = true;
        group.derived = Object.assign({}, group.derived || {}, { id: def.id, key: def.key });
        _lastGrossData.push(group);
        _lastMetrics[def.key] = result.metric;
    }

    /** 统一刷新：图表 + 指标表 + 面板。 */
    function _refreshGroupView(baseGroupIndex) {
        drawGroupChart(_lastGrossData);
        renderMetricsTable(_lastMetrics);
        updateActiveGroupCache();
        renderDerivedGroupsPanel(baseGroupIndex);
    }

    /** 单个派生组生成：发 1 次请求，更新数据，刷新 1 次。 */
    async function generateDerivedGroup(id) {
        var node = GT.datamodel && GT.datamodel.groups ? GT.datamodel.groups.get(id) : null;
        if (!node || !node.isDerived) return;
        var products = effectiveDerivedProductNames(node);
        if (!products.length) {
            alert('该派生组没有选中任何品种。');
            return;
        }
        if (!_lastGrossData || !_lastMetrics) {
            alert('请先运行分组测试，再生成派生组曲线。');
            return;
        }
        // 找到 base group（解析费率用）
        var baseNode = GT.datamodel.groups.get(node.baseGroupId);
        // 找到 baseGroupIndex（0-based，从 _lastGrossData 匹配 key）
        var baseGroupIndex = _currentGroupDetailIndex;
        if (baseGroupIndex == null && baseNode) {
            baseGroupIndex = (baseNode.groupIndex || 1) - 1;
        }
        // 从 base group 聚合费率
        var fee = 0;
        var fee_map = {};
        if (baseNode) {
            if (baseNode.feeMode === 'uniform') {
                fee = baseNode.feeRate != null ? baseNode.feeRate : 0.0025;
            } else if (baseNode.feeMode === 'per_product') {
                try {
                    fee_map = await GT.fee.ensureFeeData();
                } catch (err) {
                    console.error('[generateDerivedGroup] ensureFeeData failed:', err);
                }
            }
        }
        var def = {
            id: node.id,
            name: groupDisplayKey(node),
            key: groupDisplayKey(node),
            baseGroup: baseGroupIndex,
            productNames: products,
            productMask: node.productMask || {}
        };
        var result = await _generateDerivedGroupOnce(def, fee, fee_map);
        if (!result || !result.success) {
            alert('生成派生组失败: ' + ((result && result.error) || '未知错误'));
            return;
        }
        _applyDerivedGroupResult(result);
        _refreshGroupView(baseGroupIndex);
    }

    function deleteDerivedGroup(id) {
        var node = GT.datamodel && GT.datamodel.groups ? GT.datamodel.groups.get(id) : null;
        var baseGroupIndex = _currentGroupDetailIndex;
        if (baseGroupIndex == null && node && node.baseGroupId) {
            var baseNode = GT.datamodel.groups.get(node.baseGroupId);
            if (baseNode) baseGroupIndex = (baseNode.groupIndex || 1) - 1;
        }
        removeGeneratedDerivedArtifacts(id);
        try {
            if (GT.datamodel && GT.datamodel.groups) GT.datamodel.groups.remove(id);
            if (GT.state && GT.state.emit) GT.state.emit('groupsChanged');
        } catch (e) {
            console.warn('[deleteDerivedGroup] datamodel remove failed:', e);
        }
        if (_lastGrossData) drawGroupChart(_lastGrossData);
        if (_lastMetrics) renderMetricsTable(_lastMetrics);
        updateActiveGroupCache();
        renderDerivedGroupsPanel(baseGroupIndex != null ? baseGroupIndex : 0);
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

    function renderProductContributionRows(rows) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var feeLabel = isRealFee(rows[0]) ? ' (原始费率)' : '';
        var html = '<table class="group-detail-table"><thead><tr><th>产品</th><th>产品描述</th><th>开仓费率' + feeLabel + '</th><th>平今费率' + feeLabel + '</th><th>平昨费率' + feeLabel + '</th><th>活跃期</th><th>毛贡献</th><th>活跃期均值</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            var meanAct = row.mean_active_contribution;
            var fee = (row.product && row.product.fee) || {};
            var totalFee = (fee.total != null && isFinite(fee.total)) ? fee.total : 0;
            var highlight = (meanAct != null && isFinite(meanAct) && meanAct > totalFee) ? ' style="background:rgba(144,238,144,0.25)"' : '';
            html += '<tr' + highlight + '>' + renderProductFeeCells(row.product)
                + '<td>' + row.active_period_count + '</td><td>'
                + fmtPct(row.gross_contribution) + '</td><td>' + fmtFeeRate(meanAct) + '</td></tr>';
        });
        return html + '</tbody></table>';
    }

    function renderCalendarRows(rows, key) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>' + key + '</th><th>样本</th><th>累计</th><th>均值</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + row[key] + '</td><td>' + row.count + '</td><td>' + fmtPct(row.sum)
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

    function escapeHtml(value) { return GT.escapeHTML(value); }

    function fmtFeeRate(value) {
        if (value == null || isNaN(value) || !isFinite(value)) return '—';
        var bp = value * 10000;
        return bp.toFixed(5) + ' bp';
    }

    /** 检查行数据的 product.fee._is_real_fee，判断是否为原始费率而非回测参数 */
    function isRealFee(row) {
        return !!(row && row.product && row.product.fee && row.product.fee._is_real_fee);
    }

    function renderProductFeeCells(product) {
        if (!product || typeof product === 'string') {
            return '<td>' + (product || '—') + '</td><td style="max-width:120px;white-space:normal;word-break:break-all">—</td><td>—</td><td>—</td><td>—</td>';
        }
        var name = product.name || '—';
        var desc = product.desc && product.desc !== name ? product.desc : '—';
        var fee = product.fee || {};
        return '<td>' + name + '</td><td style="max-width:120px;white-space:normal;word-break:break-all">' + desc + '</td><td>' + fmtFeeRate(fee.open)
            + '</td><td>' + fmtFeeRate(fee.close_today) + '</td><td>' + fmtFeeRate(fee.close_yesterday != null ? fee.close_yesterday : fee.close) + '</td>';
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

    function renderGroupDetail(detail, options) {
        options = options || {};
        var summaryEl = document.getElementById('group-detail-summary');
        if (summaryEl) {
            summaryEl.innerHTML = renderGroupSummaryCards(detail.summary || {});
        }
        document.getElementById('group-detail-frequency').innerHTML = renderGroupFrequency(detail.entry_frequency, options.showDerivedPanel !== false);
        var derivedPanel = document.getElementById('group-derived-groups-panel');
        if (options.showDerivedPanel === false) {
            if (derivedPanel) derivedPanel.innerHTML = '';
        } else {
            renderDerivedGroupsPanel(_currentGroupDetailIndex == null ? 0 : _currentGroupDetailIndex);
        }
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
        renderProductAnalysis(detail.product_analysis || {});
        renderCalendarAnalysis(detail.calendar_analysis || {});
        renderHoldingAnalysis(detail.holding_analysis || {});
        renderTradabilityAnalysis(detail.tradability_analysis || {});
        renderRollingAnalysis(detail.rolling_analysis || {});
        renderCapacityAnalysis(detail.capacity_analysis || {});
        renderExplanations(detail.explanations || []);
        renderRobustnessSummary(detail.robustness_summary || {}, detail.period_robustness || {});
        renderGroupDetailReturnChart(detail.return_series || []);
        renderGroupDetailHistogram((detail.distribution || {}).histogram || []);
    }

    function buildPortfolioDetail(group, metric) {
        var timestamps = group.timestamps || [];
        var returns = group.gross_returns || [];
        if ((!returns || !returns.length) && group.cumulative_returns) {
            returns = [];
            var prev = 1.0;
            (group.cumulative_returns || []).forEach(function(value) {
                var cur = Number(value);
                if (!isFinite(cur) || prev === 0) {
                    returns.push(0);
                    return;
                }
                returns.push(cur / prev - 1.0);
                prev = cur;
            });
        }
        var wealth = 1.0;
        var returnSeries = returns.map(function(value, idx) {
            var ret = Number(value);
            if (!isFinite(ret)) ret = 0;
            wealth *= (1 + ret);
            return {
                timestamp: new Date(timestamps[idx]).toISOString(),
                return: ret,
                cumulative_return: wealth
            };
        });
        var periods = returnSeries.map(function(row) {
            return { timestamp: row.timestamp, return: row.return, products: [] };
        }).sort(function(a, b) { return b.return - a.return; });
        var cleanReturns = returns.map(Number).filter(function(v) { return isFinite(v); });
        var quantiles = {};
        if (cleanReturns.length) {
            var sorted = cleanReturns.slice().sort(function(a, b) { return a - b; });
            var qv = function(p) { return sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * p)))]; };
            quantiles = { p05: qv(0.05), p25: qv(0.25), p50: qv(0.50), p75: qv(0.75), p95: qv(0.95) };
        }
        var entryFrequency = [];
        if (group.derived && Array.isArray(group.derived.product_names)) {
            entryFrequency = group.derived.product_names.map(function(name) {
                return { product: { name: name, desc: name }, count: null, frequency: 0, mean_return: null };
            });
        } else if (group.derived && group.derived.config) {
            var config = group.derived.config;
            (config.long || []).forEach(function(leg) {
                entryFrequency.push({ product: { name: 'Long 第' + (leg.group + 1) + '组', desc: '权重 ' + leg.weight.toFixed(3) }, count: null, frequency: 0, mean_return: null });
            });
            (config.short || []).forEach(function(leg) {
                entryFrequency.push({ product: { name: 'Short 第' + (leg.group + 1) + '组', desc: '权重 ' + leg.weight.toFixed(3) }, count: null, frequency: 0, mean_return: null });
            });
        }
        return {
            summary: metric || {},
            entry_frequency: entryFrequency,
            top_periods: periods.slice(0, 10),
            bottom_periods: periods.slice(-10).reverse(),
            distribution: { histogram: [], quantiles: quantiles, period_count: cleanReturns.length },
            return_series: returnSeries,
            positive_run_analysis: {},
            intraday_analysis: {},
            daily_analysis: {},
            calendar_analysis: {},
            holding_analysis: {},
            capacity_analysis: {},
            rolling_analysis: {},
            tradability_analysis: {},
            period_robustness: {},
            robustness_summary: {},
            product_analysis: {},
            explanations: [],
        };
    }

    function renderGroupSummaryCards(summary) {
        function formatPct(pct) {
            if (pct == null || isNaN(pct) || !isFinite(pct)) return '—';
            var abs = Math.abs(pct);
            var dec;
            if (abs >= 10) dec = 2;
            else if (abs >= 1) dec = 3;
            else if (abs >= 0.1) dec = 4;
            else if (abs >= 0.01) dec = 5;
            else dec = 6;
            return pct.toFixed(dec) + '%';
        }
        var items = [
            ['Total Return', '总收益率'],
            ['Mean Return', '均值收益率'],
            ['Win Rate', '胜率'],
            ['Volatility', '年化波动率'],
            ['Max Drawdown', '最大回撤'],
            ['Avg Turnover', '平均换手率'],
        ];
        return items.map(function(item) {
            var key = item[0];
            var value = summary[key];
            var display = '—';
            if (value != null && !isNaN(value) && isFinite(value)) {
                display = formatPct(value);
            }
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
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

    function renderProductAnalysis(analysis) {
        var top = analysis.top_products || [];
        var bottom = analysis.bottom_products || [];
        var best = top[0];
        document.getElementById('group-detail-product-summary').textContent =
            best ? '哪些产品真正贡献了毛收益 · 最高 ' + formatGroupProduct(best.product) : '哪些产品真正贡献了毛收益';
        document.getElementById('group-detail-product-overview').textContent =
            '以下为已实现持仓下的毛收益贡献，不含手续费分摊。'
            + '最强 1 个产品贡献正毛收益的 ' + fmtPct(analysis.top1_positive_contribution_ratio)
            + '，最强 3 个产品贡献 ' + fmtPct(analysis.top3_positive_contribution_ratio)
            + (analysis.is_concentrated ? '。当前毛收益对少数产品较集中。' : '。');
        document.getElementById('group-detail-product-top').innerHTML = renderProductContributionRows(top);
        document.getElementById('group-detail-product-bottom').innerHTML = renderProductContributionRows(bottom);
    }

    function renderRobustnessSummary(summary, periodRobustness) {
        var top1 = periodRobustness.without_top1pct || {};
        var top5 = periodRobustness.without_top5pct || {};
        var issueLabels = {
            positive_runs: '少数连续正收益段',
            top_day: '单一交易日',
            top_periods: '头部时段',
            products: '少数产品',
            months: '少数月份',
            short_holding: '极短持有期',
            tiny_groups: '小样本组',
            unstable_windows: '滚动表现不稳',
        };
        var issues = (summary.issues || []).map(function(key) { return issueLabels[key] || key; });
        document.getElementById('group-detail-robustness-summary').textContent =
            summary.is_fragile ? '存在集中性风险' : '未见明显集中性风险';
        document.getElementById('group-detail-robustness-overview').textContent =
            '去掉最好 1% 时段后累计收益 ' + fmtPct(top1.remaining_return)
            + '；去掉最好 5% 时段后累计收益 ' + fmtPct(top5.remaining_return)
            + (issues.length ? '。当前主要风险来自：' + issues.join('、') + '。' : '。');
    }

    function renderCalendarAnalysis(analysis) {
        var topMonth = (analysis.month_rows || [])[0];
        document.getElementById('group-detail-calendar-summary').textContent =
            topMonth ? '按月、按月内日期、按年查看收益 · 最强月份 ' + topMonth.month : '按月、按月内日期、按年查看收益';
        document.getElementById('group-detail-calendar-month').innerHTML = renderCalendarRows(analysis.month_rows, 'month');
        document.getElementById('group-detail-calendar-day').innerHTML = renderCalendarRows(analysis.day_rows, 'day');
        document.getElementById('group-detail-calendar-year').innerHTML = renderCalendarRows(analysis.year_rows, 'year');
    }

    function renderHoldingAnalysis(analysis) {
        document.getElementById('group-detail-holding-summary').textContent =
            analysis.median_periods == null ? '组内成员通常停留多久' : '组内成员通常停留多久 · 中位数 ' + Number(analysis.median_periods).toFixed(1) + ' 期';
        var items = [
            ['run_count', '持有段数'],
            ['mean_periods', '平均持有期'],
            ['median_periods', '中位持有期'],
            ['p95_periods', 'P95 持有期'],
        ];
        document.getElementById('group-detail-holding').innerHTML = items.map(function(item) {
            var value = analysis[item[0]];
            var display = value == null ? '—' : Number(value).toFixed(item[0] === 'run_count' ? 0 : 2);
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
    }

    function renderExplanations(lines) {
        document.getElementById('group-detail-explanation-summary').textContent =
            lines && lines.length ? '系统归纳的主要风险 · ' + lines.length + ' 条' : '系统归纳的主要风险';
        document.getElementById('group-detail-explanations').innerHTML =
            lines && lines.length
                ? '<ul class="group-detail-explanation-list">' + lines.map(function(line) { return '<li>' + line + '</li>'; }).join('') + '</ul>'
                : '<div class="group-detail-muted">当前未识别到明显集中性风险。</div>';
    }

    function renderTradabilityAnalysis(analysis) {
        document.getElementById('group-detail-tradability-summary').textContent =
            analysis.break_even_fee == null
                ? '资金换手与成本承受力'
                : '资金换手与成本承受力 · break-even ' + fmtBp(analysis.break_even_fee);
        var items = [
            ['avg_trade_notional_ratio', '平均资金换手'],
            ['median_trade_notional_ratio', '中位资金换手'],
            ['avg_actual_fee_cost', '平均实际费率成本'],
            ['actual_fee_per_traded_notional', '成交额加权实际费率'],
            ['break_even_fee', 'Break-even 成本'],
        ];
        document.getElementById('group-detail-tradability-summary-grid').innerHTML = items.map(function(item) {
            var value = analysis[item[0]];
            var display = value == null ? '—' : (
                item[0] === 'break_even_fee' || item[0] === 'actual_fee_per_traded_notional'
                    ? fmtBp(value)
                    : fmtPct(value)
            );
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
        var rows = analysis.sensitivity || [];
        var html = '<table class="group-detail-table"><thead><tr><th>单边等比例成本</th><th>累计收益</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            html += '<tr><td>' + fmtBp(row.fee) + '</td><td>' + fmtPct(row.total_return) + '</td></tr>';
        });
        document.getElementById('group-detail-fee-sensitivity').innerHTML = rows.length ? html + '</tbody></table>' : '<div class="group-detail-muted">暂无数据</div>';
    }

    function renderRollingAnalysis(analysis) {
        var rows = analysis.rows || [];
        document.getElementById('group-detail-rolling-summary').textContent =
            analysis.window_size == null
                ? '不同时间窗口里是否持续有效'
                : '不同时间窗口里是否持续有效 · ' + analysis.window_size + ' 期窗口';
        var el = document.getElementById('group-detail-rolling-chart');
        if (!el || typeof Highcharts === 'undefined') return;
        var axis = buildContinuousTimeAxis(rows, function(row) { return row.timestamp; });
        Highcharts.chart(el, {
            chart: { backgroundColor: 'transparent', zoomType: 'x' },
            title: { text: null },
            xAxis: {
                labels: {
                    formatter: function() { return axis.labelAt(this.value); },
                },
            },
            yAxis: {
                title: { text: '窗口累计收益' },
                labels: { formatter: function() { return (this.value * 100).toFixed(2) + '%'; } },
            },
            tooltip: {
                formatter: function() {
                    return '<b>' + axis.labelAt(this.x) + '</b><br/>'
                        + this.series.name + ': ' + fmtPct(this.y);
                },
            },
            series: [{
                name: '滚动窗口收益',
                data: rows.map(function(row, idx) { return [idx, row.return]; }),
                color: '#0f4c81',
            }],
            credits: { enabled: false },
        });
    }

    function renderCapacityAnalysis(analysis) {
        document.getElementById('group-detail-capacity-summary').textContent =
            analysis.tiny_group_ratio == null ? '组内样本是否经常过小' : '组内样本是否经常过小 · 小样本期 ' + fmtPct(analysis.tiny_group_ratio);
        var items = [
            ['mean_count', '平均成员数'],
            ['median_count', '中位成员数'],
            ['min_count', '最少成员数'],
            ['empty_ratio', '空组占比'],
            ['tiny_group_ratio', '成员数 <= 2 占比'],
        ];
        document.getElementById('group-detail-capacity').innerHTML = items.map(function(item) {
            var value = analysis[item[0]];
            var display = value == null ? '—' : (
                item[0].indexOf('ratio') >= 0 ? fmtPct(value) : Number(value).toFixed(item[0] === 'min_count' ? 0 : 2)
            );
            return '<div class="group-detail-summary-item"><div class="group-detail-summary-label">'
                + item[1] + '</div><div class="group-detail-summary-value">' + display + '</div></div>';
        }).join('');
    }

    function fmtBp(value) {
        return value == null ? '—' : (value * 10000).toFixed(5) + ' bp';
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
        _currentGroupDetailIndex = groupIndex;
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

    function findGeneratedPortfolio(key) {
        if (!_lastGrossData) return null;
        return _lastGrossData.find(function(group) {
            if (!group) return false;
            if (group.key === key) return true;
            if (group.name === key) return true;
            if (group.derived && group.derived.key === key) return true;
            if (group.derived && group.derived.id === key) return true;
            return false;
        });
    }

    function openPortfolioDetail(key) {
        var group = findGeneratedPortfolio(key);
        if (!group) {
            alert('未找到该派生组/Long-Short 的已生成结果。');
            return;
        }
        var overlay = document.getElementById('group-detail-overlay');
        var loading = document.getElementById('group-detail-loading');
        var content = document.getElementById('group-detail-content');
        document.getElementById('group-detail-title').textContent = (group.name || key || '派生组') + '详情';
        overlay.classList.add('open');
        loading.style.display = 'none';
        content.style.display = '';
        renderGroupDetail(buildPortfolioDetail(group, (_lastMetrics || {})[key] || {}), { showDerivedPanel: false });
        var summary = document.getElementById('group-detail-frequency-summary');
        if (summary) summary.textContent = group.is_ls ? 'Long-Short 组合腿配置' : '派生组所选品种';
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
        var axis = buildContinuousTimeAxis(series, function(row) { return row.timestamp; });
        Highcharts.chart(el, {
            chart: { backgroundColor: 'transparent' },
            title: { text: null },
            xAxis: {
                labels: {
                    formatter: function() { return axis.labelAt(this.value); },
                },
            },
            yAxis: [{
                title: { text: '单期组差' },
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
                    return '<b>' + axis.labelAt(idx) + '</b><br/>'
                        + '单期 Top-Bottom: ' + fmtPct(row.spread) + '<br/>'
                        + '累计净值: ' + Number(row.cumulative_return).toFixed(4);
                },
            },
            series: [{
                name: '单期 Top-Bottom',
                type: 'column',
                data: series.map(function(row, idx) { return [idx, row.spread]; }),
                color: '#7c9fe6',
                tooltip: { valueSuffix: '' },
            }, {
                name: '累计净值',
                type: 'line',
                yAxis: 1,
                data: series.map(function(row, idx) { return [idx, row.cumulative_return]; }),
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

    function parseCsvNumbers(value) {
        return String(value || '').split(',')
            .map(function(x) { return parseFloat(x.trim()); })
            .filter(function(x) { return !isNaN(x) && isFinite(x); });
    }

    function buildLsLegs(groupsValue, weightsValue, defaultGroups) {
        var groups = parseCsvNumbers(groupsValue);
        if (!groups.length) groups = defaultGroups || [];
        var weights = parseCsvNumbers(weightsValue);
        if (!weights.length) weights = groups.map(function() { return 1; });
        return groups.map(function(groupNo, idx) {
            return {
                group: Math.max(0, Math.floor(groupNo) - 1),
                weight: weights[idx] != null ? weights[idx] : weights[weights.length - 1]
            };
        }).filter(function(leg) { return leg.weight > 0; });
    }

    function collectLongShortConfig(nGroups) {
        var def = (_longShortDefinitions && _longShortDefinitions[0]) || defaultLongShortDefinition();
        return buildLongShortPayload(def, nGroups);
    }

    function defaultLongShortDefinition() {
        return { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' };
    }

    function buildLongShortPayload(def, nGroups) {
        return {
            name: (def.name || '').trim() || 'Long-Short',
            long: buildLsLegs(def.longGroups || '1', def.longWeights || '1', [1]),
            short: buildLsLegs(def.shortGroups || '', def.shortWeights || '1', [nGroups])
        };
    }

    function collectLongShortConfigs(nGroups) {
        if (!_longShortDefinitions.length) _longShortDefinitions = [defaultLongShortDefinition()];
        return _longShortDefinitions.map(function(def) {
            return buildLongShortPayload(def, nGroups);
        });
    }

    function buildGroupStructureKey(submissionId, factorAlias, nGroups, startDate, endDate, returnFreqs) {
        return [
            String(submissionId || ''),
            String(factorAlias || ''),
            String(nGroups || ''),
            String(startDate || ''),
            String(endDate || ''),
            (returnFreqs || []).join(',')
        ].join('|');
    }

    function updateLongShortSummary() {
        var el = document.getElementById('long-short-summary');
        if (!el) return;
        if (!_longShortDefinitions.length) _longShortDefinitions = [defaultLongShortDefinition()];
        el.textContent = _longShortDefinitions.map(function(def) {
            return (def.name || 'Long-Short') + ': L(' + (def.longGroups || '1') + ') / S(' + (def.shortGroups || '末组') + ')';
        }).join('；');
    }

    function renderLongShortConfigList() {
        if (!_longShortDefinitions.length) _longShortDefinitions = [defaultLongShortDefinition()];
        var el = document.getElementById('long-short-config-list');
        if (!el) return;
        var html = '';
        _longShortDefinitions.forEach(function(def) {
            html += '<div class="long-short-config-row" data-ls-id="' + escapeHtml(def.id) + '">'
                + '<input data-field="name" value="' + escapeHtml(def.name || '') + '" placeholder="组合名称">'
                + '<input data-field="longGroups" value="' + escapeHtml(def.longGroups || '') + '" placeholder="Long组">'
                + '<input data-field="longWeights" value="' + escapeHtml(def.longWeights || '') + '" placeholder="Long权重">'
                + '<input data-field="shortGroups" value="' + escapeHtml(def.shortGroups || '') + '" placeholder="Short组">'
                + '<input data-field="shortWeights" value="' + escapeHtml(def.shortWeights || '') + '" placeholder="Short权重">'
                + '<button type="button" class="btn btn-outline-danger btn-sm long-short-delete-btn" data-ls-id="' + escapeHtml(def.id) + '">删除</button>'
                + '</div>';
        });
        el.innerHTML = html;
        el.querySelectorAll('input[data-field]').forEach(function(input) {
            input.addEventListener('input', function() {
                var row = input.closest('.long-short-config-row');
                var def = _longShortDefinitions.find(function(item) { return item.id === row.getAttribute('data-ls-id'); });
                if (def) {
                    def[input.getAttribute('data-field')] = input.value;
                    updateLongShortSummary();
                }
            });
        });
        el.querySelectorAll('.long-short-delete-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                _longShortDefinitions = _longShortDefinitions.filter(function(item) { return item.id !== btn.getAttribute('data-ls-id'); });
                if (!_longShortDefinitions.length) _longShortDefinitions = [defaultLongShortDefinition()];
                renderLongShortConfigList();
                updateLongShortSummary();
            });
        });
    }

    async function collectGroupRunPayload(context, factorAlias) {
        var statusSpan = document.getElementById('group_test_status');
        var currentSubmissionId = context && context.submission_id;
        if (!currentSubmissionId || !factorAlias) {
            return { error: '请先选择测试器和因子' };
        }

        // P7: Read params from datamodel if available, else fallback to DOM
        var n_groups = 5;
        var rebalance_mode = 'buy_and_hold';
        var start_date = null;
        var end_date = null;

        // Try datamodel first
        if (GT.datamodel && GT.datamodel.groups) {
            var allBase = GT.datamodel.groups.getAll();
            if (allBase && allBase.length > 0) {
                var bg = allBase[0];
                n_groups = bg.groupCount || 5;
                rebalance_mode = bg.rebalanceMode || 'buy_and_hold';
                start_date = bg.startDate || null;
                end_date = bg.endDate || null;
            }
        }

        // Fallback: read from DOM (old inputs)
        if (!start_date) {
            var gcEl = document.getElementById('group_count');
            if (gcEl) n_groups = parseInt(gcEl.value, 10) || 5;
            var rmEl = document.getElementById('rebalance_mode');
            if (rmEl) rebalance_mode = rmEl.value || 'buy_and_hold';
        }

        var use_closetoday = GT.fee ? GT.fee.useCloseToday() : false;

        // ── 费率聚合：遍历所有 base group 决定 fee + fee_map ──
        var fee = 0;
        var fee_map = {};
        var hasPerProduct = false;
        if (GT.datamodel && GT.datamodel.groups) {
            var allFeeGroups = GT.datamodel.groups.getAll() || [];
            for (var fgi = 0; fgi < allFeeGroups.length; fgi++) {
                var fg = allFeeGroups[fgi];
                if (fg.isDerived) continue;
                if (fg.feeMode === 'per_product') hasPerProduct = true;
                // 统一费率取第一个 effective group 的值
                if (fg.feeMode === 'uniform' && fee === 0) {
                    fee = fg.feeRate != null ? fg.feeRate : 0.0025;
                }
            }
        }
        if (hasPerProduct && GT.fee) {
            try {
                fee_map = await GT.fee.ensureFeeData();
            } catch (err) {
                console.error('[collectGroupRunPayload] ensureFeeData failed:', err);
            }
        }

        // Read time range from layer-1 inputs or fallback
        if (!start_date) {
            var sy = document.getElementById('group_start_year') ? document.getElementById('group_start_year').value : null;
            var sm = document.getElementById('group_start_month') ? document.getElementById('group_start_month').value : null;
            var sd = document.getElementById('group_start_day') ? document.getElementById('group_start_day').value : null;
            if (sy && sm && sd) start_date = buildValidDate(sy, sm, sd);
        }
        if (!end_date) {
            var ey = document.getElementById('group_end_year') ? document.getElementById('group_end_year').value : null;
            var em = document.getElementById('group_end_month') ? document.getElementById('group_end_month').value : null;
            var ed = document.getElementById('group_end_day') ? document.getElementById('group_end_day').value : null;
            if (ey && em && ed) end_date = buildValidDate(ey, em, ed);
        }

        // Fallback: read from time module
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

        // Fallback: use submission dates
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
        var derivedPayload = _derivedGroups.map(function(d) {
            return {
                id: d.id,
                name: d.name || d.label,
                baseGroup: d.baseGroup,
                productNames: d.productNames
            };
        });

        // ── 构造 group_fee_maps：每个 base group 的独立品种费率覆盖 ──
        var group_fee_maps = null;
        if (GT.datamodel && GT.datamodel.groups) {
            var allGroups = GT.datamodel.groups.getAll() || [];
            var gfmObj = {};
            for (var gi = 0; gi < allGroups.length; gi++) {
                var grp = allGroups[gi];
                if (grp.isDerived) continue;
                if (grp.feeMode === 'per_product' && grp.feeMap && typeof grp.feeMap === 'object') {
                    var gIdx = Number(grp.groupIndex || 1) - 1; // 1-based → 0-based
                    var gfm = {};
                    Object.keys(grp.feeMap).forEach(function(code) {
                        var ov = grp.feeMap[code];
                        if (ov && typeof ov === 'object') {
                            gfm[code.toLowerCase()] = {
                                open: ov.open_ratio != null ? ov.open_ratio : null,
                                close: ov.close_ratio != null ? ov.close_ratio : null,
                                close_today: ov.closetoday_ratio != null ? ov.closetoday_ratio : null
                            };
                        }
                    });
                    if (Object.keys(gfm).length > 0) {
                        gfmObj[gIdx] = gfm;
                    }
                }
            }
            if (Object.keys(gfmObj).length > 0) group_fee_maps = gfmObj;
        }

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
                rebalance_mode: rebalance_mode,
                ls_config: collectLongShortConfig(n_groups),
                ls_configs: collectLongShortConfigs(n_groups),
                derived_groups: derivedPayload.length > 0 ? derivedPayload : null,
                group_fee_maps: group_fee_maps,
                structure_key: buildGroupStructureKey(currentSubmissionId, factorAlias, n_groups, start_date, end_date, return_freqs)
            },
            statusEl: statusSpan,
        };
    }

    function applyGroupTestResult(data, statusText) {
        // DEBUG: log response identity to verify tester switching
        console.log('[GroupTest] applyGroupTestResult:', {
            submission_id: data.submission_id,
            factor_alias: data.factor_alias,
            tester_alias: data.tester_alias,
            tester_product_count: data.tester_product_count,
            n_groups: data.n_groups,
            multi_horizon: data.multi_horizon,
        });

        if (data.multi_horizon) {
            updateStrategyPanel(data.multi_session_active, data.rebalance_mode);
            var chartContainer = document.getElementById('group_chart_container');
            var metricsContainer = document.getElementById('group_metrics_container');
            if (chartContainer) chartContainer.style.display = 'none';
            if (metricsContainer) metricsContainer.style.display = 'none';
            closeSnapshotDrawer();
            _lastGrossData = null;
            _lastMetrics = null;
            _derivedGroups = [];
            _derivedGroupSeq = 1;
            _lastGroupStructureKey = data.structure_key || null;
            renderMultiHorizonTable(data.results, data.n_groups);
            return;
        }

        updateStrategyPanel(data.multi_session_active, data.rebalance_mode);
        _lastGrossData = data.groups;
        _lastMetrics = data.metrics;
        _lastNgroups = data.n_groups;
        _lastTimestamps = data.groups.length > 0 ? data.groups[0].timestamps : [];
        _lastGroupStructureKey = data.structure_key || null;

        // metrics key 即为 shortAlias，无需额外映射表

        // 从响应中重建 _derivedGroups（后端已统一计算，无需额外请求）
        // 注意：跳过 LS 组（is_ls），其 derived 中无 base_group。
        _derivedGroups = [];
        _derivedGroupSeq = 1;
        (data.groups || []).forEach(function(g) {
            if (g.is_derived && g.derived && !g.is_ls) {
                _derivedGroups.push({
                    id: g.derived.id || ('D' + _derivedGroupSeq),
                    name: g.name,
                    baseGroup: g.derived.base_group,
                    productNames: g.derived.product_names || [],
                    key: g.key,
                    generated: true
                });
                var num = parseInt(String(g.derived.id || '').replace(/^D/, ''), 10);
                if (!isNaN(num)) _derivedGroupSeq = Math.max(_derivedGroupSeq, num + 1);
            }
        });

        // 画图 + 指标表
        drawGroupChart(data.groups);
        renderMetricsTable(data.metrics);

        var slider = document.getElementById('fee_sensitivity_slider');
        if (slider) { slider.value = 0; updateSensitivityLabel(0); }
    }

    /** 批量重新生成全部精选组 + LS 组，所有请求完成后统一刷新图表一次。
     *  通过 _derivedGeneration 废弃旧调用：如果 applyGroupTestResult 被再次触发，
     *  旧的 refreshAllDerivedGroups 会在 drawGroupChart 前检查 generation 并静默退出。 */
    async function refreshAllDerivedGroups(generation) {
        var tasks = _derivedGroups.map(function(def) {
            if (!def.id) return Promise.resolve();
            return regenerateDerivedGroupQuiet(def, generation);
        });
        if (typeof buildLongShortGroups === 'function') {
            tasks.push(Promise.resolve().then(function() {
                try { buildLongShortGroups(); } catch(e) {}
            }));
        }
        /* global buildLongShortGroups */
        await Promise.all(tasks);
        if (generation !== _derivedGeneration) return; // 已被更新的批次废弃
        drawGroupChart(_lastGrossData);
        renderMetricsTable(_lastMetrics);
    }

    /** 静默重新生成一个精选组（不发网络请求，只更新数据）—— 实际需要发请求，但不画图。
     *  generation 用于废弃过期请求：如果 await 期间 applyGroupTestResult 被再次触发，
     *  该请求的结果不再 push 到 _lastGrossData。 */
    async function regenerateDerivedGroupQuiet(def, generation) {
        var context = getCurrentContext();
        if (!def || !context || !context.submission_id) return;
        if (!_lastGrossData || !_lastMetrics) return;
        if (def.baseGroup == null) return;

        // 从所有 base group 找对应 baseGroup (0-based index) 的费率配置
        var fee = 0;
        var fee_map = {};
        if (GT.datamodel && GT.datamodel.groups) {
            var allFeeGroups = GT.datamodel.groups.getAll() || [];
            for (var fgi = 0; fgi < allFeeGroups.length; fgi++) {
                var fg = allFeeGroups[fgi];
                if (fg.isDerived) continue;
                var gIdx = Number(fg.groupIndex || 1) - 1;
                if (gIdx === def.baseGroup) {
                    if (fg.feeMode === 'uniform') {
                        fee = fg.feeRate != null ? fg.feeRate : 0.0025;
                    } else if (fg.feeMode === 'per_product') {
                        try {
                            fee_map = await GT.fee.ensureFeeData();
                        } catch (err) {
                            console.error('[regenerateDerivedGroupQuiet] ensureFeeData failed:', err);
                        }
                    }
                    break;
                }
            }
        }

        var resp = await GT.api.createDerivedGroup({
            submission_id: context.submission_id,
            group_index: def.baseGroup,
            product_names: def.productNames,
            name: def.name,
            use_closetoday: GT.fee ? GT.fee.useCloseToday() : false,
            fee: fee,
            fee_map: fee_map
        });
        if (generation !== _derivedGeneration) return; // 已被更新的批次废弃
        if (!resp || !resp.success) return;

        removeGeneratedDerivedArtifacts(def.id);
        def.key = makeUniqueGroupKey(def.name, def.id);
        def.generated = true;
        var group = resp.group || {};
        group.name = def.name;
        group.is_derived = true;
        group.derived = Object.assign({}, group.derived || {}, { id: def.id, key: def.key });
        _lastGrossData.push(group);
        _lastMetrics[def.key] = resp.metric || {};
    }

    function postGroupTest(payload) {
        return fetch('/run_group_test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function(res) { return res.json(); });
    }

    /** 批量分组测试（单次 POST，后端并行计算） */
    function postBatchGroupTest(payload) {
        return fetch('/run_group_test_batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function(res) { return res.json(); });
    }

    // ---------- 加载默认分组 ----------
    async function loadDefaultGroups() {
        var statusSpan = document.getElementById('group_test_status');
        var runBtn = document.getElementById('run_group_test_btn');
        var defaultBtn = document.getElementById('load_default_groups_btn');

        var submissions = window.submissions || [];
        var factorList = window.factorList || [];

        if (!submissions.length) {
            alert('暂无测试器，请先在产品类别筛选模块提交产品');
            return;
        }
        if (!factorList.length) {
            alert('暂无可用的因子列表，请先在 IC 测试模块运行 IC 测试');
            return;
        }

        if (!GT.datamodel || !GT.datamodel.groups || !GT.datamodel.ls_configs) {
            alert('数据模型未就绪，请刷新页面');
            return;
        }

        var groups = GT.datamodel.groups;
        var lsConfigs = GT.datamodel.ls_configs;

        // Count existing groups
        var existingBase = (groups.getAll() || []).filter(function(g) { return !g.isDerived; });
        var existingLS = lsConfigs.getAll() || [];

        if (existingBase.length > 0 || existingLS.length > 0) {
            var confirmMsg = '当前已有 ' + existingBase.length + ' 个基础组和 ' + existingLS.length + ' 个 LS 组。\n';
            confirmMsg += '加载默认分组将清空所有现有分组，确定继续？';
            if (!confirm(confirmMsg)) return;
        }

        // Clear all existing groups and LS configs
        (groups.getAll() || []).forEach(function(g) { groups.remove(g.id); });
        (lsConfigs.getAll() || []).forEach(function(ls) { lsConfigs.remove(ls.id); });

        if (defaultBtn) defaultBtn.disabled = true;
        if (runBtn) runBtn.disabled = true;
        if (statusSpan) {
            statusSpan.innerHTML = '正在加载默认分组...';
            statusSpan.style.color = '#0078d4';
        }

        var GROUPS_PER_FACTOR = 5;
        var totalCreated = 0;

        // Track batchKey → letter so same (testerId, factorAlias, groupCount) gets same letter
        var batchLetterMap = {};
        var nextLetterCode = 65; // A

        try {
            for (var si = 0; si < submissions.length; si++) {
                var sub = submissions[si];
                var testerId = String(sub.id);
                for (var fi = 0; fi < factorList.length; fi++) {
                    var factor = factorList[fi];
                    var factorAlias = factor.alias || factor.name || '';

                    // Batch key: (testerId, factorAlias, groupCount) — same key → same letter prefix
                    var bk = GT.datamodel.groups.batchKey(testerId, factorAlias, GROUPS_PER_FACTOR);
                    var letter = batchLetterMap[bk];
                    if (!letter) {
                        letter = String.fromCharCode(nextLetterCode);
                        nextLetterCode++;
                        batchLetterMap[bk] = letter;
                    }

                    // Create 5 base groups (groupIndex 1-5) for this factor
                    var createdIds = [];
                    for (var gi = 1; gi <= GROUPS_PER_FACTOR; gi++) {
                        try {
                            var id = groups.add({
                                name: factorAlias + ' · G' + gi + ' (' + (sub.product_group || sub.label || testerId) + ')',
                                testerId: testerId,
                                factorAlias: factorAlias,
                                groupCount: GROUPS_PER_FACTOR,
                                groupIndex: gi,
                                isAllGroups: false,
                                shortAlias: letter + gi,
                                feeMode: 'none',
                                useCloseToday: false,
                                rebalanceMode: 'each_period'
                            });
                            createdIds.push({ id: id, index: gi });
                        } catch (e) {
                            console.error('创建分组失败 (' + factorAlias + ' G' + gi + '):', e);
                        }
                    }

                    // Create LS: group 1 (long) vs group 5 (short)
                    if (createdIds.length >= 5) {
                        var longItem = createdIds[0];   // groupIndex 1
                        var shortItem = createdIds[4];  // groupIndex 5
                        try {
                            lsConfigs.add({
                                name: factorAlias + ' · 多空',
                                longGroupId: longItem.id,
                                shortGroupId: shortItem.id
                            });
                        } catch (e) {
                            console.error('创建 LS 组失败 (' + factorAlias + '):', e);
                        }
                    }

                    totalCreated++;
                    if (statusSpan) {
                        statusSpan.innerHTML = '加载中... ' + totalCreated + ' 个因子分组';
                    }
                }
            }

            if (statusSpan) {
                var totalBase = (groups.getAll() || []).filter(function(g) { return !g.isDerived; }).length;
                var totalLS = (lsConfigs.getAll() || []).length;
                statusSpan.innerHTML = '✓ 已加载 ' + totalBase + ' 个基础组 + ' + totalLS + ' 个 LS 组';
                statusSpan.style.color = '#28a745';
            }

            // Refresh the panel
            if (GT.ui && GT.ui.mountTab) {
                GT.ui.mountTab('list');
            }
        } catch (e) {
            console.error('加载默认分组失败:', e);
            if (statusSpan) {
                statusSpan.innerHTML = '✗ 加载失败: ' + (e.message || '未知错误');
                statusSpan.style.color = '#d40000';
            }
        } finally {
            if (defaultBtn) defaultBtn.disabled = false;
            if (runBtn) runBtn.disabled = false;
        }
    }

    // ---------- 运行分组测试（批量：所有batch+LS组一起算） ----------
    async function runGroupTest() {
        var statusSpan = document.getElementById('group_test_status');
        var runBtn = document.getElementById('run_group_test_btn');
        var defaultBtn = document.getElementById('load_default_groups_btn');

        var REG = window.GT_CONFIG_REGISTRY;
        if (REG && typeof REG.hasDirty === 'function' && REG.hasDirty() && typeof REG.commitDirty === 'function') {
            REG.commitDirty();
        }

        // ── 0. 没有分组则自动加载默认分组 ──
        var allBase = (GT.datamodel && GT.datamodel.groups && GT.datamodel.groups.getAll()) || [];
        var nonDerived = allBase.filter(function(g) { return !g.isDerived; });
        if (nonDerived.length === 0) {
            if (statusSpan) {
                statusSpan.innerHTML = '⏳ 无现有分组，正在加载默认分组...';
                statusSpan.style.color = '#0078d4';
            }
            await loadDefaultGroups();
            // 再次检查
            allBase = (GT.datamodel && GT.datamodel.groups && GT.datamodel.groups.getAll()) || [];
            nonDerived = allBase.filter(function(g) { return !g.isDerived; });
            if (nonDerived.length === 0) {
                if (statusSpan) {
                    statusSpan.innerHTML = '✗ 无法加载默认分组';
                    statusSpan.style.color = '#d40000';
                }
                return;
            }
        }

        // ── 1. 按 batchKey 分组 ──
        var batchKeyFn = GT.datamodel.groups.batchKey;
        var batchMap = {};
        for (var i = 0; i < nonDerived.length; i++) {
            var g = nonDerived[i];
            var bk = batchKeyFn(g.testerId, g.factorAlias, g.groupCount);
            if (!batchMap[bk]) {
                batchMap[bk] = {
                    key: bk,
                    testerId: g.testerId,
                    factorAlias: g.factorAlias,
                    groupCount: g.groupCount,
                    groups: []
                };
            }
            batchMap[bk].groups.push(g);
        }
        var batches = [];
        var bkKeys = Object.keys(batchMap);
        // sort by shortAlias
        bkKeys.sort(function(a, b) {
            var sa = (batchMap[a].groups[0].shortAlias || '');
            var sb = (batchMap[b].groups[0].shortAlias || '');
            if (sa < sb) return -1;
            if (sa > sb) return 1;
            return 0;
        });
        for (var k = 0; k < bkKeys.length; k++) { batches.push(batchMap[bkKeys[k]]); }

        // ── 2. 收集 LS configs，按归属分派 ──
        var allLS = (GT.datamodel && GT.datamodel.ls_configs && GT.datamodel.ls_configs.getAll()) || [];
        // 为每个 batch 建立 groupId → groupIndex 映射
        for (var bi = 0; bi < batches.length; bi++) {
            var b = batches[bi];
            b.groupIdToIndex = {};
            var groupsByIndex = {};
            for (var gi = 0; gi < b.groups.length; gi++) {
                var originalIndex = Number(b.groups[gi].groupIndex || (gi + 1));
                if (!groupsByIndex[originalIndex]) groupsByIndex[originalIndex] = [];
                groupsByIndex[originalIndex].push(b.groups[gi]);
            }
            var expandedIndex = 1;
            for (var baseIdx = 1; baseIdx <= Number(b.groupCount || b.groups.length || 0); baseIdx++) {
                var variantsAtIndex = groupsByIndex[baseIdx] || [];
                for (var vi = 0; vi < variantsAtIndex.length; vi++) {
                    b.groupIdToIndex[variantsAtIndex[vi].id] = expandedIndex;
                    expandedIndex += 1;
                }
            }
            b.derivedPayload = collectDerivedPayloadForBatch(b);
            for (var di = 0; di < b.derivedPayload.length; di++) {
                if (b.derivedPayload[di].id) {
                    b.groupIdToIndex[b.derivedPayload[di].id] = expandedIndex;
                    expandedIndex += 1;
                }
            }
            b.lsPayloads = []; // LS configs that belong to this batch
        }
        var crossBatchLS = []; // LS configs spanning multiple batches

        for (var li = 0; li < allLS.length; li++) {
            var ls = allLS[li];
            var longBatch = null, shortBatch = null;
            for (var bj = 0; bj < batches.length; bj++) {
                if (batches[bj].groupIdToIndex[ls.longGroupId] !== undefined) longBatch = batches[bj];
                if (batches[bj].groupIdToIndex[ls.shortGroupId] !== undefined) shortBatch = batches[bj];
            }
            if (!longBatch || !shortBatch) {
                console.warn('[runGroupTest] LS config ' + ls.id + ' references unknown group(s): long=' + ls.longGroupId + ' short=' + ls.shortGroupId);
                continue;
            }
            if (longBatch === shortBatch) {
                // Same batch: build LS payload from groupIndex
                var longIdx = longBatch.groupIdToIndex[ls.longGroupId];
                var shortIdx = shortBatch.groupIdToIndex[ls.shortGroupId];
                var sameBatchName = lsDisplayName(ls);
                longBatch.lsPayloads.push({
                    name: sameBatchName,
                    key: sameBatchName,
                    long: [{ group: longIdx - 1, weight: 1.0 }],
                    short: [{ group: shortIdx - 1, weight: 1.0 }]
                });
            } else {
                crossBatchLS.push(ls);
            }
        }

        // ── 3. 构建批量 payload，单次 POST ──
        if (runBtn) runBtn.disabled = true;

        var multiHorizonContainer = document.getElementById('multi_horizon_container');
        if (multiHorizonContainer) multiHorizonContainer.style.display = 'none';

        var totalBatches = batches.length + (crossBatchLS.length > 0 ? 1 : 0);

        // 从第一个 batch 取 param 值（fee、时间等）
        var firstGroup = batches[0] && batches[0].groups[0];
        var rebalance_mode = firstGroup ? (firstGroup.rebalanceMode || 'buy_and_hold') : 'buy_and_hold';
        var start_date = firstGroup ? (firstGroup.startDate || null) : null;
        var end_date = firstGroup ? (firstGroup.endDate || null) : null;

        // 读取时间范围 fallback
        if (!start_date || !end_date) {
            var ctx = getCurrentContext();
            var sub = ctx ? ctx.submission : null;
            if (!sub && window.submissions) {
                var firstTesterId = batches[0] && batches[0].testerId;
                sub = window.submissions.find(function(s) { return String(s.id) === String(firstTesterId); });
            }
            if (!start_date) start_date = sub ? sub.start_date : null;
            if (!end_date) end_date = sub ? sub.end_date : null;
        }
        // More fallbacks from DOM
        if (!start_date || !end_date) {
            var sy = document.getElementById('group_start_year') ? document.getElementById('group_start_year').value : null;
            var sm = document.getElementById('group_start_month') ? document.getElementById('group_start_month').value : null;
            var sd = document.getElementById('group_start_day') ? document.getElementById('group_start_day').value : null;
            if (sy && sm && sd) start_date = buildValidDate(sy, sm, sd);
            var ey = document.getElementById('group_end_year') ? document.getElementById('group_end_year').value : null;
            var em = document.getElementById('group_end_month') ? document.getElementById('group_end_month').value : null;
            var ed = document.getElementById('group_end_day') ? document.getElementById('group_end_day').value : null;
            if (ey && em && ed) end_date = buildValidDate(ey, em, ed);
        }

        if (!start_date || !end_date) {
            if (statusSpan) { statusSpan.innerHTML = '✗ 请设置时间范围'; statusSpan.style.color = '#d40000'; }
            if (runBtn) runBtn.disabled = false;
            return;
        }
        if (start_date > end_date) {
            if (statusSpan) { statusSpan.innerHTML = '✗ 起始日期不能晚于终止日期'; statusSpan.style.color = '#d40000'; }
            if (runBtn) runBtn.disabled = false;
            return;
        }

        // ── 批量费率聚合：遍历所有 base group ──
        var fee = 0;
        var fee_map = {};
        var hasPerProduct = false;
        if (GT.datamodel && GT.datamodel.groups) {
            var allFeeGroups = GT.datamodel.groups.getAll() || [];
            for (var fgi = 0; fgi < allFeeGroups.length; fgi++) {
                var fg = allFeeGroups[fgi];
                if (fg.isDerived) continue;
                if (fg.feeMode === 'per_product') hasPerProduct = true;
                if (fg.feeMode === 'uniform' && fee === 0) {
                    fee = fg.feeRate != null ? fg.feeRate : 0.0025;
                }
            }
        }
        if (hasPerProduct && GT.fee) {
            try {
                fee_map = await GT.fee.ensureFeeData();
            } catch (err) {
                console.error('[runBatch] ensureFeeData failed:', err);
            }
        }
        var use_closetoday = GT.fee ? GT.fee.useCloseToday() : false;
        var return_freqs = getSelectedReturnFreqs();

        if (statusSpan) {
            statusSpan.innerHTML = '分组测试运行中...（共 ' + totalBatches + ' 批次）';
            statusSpan.style.color = '#0078d4';
        }

        // 构建批量 request payload
        var batchPayloads = [];
        for (var bi = 0; bi < batches.length; bi++) {
            var batch = batches[bi];
            // group_names: {0: [{name, fee_mode, ...}, ...], ...}
            // 同一个 groupIndex 可以对应多个 variant（不同费率策略/名称），后端一次性扩展计算。
            var groupNames = {};
            for (var gi = 0; gi < batch.groups.length; gi++) {
                var g = batch.groups[gi];
                var groupIdx = (g.groupIndex || (gi + 1)) - 1; // groupIndex 是 1-based，转为 0-based
                var variant = serializeGroupVariant(g, 'Group ' + (groupIdx + 1));
                if (!variant) continue;
                if (!groupNames[groupIdx]) groupNames[groupIdx] = [];
                groupNames[groupIdx].push(variant);
            }
            var derivedPayload = batch.derivedPayload || [];
            batchPayloads.push({
                submission_id: batch.testerId,
                factor_alias: batch.factorAlias,
                n_groups: batch.groupCount,
                group_names: Object.keys(groupNames).length > 0 ? groupNames : null,
                ls_configs: batch.lsPayloads.length > 0 ? batch.lsPayloads : null,
                derived_groups: derivedPayload.length > 0 ? derivedPayload : null
            });
        }

        // 构建跨 batch LS payload
        var crossBatchLSPayloads = [];
        for (var ci = 0; ci < crossBatchLS.length; ci++) {
            var cbLS = crossBatchLS[ci];
            var cblLongBatch = null, cblShortBatch = null;
            for (var bj = 0; bj < batches.length; bj++) {
                if (batches[bj].groupIdToIndex[cbLS.longGroupId] !== undefined) cblLongBatch = batches[bj];
                if (batches[bj].groupIdToIndex[cbLS.shortGroupId] !== undefined) cblShortBatch = batches[bj];
            }
            if (!cblLongBatch || !cblShortBatch) continue;

            var cblLongIdx = cblLongBatch.groupIdToIndex[cbLS.longGroupId] - 1; // 0-based
            var cblShortIdx = cblShortBatch.groupIdToIndex[cbLS.shortGroupId] - 1;
            var crossBatchName = lsDisplayName(cbLS);

            crossBatchLSPayloads.push({
                name: crossBatchName,
                key: crossBatchName,
                long: {
                    submission_id: cblLongBatch.testerId,
                    factor_alias: cblLongBatch.factorAlias,
                    group: cblLongIdx
                },
                short: {
                    submission_id: cblShortBatch.testerId,
                    factor_alias: cblShortBatch.factorAlias,
                    group: cblShortIdx
                }
            });
        }

        var bulkPayload = {
            batches: batchPayloads,
            cross_batch_ls: crossBatchLSPayloads.length > 0 ? crossBatchLSPayloads : null,
            fee: fee,
            fee_map: fee_map,
            group_fee_maps: null,
            use_closetoday: use_closetoday,
            start_date: start_date,
            end_date: end_date,
            return_freqs: return_freqs.length > 0 ? return_freqs : null,
            rebalance_mode: rebalance_mode
        };

        try {
            // ── 进度条：indeterminate 条形动画 ──
            var progressBarId = 'gt-batch-progress';
            var progressBar = document.getElementById(progressBarId);
            if (!progressBar) {
                progressBar = document.createElement('div');
                progressBar.id = progressBarId;
                progressBar.className = 'gt-progress-container';
                progressBar.innerHTML = '<div class="gt-progress-bar"><div class="gt-progress-indeterminate"></div></div>' +
                                        '<span class="gt-progress-text">计算中...</span>';
                var chartContainer = document.getElementById('group_chart_container');
                var insertParent = chartContainer ? chartContainer.parentNode : runBtn.parentNode;
                var insertBefore = chartContainer || runBtn.nextSibling;
                insertParent.insertBefore(progressBar, insertBefore);
            }

            var data = await postBatchGroupTest(bulkPayload);
            if (!data.success) {
                var errorText = data.needs_ic_test && pageHasICModule()
                    ? '当前测试器还没有 IC 测试结果。请先在 IC 测试模块运行一次 IC 测试。'
                    : data.error;
                if (statusSpan) {
                    statusSpan.innerHTML = '✗ 分组测试失败: ' + errorText;
                    statusSpan.style.color = '#d40000';
                }
                if (data.batch_errors) {
                    console.error('[runGroupTest] batch errors:', data.batch_errors);
                }
                return;
            }

            // 标记所有 batch 为 done
            for (var bi = 0; bi < batches.length; bi++) {
                var btch = batches[bi];
                cacheGroupResult(btch.testerId, btch.factorAlias, data);
                markGroupFactorStatus(btch.testerId, btch.factorAlias, 'done');
            }

            // ── 数据已就绪：后端统一用 key 字段 + metrics key = shortAlias ──
            // data.groups[i].key = "A1"/"B1"/... , data.metrics["A1"] = {...}
            // 无需前端注入，直接渲染

            // 一次性渲染
            applyGroupTestResult(data);

            if (statusSpan) {
                var doneMsg = '✓ ' + data.batch_count + ' 批次完成';
                if (data.cross_batch_ls_count) {
                    doneMsg += '（含 ' + data.cross_batch_ls_count + ' 跨 Batch LS）';
                }
                statusSpan.innerHTML = doneMsg;
                statusSpan.style.color = '#28a745';
            }
        } catch (e) {
            console.error('[runGroupTest] error:', e);
            if (statusSpan) {
                statusSpan.innerHTML = '✗ ' + (e.message || '未知错误');
                statusSpan.style.color = '#d40000';
            }
        } finally {
            // 清理进度条
            var _pb = document.getElementById('gt-batch-progress');
            if (_pb) _pb.remove();
            if (runBtn) {
                runBtn.disabled = false;
                runBtn.style.display = '';  // 恢复可能被 renderGroupTabs 隐藏的按钮
            }
        }
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
        if (runBtn) runBtn.disabled = true;
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
    var _derivedGroups = [];
    var _derivedGroupSeq = 1;
    var _derivedGeneration = 0;      // 每次 run_group_test 递增，废弃旧的 refreshAllDerivedGroups
    var _currentGroupDetailIndex = null;
    var _longShortDefinitions = [defaultLongShortDefinition()];
    var _lastGroupStructureKey = null;

    // ═══ Panel registry — unified flat tab list ═══
    // Each entry: { name, label, containerId, category, panel, addFlow }
    // - category: LIST (list view), CONFIG (settings), ADD (create flow)
    // - addFlow: 'base' | 'derived' | 'ls' — which add button invokes this panel
    // Populated lazily after all panel scripts have loaded.

    // Tab category constants — used for mode-based visibility filtering.
    var GT_TAB_CATEGORY = {
        LIST: 1,    // list views
        ADD: 2,     // add-flow panels (tester + factor selection)
        CONFIG: 3,  // config panels (fee, rebalance)
    };

    var GT_PANEL_REGISTRY = [];

    /** Call this after all panel scripts loaded to register panels. */
    var _panelsRegistered = false;

    function _registerPanels() {
        if (_panelsRegistered) return;
        var P = GT.panels;
        if (!P) return;

        // Unified list — shows base, derived, and LS groups together (category-1)
        if (P.list && P.list.index) {
            GT_PANEL_REGISTRY.push({ name: 'list', label: '📊 分组列表', containerId: 'unified-group-list', category: GT_TAB_CATEGORY.LIST, panel: P.list.index });
        }

        // Add-flow panels (category-2)
        if (P.add && P.add.base) {
            GT_PANEL_REGISTRY.push({ name: 'add-base', label: '新建基础组', containerId: 'add-base', category: GT_TAB_CATEGORY.ADD, panel: P.add.base, addFlow: 'base' });
        }
        if (P.add && P.add.derived) {
            GT_PANEL_REGISTRY.push({ name: 'add-derived', label: '新建派生组', containerId: 'add-derived', category: GT_TAB_CATEGORY.ADD, panel: P.add.derived, addFlow: 'derived' });
        }
        if (P.add && P.add.ls) {
            GT_PANEL_REGISTRY.push({ name: 'add-ls', label: '新建 LS 组', containerId: 'add-ls', category: GT_TAB_CATEGORY.ADD, panel: P.add.ls, addFlow: 'ls' });
        }

        // Config panels (category-3)
        if (P.config && P.config.fee) {
            GT_PANEL_REGISTRY.push({ name: 'fee', label: '💰 手续费与平今', containerId: 'config-fee', category: GT_TAB_CATEGORY.CONFIG, panel: P.config.fee });
        }
        if (P.config && P.config.rebalance) {
            GT_PANEL_REGISTRY.push({ name: 'rebalance', label: '⚖️ 再平衡', containerId: 'config-rebalance', category: GT_TAB_CATEGORY.CONFIG, panel: P.config.rebalance });
        }

        _panelsRegistered = true;
    }

    function cacheGroupResult(submissionId, factorAlias, data) {
        if (!submissionId || !factorAlias || !data) return;
        if (!_groupResultsBySubmission[submissionId]) _groupResultsBySubmission[submissionId] = {};
        _groupResultsBySubmission[submissionId][factorAlias] = data;
    }

    function getCachedGroupResult(submissionId, factorAlias) {
        return _groupResultsBySubmission[submissionId] && _groupResultsBySubmission[submissionId][factorAlias];
    }

    function updateActiveGroupCache() {
        var context = getCurrentContext();
        if (!context || !context.submission_id || !context.factor_alias) return;
        var cached = getCachedGroupResult(context.submission_id, context.factor_alias);
        if (!cached) return;
        cached.groups = _lastGrossData;
        cached.metrics = _lastMetrics;
        cached._derivedGroups = _derivedGroups.map(function(item) { return Object.assign({}, item); });
        cached.structure_key = _lastGroupStructureKey;
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
        var feeRatio = parseFloat(newFeePct) / 100.0;  // 双边费率：% → 小数

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
            var tradeNotional = src.trade_notional_ratios || [];
            for (var i = 0; i < gross.length; i++) {
                var gRet = gross[i];
                // 后台统一费率会拆成开/平各一半；只有实际买卖的名义金额才扣费。
                // trade_notional=2 表示全卖再全买一次，刚好扣完整双边费率。
                var periodFee = feeRatio * ((tradeNotional[i] || 0.0) / 2.0);
                var net = (1.0 - periodFee) * (1.0 + gRet) - 1.0;
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
                trade_notional_ratios: src.trade_notional_ratios,
                is_ls: false
            });
        }

        // Long-Short 组
        var lsSrc = _lastGrossData[nGroups];
        if (lsSrc && lsSrc.is_ls) {
            var topGross = _lastGrossData[0] ? _lastGrossData[0].gross_returns || [] : [];
            var botGross = _lastGrossData[nGroups - 1] ? _lastGrossData[nGroups - 1].gross_returns || [] : [];
            var topTrade = _lastGrossData[0] ? _lastGrossData[0].trade_notional_ratios || [] : [];
            var botTrade = _lastGrossData[nGroups - 1] ? _lastGrossData[nGroups - 1].trade_notional_ratios || [] : [];
            var longCap = 0.5, shortCap = 0.5, totalCap = 1.0;
            var lsCum = [];
            for (var i = 0; i < Math.min(topGross.length, botGross.length); i++) {
                var longGross = topGross[i];
                var shortGross = -botGross[i];
                var longFee = feeRatio * ((topTrade[i] || 0.0) / 2.0);
                var shortFee = feeRatio * ((botTrade[i] || 0.0) / 2.0);
                var longNet = (1.0 - longFee) * (1.0 + longGross) - 1.0;
                var shortNet = (1.0 - shortFee) * (1.0 + shortGross) - 1.0;
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
            
            var startDate = null, endDate = null;
            if (startYear && startMonth && startDay) {
                startDate = buildValidDate(startYear, startMonth, startDay);
                if (startDate) {
                    var parts = startDate.split('-');
                    document.getElementById('group_start_year').value = parts[0];
                    document.getElementById('group_start_month').value = parseInt(parts[1], 10);
                    document.getElementById('group_start_day').value = parseInt(parts[2], 10);
                }
            }
            if (endYear && endMonth && endDay) {
                endDate = buildValidDate(endYear, endMonth, endDay);
                if (endDate) {
                    var parts = endDate.split('-');
                    document.getElementById('group_end_year').value = parts[0];
                    document.getElementById('group_end_month').value = parseInt(parts[1], 10);
                    document.getElementById('group_end_day').value = parseInt(parts[2], 10);
                }
            }

            // P8: Persist time range into groups datamodel
            if (GT.datamodel && GT.datamodel.groups && (startDate || endDate)) {
                var allBase = GT.datamodel.groups.getAll();
                allBase.forEach(function(bg) {
                    try {
                        var patch = {};
                        if (startDate) patch.startDate = startDate;
                        if (endDate) patch.endDate = endDate;
                        GT.datamodel.groups.update(bg.id, patch);
                    } catch (e) { /* skip */ }
                });
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

        // P8: Also persist time range into groups datamodel so group
        // definitions survive time-range changes (Issue #85 follow-up).
        var sy = document.getElementById('group_start_year');
        var sm = document.getElementById('group_start_month');
        var sd = document.getElementById('group_start_day');
        var ey = document.getElementById('group_end_year');
        var em = document.getElementById('group_end_month');
        var ed = document.getElementById('group_end_day');
        var startDate = (sy && sm && sd) ? buildValidDate(sy.value, sm.value, sd.value) : null;
        var endDate = (ey && em && ed) ? buildValidDate(ey.value, em.value, ed.value) : null;

        if (GT.datamodel && GT.datamodel.groups && (startDate || endDate)) {
            var allBase = GT.datamodel.groups.getAll();
            allBase.forEach(function(bg) {
                try {
                    var patch = {};
                    if (startDate) patch.startDate = startDate;
                    if (endDate) patch.endDate = endDate;
                    GT.datamodel.groups.update(bg.id, patch);
                } catch (e) {
                    // Silently skip if update fails (e.g. validation)
                }
            });
        }
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

    // ---------- 手续费表：已迁移到 fee.js（GT.fee.*），此处仅保留桥接 ----------

    // 桥接：fee.js 中 close-today 变更回调
    GT.ui.onCloseTodayChanged = function() {
        if (_derivedGroups.length > 0) {
            _derivedGeneration++;
            refreshAllDerivedGroups(_derivedGeneration);
        }
    };

    // 桥接：fee.js 中灵敏度滑条触发重算
    GT.ui.recalcWithFee = function(val) {
        recalcWithFee(val);
    };


    // ---------- 初始化 ----------
    function init() {
        renderReturnFreqCheckboxes();
        bindDateValidation();
        bindUseTimeRange();
        bindICModuleEvents();
        bindTimeSyncListeners();
        // 使用 GT.fee.bind() 替代原 bindFeeControls()
        if (GT.fee && typeof GT.fee.bind === 'function') {
            GT.fee.bind();
        }
        bindSnapshotDrawerEvents();
        bindGroupDetailOverlay();
        bindGroupSectionToggles();
        updateRebalanceModeDescription();
        syncFromTimeModule();
        document.addEventListener('timeRangeDefaultLoaded', syncFromTimeModule, { once: true });
        setTimeout(syncFromTimeModule, 0);
        var runBtn = document.getElementById('run_group_test_btn');
        if (runBtn) runBtn.addEventListener('click', runGroupTest);
        var defaultBtn = document.getElementById('load_default_groups_btn');
        if (defaultBtn) defaultBtn.addEventListener('click', loadDefaultGroups);
        var rebalanceSelect = document.getElementById('rebalance_mode');
        if (rebalanceSelect) rebalanceSelect.addEventListener('change', updateRebalanceModeDescription);

        // P7: Wire unified tab bar (single-level, was sub-tabs)
        (function bindUnifiedTabs() {
            var panelContainer = document.getElementById('gt-panel-container');
            var tabBtnsBar = document.getElementById('gt-tab-btns');
            if (!panelContainer) return;

            var _currentPanel = null;
            var _currentTab = 'list';
            /** Current panel mode: 'list' (default), 'add' (adding new groups), 'edit' (editing selection) */
            var _panelMode = 'list';
            /** In add mode: { testerId, groupCount, allGroups (bool), groupIndex, selectedFactors:[alias], addFlow:'base'|'derived'|'ls' } */
            var _addDraft = null;
            /** In edit mode: Set of selected base-group IDs */
            var _editSelection = null;

            /** Render the action bar buttons (three create buttons always show, mode-buttons replace them in add/edit) */
            function _renderTabActions() {
                var bar = document.getElementById('gt-tab-actions');
                if (!bar) return;
                var html = '';
                if (_panelMode === 'add') {
                    if (_addDraft && _addDraft.addFlow === 'derived') {
                        html += '<button id="gt-action-submit-derived" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">创建派生组</button>';
                    } else if (_addDraft && _addDraft.addFlow === 'ls') {
                        html += '<button id="gt-action-submit-ls" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">保存 LS 组</button>';
                    } else {
                        html += '<button id="gt-action-submit" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">提交基础组</button>';
                    }
                    html += '<button id="gt-action-cancel" class="btn btn-outline-secondary btn-sm" style="padding:4px 12px;font-size:12px;">取消新建</button>';
                } else if (_panelMode === 'edit') {
                    // Check edit selection count
                    var selCount = 0;
                    var selIds = null;
                    if (_editSelection && _editSelection instanceof Set) {
                        selCount = _editSelection.size;
                        selIds = Array.from(_editSelection);
                    } else if (_editSelection && Array.isArray(_editSelection)) {
                        selCount = _editSelection.length;
                        selIds = _editSelection;
                    } else if (_editSelection && typeof _editSelection === 'object') {
                        selIds = Object.keys(_editSelection).filter(function(k) { return _editSelection[k]; });
                        selCount = selIds.length;
                    }
                    if (selCount === 1) {
                        html += '<button id="gt-action-create-derived-from-selection" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">🌳 创建派生组</button>';
                    } else if (selCount === 2) {
                        html += '<button id="gt-action-create-ls-from-selection" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">⚡ 创建 Long-Short 组</button>';
                    }
                    html += '<button id="gt-action-save" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">保存修改</button>';
                    html += '<button id="gt-action-cancel-edit" class="btn btn-outline-secondary btn-sm" style="padding:4px 12px;font-size:12px;">取消编辑</button>';
                } else {
                    // Normal list mode: show "add base group" button only
                    html += '<button id="gt-action-add-base" class="btn btn-primary btn-sm" style="padding:4px 12px;font-size:12px;">＋ 新增基础组</button>';
                }
                bar.innerHTML = html;
                _bindActionButtons();
                _renderSectionStatus();
            }

            /** Render status beside "分组组合设置" title (edit mode / dirty hint) */
            function _renderSectionStatus() {
                var el = document.getElementById('gt-section-status');
                if (!el) return;

                if (_panelMode === 'edit') {
                    var REG = window.GT_CONFIG_REGISTRY;
                    var hasDirty = REG ? REG.hasDirty() : false;
                    el.style.display = '';
                    el.style.color = hasDirty ? '#e65100' : '#888';
                    el.textContent = hasDirty ? '编辑中 - 未保存' : '编辑中';
                } else if (_panelMode === 'add') {
                    el.style.display = '';
                    el.style.color = '#1565c0';
                    el.textContent = '新建中';
                } else {
                    el.style.display = 'none';
                    el.textContent = '';
                }
            }

            function _bindActionButtons() {
                // List mode buttons
                var addBaseBtn = document.getElementById('gt-action-add-base');
                if (addBaseBtn) addBaseBtn.addEventListener('click', function() { _enterAddMode('base'); });
                var addDerivedBtn = document.getElementById('gt-action-add-derived');
                if (addDerivedBtn) addDerivedBtn.addEventListener('click', function() { _enterAddMode('derived'); });
                var addLSBtn = document.getElementById('gt-action-add-ls');
                if (addLSBtn) addLSBtn.addEventListener('click', function() { _enterAddMode('ls'); });

                // Add mode buttons
                var submitBtn = document.getElementById('gt-action-submit');
                if (submitBtn) submitBtn.addEventListener('click', function() { _submitAddBatches(); });
                var submitDerivedBtn = document.getElementById('gt-action-submit-derived');
                if (submitDerivedBtn) submitDerivedBtn.addEventListener('click', function() { _submitAddDerivedGroup(); });
                var submitLSBtn = document.getElementById('gt-action-submit-ls');
                if (submitLSBtn) submitLSBtn.addEventListener('click', function() { _submitAddLSGroup(); });
                var cancelBtn = document.getElementById('gt-action-cancel');
                if (cancelBtn) cancelBtn.addEventListener('click', function() { _exitAddMode(); });

                // Edit mode buttons
                var saveBtn = document.getElementById('gt-action-save');
                if (saveBtn) saveBtn.addEventListener('click', function() { _saveEditChanges(); });
                var cancelEditBtn = document.getElementById('gt-action-cancel-edit');
                if (cancelEditBtn) cancelEditBtn.addEventListener('click', function() { _exitEditMode(); });
                var createDerivedBtn = document.getElementById('gt-action-create-derived-from-selection');
                if (createDerivedBtn) createDerivedBtn.addEventListener('click', function() { _createDerivedFromSelection(); });
                var createLSBtn = document.getElementById('gt-action-create-ls-from-selection');
                if (createLSBtn) createLSBtn.addEventListener('click', function() { _createLSFromSelection(); });
            }

            function _enterAddMode(addFlow) {
                _panelMode = 'add';
                _addDraft = { addFlow: addFlow };
                if (addFlow === 'base') {
                    _addDraft.testerId = null;
                    _addDraft.groupCount = 5;
                    _addDraft.allGroups = true;
                    _addDraft.groupIndex = 1;
                    _addDraft.selectedFactors = [];
                    _addDraft.feeMode = 'none';
                    _addDraft.rebalanceMode = 'each_period';
                    _renderTabActions();
                    mountTab('add-base');
                } else if (addFlow === 'derived') {
                    _addDraft.derivedGroupId = null;
                    // If no preselected parent (from _createDerivedFromSelection or +子), try active state
                    if (!_addDraft.preselectedBaseGroupId && !_addDraft.preselectedParentDerivedId) {
                        var activeDerivedId = GT.state && GT.state.getActiveDerivedNodeId ? GT.state.getActiveDerivedNodeId() : null;
                        if (activeDerivedId) {
                            _addDraft.preselectedParentDerivedId = activeDerivedId;
                        } else {
                            _addDraft.preselectedBaseGroupId = GT.state && GT.state.getActiveBaseGroupId ? GT.state.getActiveBaseGroupId() : null;
                        }
                    }
                    _renderTabActions();
                    mountTab('add-derived');
                } else if (addFlow === 'ls') {
                    _renderTabActions();
                    mountTab('add-ls');
                }
            }

            function _exitAddMode() {
                _panelMode = 'list';
                _addDraft = null;
                _renderTabActions();
                mountTab('list');
            }

            function _submitAddBatches() {
                if (!_addDraft || !_addDraft.testerId) { alert('请先选择测试器'); return; }
                var gc = _addDraft.groupCount;
                if (gc < 1) { alert('分组数必须 ≥ 1'); return; }
                var factors = _addDraft.selectedFactors;
                if (factors.length === 0) { alert('请至少选择一个因子'); return; }

                try {
                    var addPanel = GT_PANEL_REGISTRY.find(function(p) { return p.name === 'add-base'; });
                    if (addPanel && addPanel.panel && typeof addPanel.panel.submitAddBatches === 'function') {
                        var result = addPanel.panel.submitAddBatches(_addDraft);
                        if (result && result.added) {
                            GT.log('_submitAddBatches: added ' + result.added + ' groups');
                        }
                    }
                } catch (err) {
                    GT.log('_submitAddBatches error: ' + (err && err.message || err));
                    alert('提交失败：' + (err && err.message || '未知错误'));
                } finally {
                    _exitAddMode();
                }
            }

            function _submitAddDerivedGroup() {
                if (!_addDraft) { alert('提交草稿丢失'); return; }
                var baseGroupId = _addDraft.preselectedBaseGroupId;
                var parentDerivedId = _addDraft.preselectedParentDerivedId;

                // Must have either a base group or a parent derived group
                if (!baseGroupId && !parentDerivedId) {
                    alert('请先从列表中选择一个基础组或派生组作为上级');
                    return;
                }
                // Resolve baseGroupId from parent derived node if not set directly
                if (!baseGroupId && parentDerivedId) {
                    var pNode = GT.datamodel.groups && GT.datamodel.groups.get(parentDerivedId);
                    if (pNode && pNode.isDerived) {
                        baseGroupId = pNode.baseGroupId;
                    }
                    if (!baseGroupId) {
                        alert('无法确定上级派生组关联的基础组');
                        return;
                    }
                }

                // Derive a default name: explicit name > shortAlias of base group > base group name > fallback
                var resolvedName = _addDraft.name || _addDraft.defaultName;
                if (!resolvedName || (typeof resolvedName === 'string' && !resolvedName.trim())) {
                    var bg = GT.datamodel.groups && GT.datamodel.groups.get(baseGroupId);
                    resolvedName = (bg && (bg.shortAlias || bg.name)) || '派生组';
                }

                var derivedPanel = GT.panels.add && GT.panels.add.derived;
                var selectedProducts = (derivedPanel && typeof derivedPanel.getSelectedProducts === 'function')
                    ? derivedPanel.getSelectedProducts() : [];

                var productMask = {};
                for (var i = 0; i < selectedProducts.length; i++) {
                    productMask[selectedProducts[i]] = true;
                }

                var config = {
                    name: resolvedName,
                    isDerived: true,
                    baseGroupId: baseGroupId,
                    productMask: productMask,
                };
                if (parentDerivedId) {
                    config.parentId = parentDerivedId;
                }

                try {
                    GT.datamodel.groups.add(config);
                } catch (err) {
                    alert('创建派生组失败: ' + (err && err.message || err));
                    return;
                }
                _exitAddMode();
            }

            function _submitAddLSGroup() {
                var lsPanel = GT.panels.add && GT.panels.add.ls;
                if (lsPanel && typeof lsPanel.handleSave === 'function') {
                    var result = lsPanel.handleSave();
                    if (result.success) {
                        _exitAddMode();
                    } else if (result.error) {
                        alert('创建 LS 组失败: ' + result.error);
                    }
                }
            }

            function _enterEditMode(selection) {
                // Clear any leftover dirty state from previous edit sessions
                var REG = window.GT_CONFIG_REGISTRY;
                if (REG) REG.rollbackDirty();

                _panelMode = 'edit';
                _editSelection = selection || {};
                _renderTabActions();
                // Don't remount the list panel — it's already showing.
                // Just refresh the tab bar to show config tabs.
                // Update the tab bar to show list + config tabs side by side
                if (tabBtnsBar) {
                    var L = GT_TAB_CATEGORY.LIST, C = GT_TAB_CATEGORY.CONFIG;
                    var visibleList = GT_PANEL_REGISTRY.filter(function(p) { return p.category === L || p.category === C; });
                    if (visibleList.length >= 1) {
                        var stHtml = '';
                        visibleList.forEach(function(p) {
                            stHtml += '<button class="gt-tab' + (p.name === _currentTab ? ' active' : '') + '" data-tab="' + p.name + '">' + p.label + '</button>';
                        });
                        tabBtnsBar.innerHTML = stHtml;
                        tabBtnsBar.querySelectorAll('.gt-tab').forEach(function(st) {
                            st.addEventListener('click', function() {
                                mountTab(st.getAttribute('data-tab'));
                            });
                        });
                    }
                }
            }

            function _exitEditMode() {
                // Discard any unsaved dirty state
                var REG = window.GT_CONFIG_REGISTRY;
                if (REG) REG.rollbackDirty();

                _panelMode = 'list';
                _editSelection = null;
                GT.state.setActiveBaseGroupId(null);
                GT.state.setActiveDerivedNodeId(null);
                GT.state.emit('editModeExited');
                _renderTabActions();
                // Refresh tab bar back to list-only
                if (tabBtnsBar) {
                    var L = GT_TAB_CATEGORY.LIST;
                    var visibleList = GT_PANEL_REGISTRY.filter(function(p) { return p.category === L; });
                    if (visibleList.length >= 1) {
                        var stHtml = '';
                        visibleList.forEach(function(p) {
                            stHtml += '<button class="gt-tab' + (p.name === _currentTab ? ' active' : '') + '" data-tab="' + p.name + '">' + p.label + '</button>';
                        });
                        tabBtnsBar.innerHTML = stHtml;
                        tabBtnsBar.querySelectorAll('.gt-tab').forEach(function(st) {
                            st.addEventListener('click', function() {
                                mountTab(st.getAttribute('data-tab'));
                            });
                        });
                    } else {
                        tabBtnsBar.innerHTML = '';
                    }
                }
                mountTab('list');
            }

            /**
             * Create a derived group from a single selected item (base group or derived group).
             * Opens the derived add panel pre-filled with the selection as parent.
             */
            function _createDerivedFromSelection() {
                var selIds;
                if (_editSelection && _editSelection instanceof Set) {
                    selIds = Array.from(_editSelection);
                } else if (_editSelection && Array.isArray(_editSelection)) {
                    selIds = _editSelection;
                } else if (_editSelection && typeof _editSelection === 'object') {
                    selIds = Object.keys(_editSelection).filter(function(k) { return _editSelection[k]; });
                } else {
                    selIds = [];
                }
                if (selIds.length !== 1) {
                    alert('请选择 1 行来创建派生组');
                    return;
                }
                var selectedId = selIds[0];

                // Determine if the selection is a base group or a derived group
                // (Both are in groups, distinguished by isDerived flag)
                var draft = { addFlow: 'derived' };
                var sg = GT.datamodel.groups && GT.datamodel.groups.get(selectedId);
                if (sg && sg.isDerived) {
                    // It's a derived group → use as parent
                    draft.preselectedParentDerivedId = selectedId;
                } else if (sg) {
                    // It's a base group → use as base
                    draft.preselectedBaseGroupId = selectedId;
                } else {
                    alert('无法识别选中的分组类型');
                    return;
                }

                _exitEditMode();
                _panelMode = 'add';
                _addDraft = draft;
                mountTab('add-derived');
                _renderTabActions();
            }

            /**
             * Create a Long-Short group from 2+ selected base groups.
             * Each selected base group gets its own derived node first,
             * then an LS config is created pairing them.
             */
            function _createLSFromSelection() {
                var selIds;
                if (_editSelection && _editSelection instanceof Set) {
                    selIds = Array.from(_editSelection);
                } else if (_editSelection && Array.isArray(_editSelection)) {
                    selIds = _editSelection;
                } else if (_editSelection && typeof _editSelection === 'object') {
                    selIds = Object.keys(_editSelection).filter(function(k) { return _editSelection[k]; });
                } else {
                    selIds = [];
                }
                if (selIds.length < 2) {
                    alert('请至少选择 2 个基础组来创建 Long-Short 组');
                    return;
                }
                // Switch to LS add mode with pre-selected base groups
                _exitEditMode();
                _panelMode = 'add';
                _addDraft = { addFlow: 'ls', preselectedBaseGroupIds: selIds };
                mountTab('add-ls');
                _renderTabActions();
            }

            GT.ui.createDerivedFromSelection = _createDerivedFromSelection;
            GT.ui.createLSFromSelection = _createLSFromSelection;

            function _saveEditChanges() {
                // Commit any unsaved dirty state from config panels
                var REG = window.GT_CONFIG_REGISTRY;
                if (REG) REG.commitDirty();
                // Exit edit mode without rollback (dirty already committed or none)
                _panelMode = 'list';
                _editSelection = null;
                GT.state.setActiveBaseGroupId(null);
                GT.state.setActiveDerivedNodeId(null);
                GT.state.emit('editModeExited');
                _renderTabActions();
                // Refresh tab bar back to list-only
                if (tabBtnsBar) {
                    var L = GT_TAB_CATEGORY.LIST;
                    var visibleList = GT_PANEL_REGISTRY.filter(function(p) { return p.category === L; });
                    if (visibleList.length >= 1) {
                        var stHtml = '';
                        visibleList.forEach(function(p) {
                            stHtml += '<button class="gt-tab' + (p.name === _currentTab ? ' active' : '') + '" data-tab="' + p.name + '">' + p.label + '</button>';
                        });
                        tabBtnsBar.innerHTML = stHtml;
                        tabBtnsBar.querySelectorAll('.gt-tab').forEach(function(st) {
                            st.addEventListener('click', function() {
                                mountTab(st.getAttribute('data-tab'));
                            });
                        });
                    } else {
                        tabBtnsBar.innerHTML = '';
                    }
                }
                mountTab('list');
            }

            // Expose mode management
            GT.ui.getPanelMode = function() { return _panelMode; };
            GT.ui.getAddDraft = function() { return _addDraft; };
            GT.ui.updateAddDraft = function(patch) { if (_addDraft) Object.assign(_addDraft, patch); };
            GT.ui.getEditSelection = function() { return _editSelection; };
            GT.ui.enterEditMode = _enterEditMode;
            GT.ui.exitEditMode = _exitEditMode;
            GT.ui.enterAddMode = _enterAddMode;
            GT.ui.exitAddMode = _exitAddMode;
            GT.ui.renderTabActions = _renderTabActions;

            /** Call unmount on currently mounted panel (if any) */
            function _unmountCurrent() {
                if (_currentPanel && typeof _currentPanel.unmount === 'function') {
                    _currentPanel.unmount();
                }
                _currentPanel = null;
                if (tabBtnsBar) tabBtnsBar.innerHTML = '';
                if (panelContainer) panelContainer.innerHTML = '';
            }

            /** Mount a specific tab panel */
            function mountTab(tabName) {
                _unmountCurrent();
                _currentTab = tabName;

                // Tab visibility by mode:
                //   list mode:  category-1 (LIST)
                //   edit mode:  category-1 (LIST) + category-3 (CONFIG)
                //   add mode:   category-2 (ADD) + category-3 (CONFIG)
                var L = GT_TAB_CATEGORY.LIST, C = GT_TAB_CATEGORY.CONFIG, A = GT_TAB_CATEGORY.ADD;
                var visibleCategories;
                if (_panelMode === 'list') {
                    visibleCategories = [L];
                } else if (_panelMode === 'edit') {
                    visibleCategories = [L, C];
                } else if (_panelMode === 'add') {
                    visibleCategories = [A, C];
                } else {
                    visibleCategories = [L];
                }

                // All panels whose category is visible — used for rendering the tab bar
                var visibleList = GT_PANEL_REGISTRY.filter(function(p) {
                    return visibleCategories.indexOf(p.category) >= 0;
                });

                // In add mode, only show ADD tabs matching the current addFlow
                if (_panelMode === 'add' && _addDraft && _addDraft.addFlow) {
                    visibleList = visibleList.filter(function(p) {
                        return p.category !== A || p.addFlow === _addDraft.addFlow;
                    });
                }

                // Find the entry to mount: same as visibleList but in add mode
                // only mount ADD panels whose name matches the requested add-flow
                var entry = visibleList.find(function(p) {
                    if (p.name !== tabName) return false;
                    if (_panelMode === 'add' && p.category === A) return true; // ADD panels: exact name match
                    return true; // CONFIG panels: name match is enough
                });
                if (!entry) return;

                // Render tabs into #gt-tab-btns — always show all visible tabs
                if (tabBtnsBar && visibleList.length >= 1) {
                    var stHtml = '';
                    visibleList.forEach(function(p) {
                        stHtml += '<button class="gt-tab' + (p.name === tabName ? ' active' : '') + '" data-tab="' + p.name + '">' + p.label + '</button>';
                    });
                    tabBtnsBar.innerHTML = stHtml;
                    tabBtnsBar.querySelectorAll('.gt-tab').forEach(function(st) {
                        st.addEventListener('click', function() {
                            mountTab(st.getAttribute('data-tab'));
                        });
                    });
                } else if (tabBtnsBar) {
                    // Single panel (e.g., add mode) — hide tab bar
                    tabBtnsBar.innerHTML = '';
                }

                // Ensure panel container exists
                if (panelContainer) {
                    panelContainer.innerHTML = '<div id="' + entry.containerId + '" class="gt-panel-inner"></div>';
                }

                // Mount the panel — pass the container element
                if (entry.panel && typeof entry.panel.mount === 'function') {
                    var containerEl = document.getElementById(entry.containerId);
                    if (containerEl) {
                        entry.panel.mount(containerEl);
                        _currentPanel = entry.panel;
                    } else {
                        console.warn('mountTab: container #' + entry.containerId + ' not found for tab ' + tabName);
                    }
                }

                // Always refresh action buttons
                _renderTabActions();
            }

            // Expose for external use
            GT.ui.mountTab = mountTab;

            // Register panels and mount initial
            _registerPanels();
            mountTab('list');
        })();
        var addIntradayWindowBtn = document.getElementById('group-intraday-window-add');
        if (addIntradayWindowBtn) addIntradayWindowBtn.addEventListener('click', addSelectedIntradayWindow);

        // 如果已有 submissions，渲染两级选项卡
        if (window.submissions && window.submissions.length > 0) {
            window.renderGroupTabs(window.submissions);
        }

        // 绑定分组组合设置折叠/展开
        var sectionHeader = document.getElementById('gt-section-header');
        var sectionToggle = document.getElementById('gt-section-toggle');
        var layerTabs = document.getElementById('gt-layer-tabs');
        if (sectionHeader && layerTabs && sectionToggle) {
            // 移除 HTML 上的 inline onclick，用 JS 统一管理
            sectionHeader.removeAttribute('onclick');
            sectionHeader.addEventListener('click', function() {
                var collapsed = layerTabs.classList.toggle('gt-collapsed');
                sectionToggle.style.transform = collapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
                // Scroll to reveal tab content when expanding
                if (!collapsed && layerTabs) {
                    layerTabs.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
            // 默认折叠
            layerTabs.classList.add('gt-collapsed');
            sectionToggle.style.transform = 'rotate(-90deg)';
        }

        // ── Click-on-empty-area exits edit mode ──
        var panelContainer = document.getElementById('gt-panel-container');
        if (panelContainer) {
            panelContainer.addEventListener('click', function(e) {
                // Only react if clicking the container itself (not children), and in edit mode
                if (e.target === panelContainer && GT.ui.getPanelMode() === 'edit') {
                    GT.ui.exitEditMode();
                }
            });
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
        var lsOverlay = document.getElementById('long-short-drawer');
        var lsOpenBtn = document.getElementById('long-short-drawer-trigger');
        var lsCloseBtn = document.getElementById('long-short-drawer-close');
        var lsAddBtn = document.getElementById('long-short-add-btn');
        if (lsOpenBtn) lsOpenBtn.addEventListener('click', function() {
            renderLongShortConfigList();
            updateLongShortSummary();
            if (lsOverlay) lsOverlay.classList.add('open');
        });
        if (lsCloseBtn) lsCloseBtn.addEventListener('click', function() {
            if (lsOverlay) lsOverlay.classList.remove('open');
        });
        if (lsOverlay) lsOverlay.addEventListener('click', function(event) {
            if (event.target === lsOverlay) lsOverlay.classList.remove('open');
        });
        if (lsAddBtn) lsAddBtn.addEventListener('click', function() {
            var nextId = 'LS' + (Date.now());
            _longShortDefinitions.push({ id: nextId, name: 'Long-Short ' + _longShortDefinitions.length, longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' });
            renderLongShortConfigList();
            updateLongShortSummary();
        });
        updateLongShortSummary();
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

    // 暴露给外部调用：渲染分组测试 UI（P7: 5-layer layout）
    // Fills #gt-submission-tabs with horizontal pills.
    // Old #group-tab-container kept hidden for backward compat factor navigation.
    window.renderGroupTabs = function(submissions) {
        var container = document.getElementById('group-tab-container');
        var subTabsContainer = document.getElementById('gt-submission-tabs');
        var runBtn = document.getElementById('run_group_test_btn');
        var defaultBtn = document.getElementById('load_default_groups_btn');

        if (!submissions || submissions.length === 0) {
            // Update both old and new containers
            if (container) container.innerHTML = '<div style="color:#888; padding:8px; border:1px dashed #ccc; border-radius:4px; font-size:13px;">暂无提交记录，请先在产品类别筛选模块提交产品。</div>';
            if (subTabsContainer) subTabsContainer.innerHTML = '<span style="color:#888;font-size:12px;padding:4px 8px;">暂无提交记录</span>';
            if (runBtn) runBtn.style.display = 'none';
            if (defaultBtn) defaultBtn.style.display = 'none';
            return;
        }
        if (runBtn) runBtn.style.display = '';
        if (defaultBtn) defaultBtn.style.display = '';

        var factorList = window.factorList || [];
        var activeSubmission = submissions.find(function(sub) {
            return String(sub.id) === String(_activeGroupSubmissionId);
        }) || submissions[0];
        _activeGroupSubmissionId = activeSubmission ? String(activeSubmission.id) : null;

        // ── P7: Fill #gt-submission-tabs with horizontal pills ──
        if (subTabsContainer) {
            var subTabsHtml = '';
            submissions.forEach(function(sub) {
                var isActive = String(sub.id) === String(_activeGroupSubmissionId);
                var tabLabel = sub.product_group || sub.label || ('测试器');
                subTabsHtml += '<button type="button" class="gt-submission-tab' + (isActive ? ' active' : '') + '" data-submission-id="' + escGrp(sub.id) + '">'
                    + escGrp(tabLabel) + '</button>';
            });
            subTabsContainer.innerHTML = subTabsHtml;
            subTabsContainer.querySelectorAll('.gt-submission-tab').forEach(function(tab) {
                tab.addEventListener('click', function() {
                    _activeGroupSubmissionId = tab.getAttribute('data-submission-id');
                    window.renderGroupTabs(submissions);
                });
            });
        }

        // ── P7: Fill old #group-tab-container (hidden) for factor navigation compat ──
        var activeFactorAlias = getActiveFactorAliasForSubmission(_activeGroupSubmissionId)
            || (factorList.length > 0 ? (factorList[0].alias || factorList[0].name || '') : null);
        if (activeFactorAlias && _activeGroupSubmissionId) {
            _activeGroupFactorBySubmission[_activeGroupSubmissionId] = activeFactorAlias;
        }

        if (container) {
            var navHtml = '';
            if (factorList.length > 0 && _activeGroupSubmissionId) {
                factorList.forEach(function(f) {
                    var alias = f.alias || f.name || '';
                    var isFactorActive = alias === activeFactorAlias;
                    var cached = getCachedGroupResult(_activeGroupSubmissionId, alias);
                    var status = cached ? (cached.success ? 'done' : 'error') : '';
                    navHtml += '<button type="button" class="group-factor-nav-btn' + (isFactorActive ? ' active' : '')
                        + '" data-submission-id="' + escGrp(_activeGroupSubmissionId)
                        + '" data-factor-alias="' + escGrp(alias)
                        + '" data-run-status="' + status + '" style="display:none;">'
                        + '<span>' + escGrp(alias) + '</span>'
                        + '<span class="group-factor-run-status">' + (status === 'done' ? '✓' : (status === 'error' ? '!' : '')) + '</span>'
                        + '</button>';
                });
            }
            container.innerHTML = navHtml;
        }

        bindGroupFactorTabLongPress();
        bindGroupFactorNavigation();
        restoreActiveGroupResult({ preserveWhenMissingActive: factorList.length === 0 });

        // 当 submissions 到达时，总是重新挂载当前面板。
        // 这确保面板能感知到新的 submission 上下文（如基础组列表按 testerId 筛选）。
        if (submissions.length > 0) {
            // 确保 GT_PANEL_REGISTRY 已注册（可能在 init 之前到达）
            if (GT_PANEL_REGISTRY && (!GT_PANEL_REGISTRY.length)) {
                _registerPanels();
            }
            // 重新挂载当前 tab
            if (GT.ui.mountTab) {
                GT.ui.mountTab('list');
            }
        }
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
        var sid = activeBtn.getAttribute('data-submission-id');
        var falias = activeBtn.getAttribute('data-factor-alias');
        var result = getCachedGroupResult(sid, falias);
        console.log('[GroupTest] restoreActiveGroupResult: sid=' + sid + ' factor=' + falias + ' cached=' + (result ? result.tester_alias || '(yes, no tester_alias)' : 'no'));
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
    // Expose primary entrypoints under GroupTest (namespaced)
    GT.ui.init = init;
    GT.ui.renderTabs = window.renderGroupTabs;

    // ── Submission bus subscriptions ────────────────────────────────────────────
    (function() {
        var bus = window._submissionBus;
        if (!bus) return;

        // React to tester deletion: clean up groups, ls_configs, registrations, caches
        bus.on(bus.EVENTS.REMOVED, function(data) {
            if (!data || !data.id_time) return;
            var removedTesterId = String(data.id_time);

            // 1) Remove all groups referencing this tester (base + derived via cascade)
            if (GT.datamodel && GT.datamodel.groups) {
                var allGroups = GT.datamodel.groups.getAll();
                // First pass: remove all groups (base or derived) that reference this tester
                for (var gi = 0; gi < allGroups.length; gi++) {
                    var g = allGroups[gi];
                    if (String(g.testerId) === removedTesterId) {
                        try {
                            GT.datamodel.groups.remove(g.id); // cascades to descendants
                        } catch(e) {
                            console.warn('[group_test/bus] Failed to remove group:', g.id, e);
                        }
                    }
                }
            }

            // 3) Clear ls_configs (these are tester-scoped)
            if (GT.datamodel && GT.datamodel.ls_configs) {
                try {
                    GT.datamodel.ls_configs._reset();
                } catch(e) {}
            }

            // 4) Clear registrations
            if (GT.datamodel && GT.datamodel.registrations) {
                try {
                    GT.datamodel.registrations._reset();
                } catch(e) {}
            }

            // 5) Clear group result cache for this tester
            if (_groupResultsBySubmission[removedTesterId]) {
                delete _groupResultsBySubmission[removedTesterId];
            }
            if (_activeGroupFactorBySubmission[removedTesterId]) {
                delete _activeGroupFactorBySubmission[removedTesterId];
            }
            if (String(_activeGroupSubmissionId) === removedTesterId) {
                _activeGroupSubmissionId = null;
            }
        });

        // React to any change: re-render tabs
        bus.on('*', function(event) {
            if (window.submissions && window.submissions.length > 0) {
                window.renderGroupTabs(window.submissions);
            } else {
                // Empty state
                var container = document.getElementById('gt-submission-tabs');
                if (container) {
                    container.innerHTML = '<span style="color:#888;font-size:12px;padding:4px 8px;">暂无提交记录</span>';
                }
                var runBtn = document.getElementById('run_group_test_btn');
                if (runBtn) runBtn.style.display = 'none';
            }
        });
    })();

    // ── Datamodel sync bridge (Issue #85 P7) ───────────────────────────────────
    // When new datamodel is available, expose a sync function so that
    // global_template_module.js can push legacy DOM/state into GT.datamodel
    // before calling GT.datamodel.settings.snapshot() during template save.
    GT.ui.syncLegacyStateToDatamodel = function() {
        if (!GT.datamodel || !GT.datamodel.groups ||
            !GT.datamodel.ls_configs || !GT.datamodel.registrations) {
            return false;
        }
        try {
            GT.datamodel.groups._reset();
            GT.datamodel.ls_configs._reset();
            GT.datamodel.registrations._reset();

            // Sync legacy _derivedGroups → datamodel.groups (unified storage)
            if (_derivedGroups && _derivedGroups.length > 0) {
                // Sort: base-only first (no parent or parent==='0'), then by id
                var sortedDerived = _derivedGroups.slice().sort(function(a, b) {
                    var aIsBase = !a.parent || a.parent === '0';
                    var bIsBase = !b.parent || b.parent === '0';
                    if (aIsBase && !bIsBase) return -1;
                    if (!aIsBase && bIsBase) return 1;
                    return (a.id || '').localeCompare(b.id || '');
                });
                sortedDerived.forEach(function(dg) {
                    var parentId = (!dg.parent || dg.parent === '0') ? null : dg.parent;
                    try {
                        GT.datamodel.groups.add({
                            name: dg.name || ('Group ' + dg.id),
                            isDerived: true,
                            parentId: parentId,
                            baseGroupId: dg.baseGroup,
                            productMask: dg.productMask,
                            feeMode: dg.feeMode || 'none',
                            feeRate: dg.feeRate != null ? dg.feeRate : null,
                            feeMap: dg.feeMap != null ? dg.feeMap : null,
                            useCloseToday: dg.useCloseToday !== undefined ? !!dg.useCloseToday : false,
                            rebalanceMode: dg.rebalanceMode || 'each_period'
                        });
                    } catch (e) {
                        console.warn('[app.js syncDatamodel] skip derived group:', dg.id, e.message);
                    }
                });
            }

            // Sync legacy _longShortDefinitions → datamodel.ls_configs
            if (_longShortDefinitions && _longShortDefinitions.length > 0) {
                _longShortDefinitions.forEach(function(ls) {
                    try {
                        GT.datamodel.ls_configs.add({
                            name: ls.name || 'LS-' + ls.id,
                            longGroups: (ls.longGroups || '').toString(),
                            longWeights: (ls.longWeights || '').toString(),
                            shortGroups: (ls.shortGroups || '').toString(),
                            shortWeights: (ls.shortWeights || '').toString()
                        });
                    } catch (e) {
                        console.warn('[app.js syncDatamodel] skip LS config:', ls.id, e.message);
                    }
                });
            }

            return true;
        } catch (e) {
            console.error('[app.js syncDatamodel] error:', e);
            return false;
        }
    };
})();
