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
        var selectionLabel = batch.product_path_selection_label || batch.product_path_selection_id || '';
        var factorAlias = batch.factor_alias || batch.factorAlias || '';
        var groupText = batch.n_groups ? (' / ' + batch.n_groups + '组') : '';
        return (batchIndex ? ('Batch ' + batchIndex + ' · ') : '')
            + [selectionLabel, factorAlias].filter(Boolean).join(' / ')
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
        var runtimeRows = Array.isArray(data.runtime_info_rows) ? data.runtime_info_rows : [];
        for (var ri = 0; ri < runtimeRows.length; ri++) {
            var item = runtimeRows[ri] || {};
            rows.push({
                type: item.type || '运行信息',
                status: item.status || _runtimeStatusLabel(item.level),
                detail: item.detail || item.message || '',
                detailHtml: item.detailHtml || '',
            });
        }
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
    }

    function _pushRunSettingRows(rows, data) {
        var parts = _silentDefaultParts(data && data.silent_default_settings);
        if (parts.length) {
            rows.push({
                type: '当前运行配置',
                status: '默认',
                detailHtml: '<div class="gt-strategy-chip-list">' + parts.map(function(part) {
                    var chipHtml = (window.ChipRenderer && typeof window.ChipRenderer.chipHtml === 'function')
                        ? window.ChipRenderer.chipHtml(
                            { chip_template: '{label}: {value}' },
                            { valueOf: function(k) { return k === 'label' ? part.label : part.value; },
                              escapeHTML: GT.escapeHTML,
                              renderChipHtml: GT.backendSettings && typeof GT.backendSettings.renderChipHtml === 'function'
                                  ? GT.backendSettings.renderChipHtml : undefined }
                        )
                        : (GT.escapeHTML(part.label) + ': ' + GT.escapeHTML(part.value));
                    return '<span class="gt-backend-chip">' + chipHtml + '</span>';
                }).join('') + '</div>',
            });
        }
        var fallbacks = Array.isArray(data && data.setting_fallbacks)
            ? data.setting_fallbacks
            : [];
        if (!fallbacks.length) return;
        rows.push({
            type: '默认值替换',
            status: '已使用默认值',
            detailHtml: (data.setting_fallback_warning ? GT.escapeHTML(data.setting_fallback_warning) : '')
                + '<div class="gt-strategy-chip-list">' + fallbacks.map(function(item) {
                var label = String(item.setting_key || item.module || '设置');
                var value = String(item.requested_value) + ' → ' + String(item.applied_value);
                var chipHtml = (window.ChipRenderer && typeof window.ChipRenderer.chipHtml === 'function')
                    ? window.ChipRenderer.chipHtml(
                        { chip_template: '{label}: {value}' },
                        { valueOf: function(k) { return k === 'label' ? label : value; },
                          escapeHTML: GT.escapeHTML,
                          renderChipHtml: GT.backendSettings && typeof GT.backendSettings.renderChipHtml === 'function'
                              ? GT.backendSettings.renderChipHtml : undefined }
                    )
                    : (GT.escapeHTML(label) + ': ' + GT.escapeHTML(value));
                return '<span class="gt-backend-chip">' + chipHtml + '</span>';
            }).join('') + '</div>',
        });
    }

    function _valueLabel(map, value) {
        var key = value === undefined || value === null || value === '' ? '默认' : String(value);
        return map[key] || key;
    }

    function _silentDefaultParts(items) {
        if (!Array.isArray(items)) return [];
        return items.map(function(item) {
            if (!item) return null;
            var label = String(item.label || item.setting_key || item.module || '设置');
            var value = item.value_label !== undefined && item.value_label !== null
                ? String(item.value_label)
                : item.value !== undefined && item.value !== null
                ? String(item.value)
                : String(item.applied_value !== undefined ? item.applied_value : '');
            if (!value) return null;
            return { label: label, value: value };
        }).filter(Boolean);
    }

    function _rowHtml(row) {
        return '<tr class="gt-strategy-row">'
            + '<td class="gt-strategy-type-cell">' + GT.escapeHTML(row.type || '') + '</td>'
            + '<td class="gt-strategy-status-cell">' + GT.escapeHTML(row.status || '') + '</td>'
            + '<td class="gt-strategy-detail-cell">' + (row.detailHtml || GT.escapeHTML(row.detail || '')) + '</td>'
            + '</tr>';
    }

    function _runtimeStatusLabel(level) {
        if (level === 'warning') return '提示';
        if (level === 'error') return '异常';
        return '信息';
    }

    function _ensureTable() {
        var layer = document.getElementById('gt-layer-strategy');
        var head = document.getElementById('gt-strategy-head');
        var body = document.getElementById('gt-strategy-body');
        if (!layer || !head || !body) return null;
        layer.style.display = '';
        if (!head.innerHTML) {
            head.innerHTML = '<tr><th class="gt-strategy-type-cell">类型</th><th class="gt-strategy-status-cell">状态</th><th class="gt-strategy-detail-cell">说明</th></tr>';
        }
        return body;
    }

    function pushRuntimeInfo(row) {
        var body = _ensureTable();
        if (!body) return;
        var normalized = row || {};
        var key = normalized.code || normalized.detail || normalized.message || JSON.stringify(normalized);
        if (!body._gtRuntimeInfoKeys) body._gtRuntimeInfoKeys = {};
        if (body._gtRuntimeInfoKeys[key]) return;
        body._gtRuntimeInfoKeys[key] = true;
        body.insertAdjacentHTML('beforeend', _rowHtml({
            type: normalized.type || '运行信息',
            status: normalized.status || _runtimeStatusLabel(normalized.level),
            detail: normalized.detail || normalized.message || '',
            detailHtml: normalized.detailHtml || '',
        }));
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
            : [{ index: 0, product_path_selection_label: '当前产品路径', factor_alias: '当前因子', n_groups: null }];
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
        pushRuntimeInfo: pushRuntimeInfo,
    };
})();
