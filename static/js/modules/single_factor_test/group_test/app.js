(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GroupTest] bootstrap missing'); return; }

    // 确保 GT.ui 在全局代码使用前已初始化
    GT.ui = GT.ui || {};

    // 时区：后端返回 UTC epoch，useUTC=false 按浏览器本地时区显示
    if (typeof Highcharts !== 'undefined') {
        Highcharts.setOptions({ global: { useUTC: false } });
    }

    // ---------- 日期工具桥接（已迁移到 GT.utils.dates） ----------
    // 保留本地引用以兼容现有代码，无新代码使用时应逐步移除
    var showDateHint = GT.utils.dates ? GT.utils.dates.showDateHint : function(){};
    var bindDateValidation = GT.utils.dates ? GT.utils.dates.bindDateValidation : function(){};
    var buildValidDate = GT.utils.dates ? GT.utils.dates.buildValidDate : function(y,m,d){ return y+'-'+m+'-'+d; };
    var readGroupTimeRangeInput = GT.utils.dates ? GT.utils.dates.readGroupTimeRangeInput : function(){ return {startDate:null,endDate:null}; };
    var persistGroupTimeRangeToDatamodel = GT.utils.dates ? GT.utils.dates.persistGroupTimeRangeToDatamodel : function(){};
    var resolveGroupRunTimeRange = GT.utils.dates ? GT.utils.dates.resolveGroupRunTimeRange : function(){ return {startDate:null,endDate:null}; };
    var bindUseTimeRange = GT.utils.dates ? GT.utils.dates.bindUseTimeRange : function(){};
    var syncFromTimeModule = GT.utils.dates ? GT.utils.dates.syncFromTimeModule : function(){};
    var bindTimeSyncListeners = GT.utils.dates ? GT.utils.dates.bindTimeSyncListeners : function(){};

    GT.ui._readGroupTimeRangeInput = readGroupTimeRangeInput;
    GT.ui._resolveGroupRunTimeRange = resolveGroupRunTimeRange;

    // ---------- 激活状态桥接（已迁移到 GT.utils.dates） ----------
    var getActiveSubmissionId = GT.utils.dates ? GT.utils.dates.getActiveSubmissionId : function() { return null; };
    var getActiveFactorAlias = GT.utils.dates ? GT.utils.dates.getActiveFactorAlias : function() { return null; };
    var pageHasICModule = GT.utils.dates ? GT.utils.dates.pageHasICModule : function() { return false; };

    // ---------- 多时段品种策略提示面板 ----------
    function updateStrategyPanel(multiSessionActive, usedMode, multiSessionBatches) {
        if (GT.results && GT.results.strategyPanel && typeof GT.results.strategyPanel.render === 'function') {
            GT.results.strategyPanel.render(multiSessionActive, usedMode, multiSessionBatches);
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
        if (chartContainer) chartContainer.style.display = 'none';
        if (metricsContainer) metricsContainer.style.display = 'none';
        closeSnapshotDrawer();
        if (options.clearStatus) {
            var status = document.getElementById('group_test_status');
            if (status) status.innerHTML = '';
        }
    }

    /**
     * 构建连续等间隔时间轴。
     * 自动检测日内/日间，生成自适应格式的标签，并计算合理的标签步长。
     * 返回 { labels, labelAt, stepMs, labelEvery }。
     */
    function buildContinuousTimeAxis(rows, timestampGetter) {
        return GT.utils.dates.buildContinuousTimeAxis(rows, timestampGetter);
    }

    function drawGroupChart(groups) {
        if (!GT.chart || !GT.chart.groups || typeof GT.chart.groups.draw !== 'function') return;
        GT.chart.groups.draw(groups, {
            onSnapshot: fetchGroupSnapshot,
        });
    }

    // ---------- 快照导航状态 ----------
    var _snapshotTimestamps = [];  // 所有可用时间点（epoch ms）
    var _snapshotCurrentMs = null; // 当前显示的时间点

    // ---------- 获取并展示分组快照 ----------
    function fetchGroupSnapshot(timestampMs) {
        var submissionId = getActiveSubmissionId();
        if (!submissionId) return;

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
                submission_id: submissionId,
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
        if (GT.metrics && GT.metrics.table && typeof GT.metrics.table.render === 'function') {
            GT.metrics.table.render(metrics, _lastGrossData, {
                openResultGroupDetail: GT.metrics.detailOverlay.index.openResultGroupDetail,
                openGroupRankingDetail: GT.metrics.detailOverlay.index.openGroupRankingDetail,
            });
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

    /* ───── 辅助函数（用于 renderGroupFrequency / renderGroupDetailTable） ───── */
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

    function escapeHtml(value) {
        return GT.escapeHTML(value);
    }

    function fmtFeeRate(value) {
        if (value == null || isNaN(value) || !isFinite(value)) return '—';
        var bp = value * 10000;
        return bp.toFixed(5) + ' bp';
    }

    function isRealFee(row) {
        return !!(row && row.product && row.product.fee && row.product.fee._is_real_fee);
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
        if (GT.datamodel && GT.datamodel.groups && typeof GT.datamodel.groups.effectiveProductNames === 'function') {
            return GT.datamodel.groups.effectiveProductNames(node, {
                getProductsForTester: productNamesForTester
            }, seen);
        }
        return [];
    }

    function groupDisplayKey(group, allGroups) {
        if (GT.datamodel && GT.datamodel.groups && typeof GT.datamodel.groups.displayKey === 'function') {
            return GT.datamodel.groups.displayKey(group, allGroups);
        }
        if (!group) return '';
        return group.shortAlias || group.key || group.name || group.id || '';
    }

    function lsDisplayName(ls) {
        if (GT.datamodel && GT.datamodel.ls_configs && typeof GT.datamodel.ls_configs.displayName === 'function') {
            return GT.datamodel.ls_configs.displayName(ls);
        }
        return (ls && (ls.shortAlias || ls.name)) || 'Long-Short';
    }

    function serializeGroupFeeMap(feeMap) {
        return GT.datamodel.groups.serializeFeeMap(feeMap);
    }

    function serializeGroupVariant(group, fallbackName) {
        return GT.datamodel.groups.serializeVariant(group, fallbackName);
    }

    function collectDerivedPayloadForBatch(batch) {
        if (!GT.datamodel || !GT.datamodel.groups || typeof GT.datamodel.groups.collectDerivedPayloadForBatch !== 'function') return [];
        return GT.datamodel.groups.collectDerivedPayloadForBatch(batch, {
            getProductsForTester: productNamesForTester
        });
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
        var submissionId = getActiveSubmissionId();
        var factorAlias = getActiveFactorAlias();
        var all = GT.datamodel.groups.getAll ? (GT.datamodel.groups.getAll() || []) : [];
        var resultGroup = _lastGrossData && _lastGrossData[groupIndex] ? _lastGrossData[groupIndex] : null;
        var baseGroupIndex = resultGroup && resultGroup.derived && resultGroup.derived.base_group != null
            ? Number(resultGroup.derived.base_group)
            : Number(groupIndex);
        var expectedIndex = baseGroupIndex + 1;
        var matches = all.filter(function(group) {
            if (!group || group.isDerived) return false;
            if (Number(group.groupIndex) !== expectedIndex) return false;
            if (submissionId && String(group.testerId) !== String(submissionId)) return false;
            if (factorAlias && String(group.factorAlias || '') !== String(factorAlias || '')) return false;
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
        mountTab('config-derived');
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
        var submissionId = getActiveSubmissionId();
        if (!def || !submissionId) return null;
        if (def.baseGroup == null) return null;
        try {
            var resp = await GT.api.createDerivedGroup({
                submission_id: submissionId,
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

    // ──────────────────────────────────────────────
    // Detail overlay — 桥接到 metrics/detail_overlay/
    // ──────────────────────────────────────────────
    if (!GT.results.detailOverlay) GT.results.detailOverlay = {};
    GT.results.detailOverlay.hostRefs = {
        get _lastGrossData() { return _lastGrossData; },
        get _lastMetrics() { return _lastMetrics; },
        get _currentGroupDetailIndex() { return (typeof _currentGroupDetailIndex !== 'undefined') ? _currentGroupDetailIndex : null; },
        onRenderDerivedPanel: renderDerivedGroupsPanel,
    };

    // renderGroupDetail 委托给 tabs.js 版本
    function renderGroupDetail(detail, options) {
        if (GT.metrics && GT.metrics.detailOverlay && GT.metrics.detailOverlay.tabs && typeof GT.metrics.detailOverlay.tabs.renderGroupDetail === 'function') {
            GT.metrics.detailOverlay.tabs.renderGroupDetail(detail, options);
        }
    }

    function collectLongShortConfig(nGroups) {
        var def = (_longShortDefinitions && _longShortDefinitions[0]) || defaultLongShortDefinition();
        return buildLongShortPayload(def, nGroups);
    }

    function defaultLongShortDefinition() {
        if (GT.datamodel && GT.datamodel.ls_configs && GT.datamodel.ls_configs.defaultLegacyDefinition) {
            return GT.datamodel.ls_configs.defaultLegacyDefinition();
        }
        return { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' };
    }

    function buildLongShortPayload(def, nGroups) {
        return GT.datamodel.ls_configs.buildLegacyPayload(def, nGroups);
    }

    function defaultLongShortDefinition() {
        if (GT.datamodel && GT.datamodel.ls_configs && GT.datamodel.ls_configs.defaultLegacyDefinition) {
            return GT.datamodel.ls_configs.defaultLegacyDefinition();
        }
        return { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' };
    }

    function buildLongShortPayload(def, nGroups) {
        return GT.datamodel.ls_configs.buildLegacyPayload(def, nGroups);
    }

    function collectLongShortConfigs(nGroups) {
        if (!_longShortDefinitions.length) _longShortDefinitions = [defaultLongShortDefinition()];
        return GT.datamodel.ls_configs.buildLegacyPayloads(_longShortDefinitions, nGroups);
    }

    function buildGroupStructureKey(submissionId, factorAlias, nGroups, startDate, endDate) {
        return [
            String(submissionId || ''),
            String(factorAlias || ''),
            String(nGroups || ''),
            String(startDate || ''),
            String(endDate || '')
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

    async function collectGroupRunPayload(submissionId, factorAlias) {
        var statusSpan = document.getElementById('group_test_status');
        if (!submissionId || !factorAlias) {
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

        // Explicit group time inputs win over saved group datamodel values.
        var groupTimeRange = resolveGroupRunTimeRange(start_date, end_date);
        start_date = groupTimeRange.startDate;
        end_date = groupTimeRange.endDate;
        persistGroupTimeRangeToDatamodel(groupTimeRange.explicitStartDate, groupTimeRange.explicitEndDate);

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
            var submission = window.submissions ? window.submissions.find(function(s) { return String(s.id) === String(submissionId); }) : null;
            if (submission) {
                if (!start_date) start_date = submission.start_date;
                if (!end_date) end_date = submission.end_date;
            }
        }

        if (!start_date || !end_date) return { error: '请设置时间范围' };
        if (start_date > end_date) return { error: '起始日期不能晚于终止日期' };

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
                submission_id: submissionId,
                factor_alias: factorAlias,
                n_groups: n_groups,
                fee: fee,
                fee_map: fee_map,
                use_closetoday: use_closetoday,
                start_date: start_date,
                end_date: end_date,
                rebalance_mode: rebalance_mode,
                ls_config: collectLongShortConfig(n_groups),
                ls_configs: collectLongShortConfigs(n_groups),
                derived_groups: derivedPayload.length > 0 ? derivedPayload : null,
                group_fee_maps: group_fee_maps,
                structure_key: buildGroupStructureKey(submissionId, factorAlias, n_groups, start_date, end_date)
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
        });

        updateStrategyPanel(data.multi_session_active, data.rebalance_mode, data.multi_session_batches);
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
        var submissionId = getActiveSubmissionId();
        if (!def || !submissionId) return;
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
            submission_id: submissionId,
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

        var totalBatches = batches.length + (crossBatchLS.length > 0 ? 1 : 0);

        // 从第一个 batch 取 param 值（fee、时间等）
        var firstGroup = batches[0] && batches[0].groups[0];
        var firstTesterId = batches[0] && batches[0].testerId;
        var rebalance_mode = firstGroup ? (firstGroup.rebalanceMode || 'buy_and_hold') : 'buy_and_hold';
        var fallbackTesterId = firstTesterId || (firstGroup ? firstGroup.testerId : null);
        var resolvedRange = GT.utils.dates && GT.utils.dates.resolveGroupRunTimeRangeWithFallback
            ? GT.utils.dates.resolveGroupRunTimeRangeWithFallback(
                firstGroup ? (firstGroup.startDate || null) : null,
                firstGroup ? (firstGroup.endDate || null) : null,
                fallbackTesterId
              )
            : resolveGroupRunTimeRange(
                firstGroup ? (firstGroup.startDate || null) : null,
                firstGroup ? (firstGroup.endDate || null) : null
              );
        var start_date = resolvedRange.startDate;
        var end_date = resolvedRange.endDate;
        persistGroupTimeRangeToDatamodel(resolvedRange.explicitStartDate, resolvedRange.explicitEndDate);

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
        var submissionId = getActiveSubmissionId();
        if (!submissionId) {
            alert('请先选择一个 FactorTester 选项卡');
            return;
        }
        var factors = Array.isArray(window.factorList) ? window.factorList : [];
        if (!factors.length) {
            alert('暂无可运行因子');
            return;
        }
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
                var built = await collectGroupRunPayload(submissionId, factorAlias);
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

    // ---------- 缓存桥接（共享状态已迁移到 GT.core.cache） ----------
    // 本地桥接变量供 app.js 内其他函数直接使用
    var _groupResultsBySubmission = GT.core.cache ? GT.core.cache.getGroupResultsBySubmission() : {};
    var _activeGroupSubmissionId = GT.core.cache ? GT.core.cache.getActiveGroupSubmissionId() : null;
    var _activeGroupFactorBySubmission = GT.core.cache ? GT.core.cache.getActiveGroupFactorBySubmission() : {};
    var _derivedGroups = GT.core.cache ? GT.core.cache.getDerivedGroups() : [];
    var _derivedGroupSeq = GT.core.cache ? GT.core.cache.getDerivedGroupSeq() : 1;
    var _derivedGeneration = GT.core.cache ? GT.core.cache.getDerivedGeneration() : 0;
    var _currentGroupDetailIndex = GT.core.cache ? GT.core.cache.getCurrentGroupDetailIndex() : null;
    var _longShortDefinitions = GT.core.cache ? GT.core.cache.getLongShortDefinitions() : [defaultLongShortDefinition()];
    var _lastGroupStructureKey = GT.core.cache ? GT.core.cache.getLastGroupStructureKey() : null;
    var _lastGrossData = GT.core.cache ? GT.core.cache.getLastGrossData() : null;
    var _lastMetrics = GT.core.cache ? GT.core.cache.getLastMetrics() : null;
    var _lastTimestamps = GT.core.cache ? GT.core.cache.getLastTimestamps() : [];
    var _lastNgroups = GT.core.cache ? GT.core.cache.getLastNgroups() : 0;

    function cacheGroupResult(sid, fa, d) { return GT.core.cache && GT.core.cache.cacheGroupResult(sid, fa, d); }
    function getCachedGroupResult(sid, fa) { return GT.core.cache ? GT.core.cache.getCachedGroupResult(sid, fa) : null; }
    function clearCachedGroupResultsForSubmission(sid) { return GT.core.cache && GT.core.cache.clearCachedGroupResultsForSubmission(sid); }
    function updateActiveGroupCache() {
        var submissionId = getActiveSubmissionId();
        var factorAlias = getActiveFactorAlias();
        if (!submissionId || !factorAlias) return;
        var cached = getCachedGroupResult(submissionId, factorAlias);
        if (!cached) return;
        cached.groups = _lastGrossData;
        cached.metrics = _lastMetrics;
        cached._derivedGroups = _derivedGroups.map(function(item) { return Object.assign({}, item); });
        cached.structure_key = _lastGroupStructureKey;
    }
    function markGroupFactorStatus(sid, fa, s) { return GT.core.cache && GT.core.cache.markGroupFactorStatus(sid, fa, s); }
    function clearGroupFactorStatuses(sid) { return GT.core.cache && GT.core.cache.clearGroupFactorStatuses(sid); }

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
        if (P.config && P.config.derived) {
            GT_PANEL_REGISTRY.push({ name: 'config-derived', label: '品种筛选', containerId: 'config-derived', category: GT_TAB_CATEGORY.CONFIG, panel: P.config.derived });
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
        if (P.config && P.config.liquidity) {
            GT_PANEL_REGISTRY.push({ name: 'liquidity', label: '💧 流动性', containerId: 'config-liquidity', category: GT_TAB_CATEGORY.CONFIG, panel: P.config.liquidity });
        }

        _panelsRegistered = true;
    }

    // ---------- 手续费表：已迁移到 fee.js（GT.fee.*），此处仅保留桥接 ----------

    // 桥接：fee.js 中 close-today 变更回调
    GT.ui.onCloseTodayChanged = function() {
        if (_derivedGroups.length > 0) {
            _derivedGeneration++;
            refreshAllDerivedGroups(_derivedGeneration);
        }
    };

    function bindICModuleEvents() {
        // 分组测试结果按 submission + factor 缓存，切换选项卡时不主动清空。
    }

    // ---------- 初始化 ----------
    function init() {
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

            function _selectedEditIds() {
                if (_editSelection && _editSelection instanceof Set) return Array.from(_editSelection);
                if (_editSelection && Array.isArray(_editSelection)) return _editSelection.slice();
                if (_editSelection && typeof _editSelection === 'object') {
                    return Object.keys(_editSelection).filter(function(k) { return _editSelection[k]; });
                }
                return [];
            }

            function _resolvedConfigForDraft(group) {
                var base = null;
                if (group && group.isDerived && group.baseGroupId && GT.datamodel && GT.datamodel.groups) {
                    base = GT.datamodel.groups.get(group.baseGroupId);
                }
                var resolvedFee = null;
                if (group && group.isDerived && GT.datamodel && GT.datamodel.fee_strategy) {
                    try { resolvedFee = GT.datamodel.fee_strategy.resolveFee(group.id); } catch (e) { resolvedFee = null; }
                }
                return {
                    feeMode: resolvedFee ? (resolvedFee.mode || 'none') : (group && group.feeMode != null ? group.feeMode : (base && base.feeMode != null ? base.feeMode : 'none')),
                    feeRate: resolvedFee ? resolvedFee.rate : (group && group.feeRate != null ? group.feeRate : (base ? base.feeRate : null)),
                    feeMap: resolvedFee ? resolvedFee.feeMap : (group && group.feeMap != null ? group.feeMap : (base ? base.feeMap : null)),
                    feeSensitivity: resolvedFee && resolvedFee.sensitivity !== undefined ? resolvedFee.sensitivity : (group && group.feeSensitivity != null ? group.feeSensitivity : (base && base.feeSensitivity != null ? base.feeSensitivity : 1)),
                    useCloseToday: group && group.useCloseToday != null ? !!group.useCloseToday : !!(base && base.useCloseToday),
                    rebalanceMode: group && group.rebalanceMode != null ? group.rebalanceMode : (base && base.rebalanceMode ? base.rebalanceMode : 'each_period'),
                    liquidityMode: group && group.liquidityMode != null ? group.liquidityMode : (base && base.liquidityMode ? base.liquidityMode : 'infinite'),
                    liquidityPercent: group && group.liquidityPercent != null ? group.liquidityPercent : (base && base.liquidityPercent != null ? base.liquidityPercent : 100)
                };
            }

            function _buildDerivedAddDraftFromSelection() {
                var ids = _selectedEditIds();
                if (ids.length !== 1 || !GT.datamodel || !GT.datamodel.groups) return { addFlow: 'derived' };
                var selected = GT.datamodel.groups.get(ids[0]);
                if (!selected) return { addFlow: 'derived' };
                var draft = { addFlow: 'derived' };
                if (selected.isDerived) {
                    draft.preselectedParentDerivedId = selected.id;
                    draft.preselectedBaseGroupId = selected.baseGroupId;
                    // Only preselect products if the parent has its own productMask (override);
                    // otherwise leave empty so the child inherits from the parent chain.
                    var parentMask = selected.productMask || {};
                    var hasOwnMask = Object.keys(parentMask).length > 0;
                    if (hasOwnMask) {
                        draft.preselectedProducts = Object.keys(parentMask).filter(function(k) { return parentMask[k]; });
                    }
                } else {
                    draft.preselectedBaseGroupId = selected.id;
                }
                // Inherit resolved config from selected group (works for both base and derived)
                var cfg = _resolvedConfigForDraft(selected);
                Object.assign(draft, cfg);
                draft._inheritedConfigKeys = {};
                ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday', 'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(key) {
                    draft._inheritedConfigKeys[key] = true;
                });
                return draft;
            }

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
                    var selIds = _selectedEditIds();
                    var selCount = selIds.length;
                    if (_currentTab === 'config-derived') {
                        // In edit mode with config-derived tab, the user is modifying
                        // product selection of an existing derived group — show normal
                        // edit actions (save/cancel) instead of "create derived".
                    } else if (selCount === 1) {
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
                    _addDraft.liquidityMode = 'infinite';
                    _addDraft.liquidityPercent = 100;
                    _renderTabActions();
                    mountTab('add-base');
                } else if (addFlow === 'derived') {
                    // If no preselected parent (from _createDerivedFromSelection or +子), try active state
                    if (!_addDraft.preselectedBaseGroupId && !_addDraft.preselectedParentDerivedId) {
                        var activeDerivedId = GT.state && GT.state.getActiveDerivedNodeId ? GT.state.getActiveDerivedNodeId() : null;
                        if (activeDerivedId) {
                            _addDraft.preselectedParentDerivedId = activeDerivedId;
                            var activeDerived = GT.datamodel.groups && GT.datamodel.groups.get(activeDerivedId);
                            if (activeDerived) {
                                _addDraft.preselectedBaseGroupId = activeDerived.baseGroupId;
                                _addDraft.preselectedProducts = effectiveDerivedProductNames(activeDerived);
                                Object.assign(_addDraft, _resolvedConfigForDraft(activeDerived));
                                _addDraft._inheritedConfigKeys = { feeMode: true, feeRate: true, feeMap: true, feeSensitivity: true, useCloseToday: true, rebalanceMode: true, liquidityMode: true, liquidityPercent: true };
                            }
                        } else {
                            var activeBaseId = GT.state && GT.state.getActiveBaseGroupId ? GT.state.getActiveBaseGroupId() : null;
                            _addDraft.preselectedBaseGroupId = activeBaseId;
                            var activeBase = GT.datamodel.groups && GT.datamodel.groups.get(activeBaseId);
                            if (activeBase) {
                                Object.assign(_addDraft, _resolvedConfigForDraft(activeBase));
                                _addDraft._inheritedConfigKeys = { feeMode: true, feeRate: true, feeMap: true, feeSensitivity: true, useCloseToday: true, rebalanceMode: true, liquidityMode: true, liquidityPercent: true };
                            }
                        }
                    }
                    _renderTabActions();
                    mountTab('config-derived');
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
                    var REG = window.GT_CONFIG_REGISTRY;
                    if (REG && typeof REG.commitDirty === 'function') {
                        REG.commitDirty();
                    }
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

                // Product mask: only set if user explicitly narrowed selection; default empty = inherit all
                var derivedPanel = GT.panels.config && GT.panels.config.derived;
                var selectedProducts = (derivedPanel && typeof derivedPanel.getSelectedProducts === 'function')
                    ? derivedPanel.getSelectedProducts() : [];
                // Count total available products to know if user narrowed
                var allProducts = (derivedPanel && typeof derivedPanel.getAllProducts === 'function')
                    ? derivedPanel.getAllProducts() : [];

                var productMask = {};
                if (selectedProducts.length > 0 && selectedProducts.length < allProducts.length) {
                    for (var i = 0; i < selectedProducts.length; i++) {
                        productMask[selectedProducts[i]] = true;
                    }
                }

                var config = {
                    name: resolvedName,
                    isDerived: true,
                    baseGroupId: baseGroupId,
                    productMask: productMask,
                };
                ['feeMode', 'feeRate', 'feeMap', 'feeSensitivity', 'useCloseToday', 'rebalanceMode', 'liquidityMode', 'liquidityPercent'].forEach(function(key) {
                    var inherited = _addDraft._inheritedConfigKeys && _addDraft._inheritedConfigKeys[key];
                    if (!inherited && _addDraft[key] !== undefined) config[key] = _addDraft[key];
                });
                if (parentDerivedId) {
                    config.parentId = parentDerivedId;
                }

                try {
                    GT.datamodel.groups.add(config);
                } catch (err) {
                    alert('创建派生组失败: ' + (err && err.message || err));
                    return;
                }
                // Auto-expand parent derived node so the new child is visible
                if (parentDerivedId && GT.datamodel.groups) {
                    var parentNode = GT.datamodel.groups.get(parentDerivedId);
                    if (parentNode && parentNode._expanded === false) {
                        GT.datamodel.groups.toggleExpanded(parentDerivedId);
                    }
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
	                    // Check if any selected group is a derived group
	                    var selIds = _selectedEditIds();
	                    var hasDerived = selIds.some(function(sid) {
	                        var g = GT.datamodel.groups && GT.datamodel.groups.get(sid);
	                        return g && g.isDerived;
	                    });
	                    var visibleList = GT_PANEL_REGISTRY.filter(function(p) {
	                        if (p.category === L) return true;
	                        if (p.category === C && p.name === 'config-derived' && !hasDerived) return false;
	                        if (p.category === C) return true;
	                        return false;
	                    });
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
                var selIds = _selectedEditIds();
                if (selIds.length !== 1) {
                    alert('请选择 1 行来创建派生组');
                    return;
                }
                var draft = _buildDerivedAddDraftFromSelection();
                if (!draft.preselectedBaseGroupId && !draft.preselectedParentDerivedId) {
                    alert('无法识别选中的分组类型');
                    return;
                }

                _exitEditMode();
                _panelMode = 'add';
                _addDraft = draft;
                mountTab('config-derived');
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

                // If the user was editing product selection for a derived group,
                // save the productMask to the existing derived group.
                if (_currentTab === 'config-derived') {
                    var selIds = _selectedEditIds();
                    if (selIds.length === 1) {
                        var derivedPanel = GT.panels.config && GT.panels.config.derived;
                        if (derivedPanel && typeof derivedPanel.getSelectedProducts === 'function') {
                            var selectedProds = derivedPanel.getSelectedProducts();
                            var productMask = {};
                            for (var pi = 0; pi < selectedProds.length; pi++) {
                                productMask[selectedProds[pi]] = true;
                            }
                            try {
                                GT.datamodel.groups.update(selIds[0], { productMask: productMask });
                            } catch (e) {
                                alert('保存品种修改失败: ' + (e && e.message || e));
                                return;
                            }
                        }
                    }
                }
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
            GT.ui.updateAddDraft = function(patch) {
                if (!_addDraft) return;
                Object.assign(_addDraft, patch);
                if (_addDraft._inheritedConfigKeys && patch) {
                    Object.keys(patch).forEach(function(key) { delete _addDraft._inheritedConfigKeys[key]; });
                }
            };
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
                    visibleCategories = [L, C, A];
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
                        if (p.category === A) return p.addFlow === _addDraft.addFlow;
                        if (p.category === C && p.name === 'config-derived') return _addDraft.addFlow === 'derived';
                        return true;
                    });
                } else if (_panelMode === 'edit') {
                    // In edit mode, show LIST + CONFIG only (no ADD panels).
                    // But hide config-derived unless at least one selected group is a derived group.
                    var selIds = _selectedEditIds();
                    var hasDerived = selIds.some(function(sid) {
                        var g = GT.datamodel.groups && GT.datamodel.groups.get(sid);
                        return g && g.isDerived;
                    });
                    visibleList = visibleList.filter(function(p) {
                        if (p.category === A) return false;
                        if (p.name === 'config-derived' && !hasDerived) return false;
                        return true;
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
                if (_panelMode === 'edit' && tabName === 'config-derived') {
                    _addDraft = _buildDerivedAddDraftFromSelection();
                }

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
                statusSpan.innerHTML = '✓ 分组测试完成';
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
