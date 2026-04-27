/**
 * 分组测试模块独立脚本
 */
(function() {
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

    // ---------- 清空测试结果 ----------
    function clearResults() {
        var chartContainer = document.getElementById('group_chart_container');
        var metricsContainer = document.getElementById('group_metrics_container');
        if (chartContainer) chartContainer.style.display = 'none';
        if (metricsContainer) metricsContainer.style.display = 'none';
        var status = document.getElementById('group_test_status');
        if (status) status.innerHTML = '';
    }

    // ---------- 绘制分组累计收益曲线 ----------
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
            'Win Rate': '胜率', 'Mean Return': '均值收益率', 'Skewness': '偏度', 'Kurtosis': '峰度'
        };
        
        // 表头
        var theadHtml = '<tr><th>分组</th>';
        metricNames.forEach(function(name) {
            theadHtml += '<th>' + (metricNamesCN[name] || name) + '</th>';
        });
        theadHtml += '</tr>';
        document.getElementById('metrics_head').innerHTML = theadHtml;
        
        // 表体
        var tbodyHtml = '';
        for (var groupIdx in metrics) {
            if (!metrics.hasOwnProperty(groupIdx)) continue;
            var groupMetrics = metrics[groupIdx];
            var isLS = (groupIdx === 'LS');
            var label = isLS ? '<strong>Long-Short</strong>' : ('<strong>第' + (parseInt(groupIdx)+1) + '组</strong>');
            var rowStyle = isLS ? ' style="background:#f0f0f0;font-weight:600;"' : '';
            tbodyHtml += '<tr' + rowStyle + '><td>' + label + '</td>';
            metricNames.forEach(function(name) {
                var val = groupMetrics[name];
                if (typeof val === 'number') {
                    if (name.includes('Rate') || name.includes('Return') || name.includes('Drawdown')) {
                        val = val.toFixed(2) + '%';
                    } else if (name.includes('Ratio')) {
                        val = val.toFixed(4);
                    } else {
                        val = val.toFixed(4);
                    }
                } else if (val === null || val === undefined) {
                    val = '—';
                }
                tbodyHtml += '<td>' + val + '</td>';
            });
            tbodyHtml += '</tr>';
        }
        document.getElementById('metrics_body').innerHTML = tbodyHtml;
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
        
        statusSpan.innerHTML = '分组测试运行中...';
        statusSpan.style.color = '#0078d4';
        
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
                end_date: end_date
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
            statusSpan.innerHTML = '✓ 分组测试完成';
            statusSpan.style.color = '#28a745';
            drawGroupChart(data.groups);
            renderMetricsTable(data.metrics);
        })
        .catch(function(err) {
            statusSpan.innerHTML = '请求失败: ' + err.message;
            statusSpan.style.color = '#d40000';
            console.error(err);
        });
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

    /** 获取当前费率修改（供全局模板 collectSnapshot 调用） */
    window._getFeeModifications = function() {
        return JSON.parse(JSON.stringify(_feeModifications));
    };

    /** 应用费率修改（供全局模板 applySnapshot 调用） */
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
    }

    // ---------- 初始化 ----------
    function init() {
        bindDateValidation();
        bindUseTimeRange();
        bindICModuleEvents();
        bindTimeSyncListeners();
        bindFeeControls();
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
                        '<div style="color:#888;padding:16px;text-align:center;">已选择因子 <b>' + (f.alias || f.name) + '</b>，配置好参数后点击上方"运行分组测试"</div>' +
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
