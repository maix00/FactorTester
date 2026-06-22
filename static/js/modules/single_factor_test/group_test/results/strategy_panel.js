/**
 * Strategy summary panel for group-test results.
 *
 * Renders MultiSession batch summaries and capital shortage diagnostics.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.results = GT.results || {};

    function hide(layer, status, notice, head, body) {
        layer.style.display = 'none';
        if (status) status.textContent = '';
        if (notice) notice.innerHTML = '';
        if (notice) notice.style.display = 'none';
        head.innerHTML = '';
        body.innerHTML = '';
    }

    function batchLabel(batch) {
        var batchIndex = Number.isFinite(Number(batch.index)) ? (Number(batch.index) + 1) : '';
        var testerAlias = batch.tester_alias || batch.testerAlias || batch.submission_id || '';
        var factorAlias = batch.factor_alias || batch.factorAlias || '';
        var groupText = batch.n_groups ? (' / ' + batch.n_groups + '组') : '';
        return (batchIndex ? ('Batch ' + batchIndex + ' · ') : '')
            + [testerAlias, factorAlias].filter(Boolean).join(' / ')
            + groupText;
    }

    function _formatMissingProducts(batch) {
        var products = Array.isArray(batch && batch.missing_products)
            ? batch.missing_products.filter(Boolean)
            : [];
        if (!products.length) return '';
        var total = Number(batch.missing_product_count || products.length);
        var sample = products.slice(0, 8).join('、');
        if (total > products.length || products.length > 8) sample += ' 等';
        return '触发品种：' + sample + '（' + total + ' 个品种存在非头部缺 bar/交易时段差异）';
    }

    function _pushCapitalRows(rows, data) {
        if (!data) return;
        _pushRunSettingRows(rows, data);
        if (data.capital_warning) {
            rows.push({
                type: '资金约束',
                status: '提示',
                detail: data.capital_warning,
            });
        }
        if (data.market_rule_warning) {
            rows.push({
                type: '市场规则',
                status: '近似',
                detail: data.market_rule_warning,
            });
        }
        var diag = data.capital_diagnostics || {};
        var details = [];
        if (diag.blocked_group_count !== undefined && diag.blocked_group_count !== null) {
            details.push('未开仓组数：' + String(diag.blocked_group_count));
        }
        var blocked = Array.isArray(diag.blocked_groups) ? diag.blocked_groups : [];
        if (blocked.length > 0) {
            var sample = blocked[0];
            var sampleParts = [];
            if (sample.group_name) sampleParts.push('组 ' + String(sample.group_name));
            if (sample.cheapest_product_name) sampleParts.push('最便宜品种 ' + String(sample.cheapest_product_name));
            if (sample.cheapest_required_capital !== undefined) sampleParts.push('需求约 ' + String(Math.round(Number(sample.cheapest_required_capital))));
            if (sample.budget_per_product !== undefined) sampleParts.push('预算约 ' + String(Math.round(Number(sample.budget_per_product))));
            if (sampleParts.length) details.push(sampleParts.join('，'));
        }
        if (details.length) {
            rows.push({
                type: '资金约束',
                status: '诊断',
                detail: details.join('；'),
            });
        }
        if (data.setting_fallback_warning) {
            var fallbackDetails = [];
            var fallbacks = Array.isArray(data.setting_fallbacks) ? data.setting_fallbacks : [];
            if (fallbacks.length) {
                var first = fallbacks[0];
                fallbackDetails.push(
                    String(first.module || first.setting_key || '设置')
                    + ': ' + String(first.requested_value)
                    + ' → ' + String(first.applied_value)
                );
                if (fallbacks.length > 1) fallbackDetails.push('等 ' + fallbacks.length + ' 项');
            }
            rows.push({
                type: '引擎设置',
                status: '已替换',
                detail: data.setting_fallback_warning + (fallbackDetails.length ? ' ' + fallbackDetails.join('，') : ''),
            });
        }
    }

    function _valueLabel(map, value) {
        var key = value === undefined || value === null || value === '' ? '默认' : String(value);
        return map[key] || key;
    }

    function _uniqueValues(settingsByGroup, key) {
        var values = {};
        Object.keys(settingsByGroup || {}).forEach(function(groupId) {
            var item = settingsByGroup[groupId] || {};
            if (groupId.indexOf('long-short:') === 0) return;
            if (item[key] === undefined || item[key] === null || item[key] === '') return;
            values[String(item[key])] = true;
        });
        return Object.keys(values);
    }

    function _formatUnique(settingsByGroup, key, labels) {
        var values = _uniqueValues(settingsByGroup, key);
        if (!values.length) return '';
        if (values.length === 1) return _valueLabel(labels || {}, values[0]);
        return values.map(function(value) { return _valueLabel(labels || {}, value); }).join(' / ');
    }

    function _pushRunSettingRows(rows, data) {
        var settings = data && data.backtest_settings || {};
        var groups = settings.groups || {};
        if (!groups || !Object.keys(groups).length) return;
        var engine = settings.engine || (data.engine_result && data.engine_result.engine) || '';
        var allocation = _formatUnique(groups, 'allocation_policy', {
            inverse_volatility: '等风险',
            equal_notional: '等市值',
            equal_margin: '等保证金',
        });
        var trigger = _formatUnique(groups, 'rebalance_trigger', {
            on_factor_signal: '因子信号事件',
            membership_change: '成员变化事件',
            scheduled: '日历计划',
        });
        var position = _formatUnique(groups, 'position_policy', {
            rebalance_to_target: '按目标调仓',
            buy_and_hold: '买入持有',
        });
        var fee = _formatUnique(groups, 'fee_mode', {
            none: '无费用',
            market: '市场费率',
            custom: '自定义费率',
        });
        var margin = _formatUnique(groups, 'margin_mode', {
            none: '无保证金约束',
            market: '市场保证金',
        });
        var liquidity = _formatUnique(groups, 'liquidity_mode', {
            infinite: '无限流动性',
            volume_participation: '成交量参与率',
        });
        var participation = _formatUnique(groups, 'participation_rate', {});
        var parts = [];
        function item(label, value) {
            if (!value) return;
            parts.push({ label: label, value: value });
        }
        item('引擎', _valueLabel({native: 'Native', backtrader: 'Backtrader', qlib: 'Qlib', zipline: 'Zipline', rqalpha: 'RQAlpha'}, engine));
        item('目标分配', allocation);
        item('触发', trigger);
        item('持仓', position);
        item('费用', fee);
        item('保证金', margin);
        item('流动性', liquidity + (liquidity === '成交量参与率' && participation ? ' ' + participation : ''));
        if (!parts.length) return;
        rows.push({
            type: '当前运行配置',
            status: '默认',
            detailHtml: '<div class="gt-strategy-chip-list">' + parts.map(function(part) {
                var chipHtml = GT.backendSettings && typeof GT.backendSettings.renderChipHtml === 'function'
                    ? GT.backendSettings.renderChipHtml(part.label, part.value)
                    : (GT.escapeHTML(part.label) + ': ' + GT.escapeHTML(part.value));
                return '<span class="gt-backend-chip">' + chipHtml + '</span>';
            }).join('') + '</div>',
        });
    }

    function _rowHtml(row) {
        return '<tr class="gt-strategy-row">'
            + '<td class="gt-strategy-type-cell">' + GT.escapeHTML(row.type || '') + '</td>'
            + '<td class="gt-strategy-status-cell">' + GT.escapeHTML(row.status || '') + '</td>'
            + '<td class="gt-strategy-detail-cell">' + (row.detailHtml || GT.escapeHTML(row.detail || '')) + '</td>'
            + '</tr>';
    }

    function render(multiSessionActive, multiSessionBatches, capitalWarningData) {
        var layer = document.getElementById('gt-layer-strategy');
        var status = document.getElementById('gt-strategy-status');
        var notice = document.getElementById('gt-strategy-notice');
        var head = document.getElementById('gt-strategy-head');
        var body = document.getElementById('gt-strategy-body');
        if (!layer || !head || !body) return;

        var rows = [];
        var hasMultiSession = !!multiSessionActive;
        var batches = Array.isArray(multiSessionBatches) && multiSessionBatches.length > 0
            ? multiSessionBatches
            : [{ index: 0, tester_alias: '当前测试器', factor_alias: '当前因子', n_groups: null }];
        if (hasMultiSession) {
            for (var bi = 0; bi < batches.length; bi++) {
                var batch = batches[bi];
                var productText = _formatMissingProducts(batch);
                var detail = '市场日历检测到持仓池成员存在异步交易时段：不可交易成员沿用持仓，可交易成员按当前切片参与资金分配；分组测试会额外记录组内 membership 对资金分配的影响。';
                if (productText) detail += ' ' + productText;
                rows.push({
                    type: batches.length > 1 ? (batchLabel(batch) || 'MultiSession 批次') : '多交易时段',
                    status: '按策略设置',
                    detail: detail,
                });
            }
        }
        _pushCapitalRows(rows, capitalWarningData);
        if (!rows.length) {
            hide(layer, status, notice, head, body);
            return;
        }

        layer.style.display = '';
        if (status) {
            status.textContent = !hasMultiSession
                ? ''
                : batches.length > 1
                ? ('检测到 ' + batches.length + ' 个 MultiSession 批次')
                : '多交易时段处理已启用';
        }
        if (notice) {
            notice.innerHTML = '';
            notice.style.display = 'none';
        }
        head.innerHTML = '<tr><th class="gt-strategy-type-cell">类型</th><th class="gt-strategy-status-cell">状态</th><th class="gt-strategy-detail-cell">说明</th></tr>';
        body.innerHTML = rows.map(_rowHtml).join('');
    }

    // 从 app.js 桥接：由 applyGroupTestResult 调用
    function updatePanel(multiSessionActive, multiSessionBatches, capitalWarningData) {
        render(multiSessionActive, multiSessionBatches, capitalWarningData);
    }

    GT.results.strategyPanel = {
        render: render,
        update: updatePanel,
    };
})();
