/**
 * panels/actions.js — 分组测试面板 DOM 交互操作
 *
 * 负责：
 *   - 派生组面板渲染/绑定（renderDerivedGroupsPanel, bindDerivedGroupPanelEvents）
 *   - 长-短配置 UI（updateLongShortSummary, renderLongShortConfigList）
 *   - 面板工具函数（formatGroupProduct, fmtFeeRate, isRealFee 等）
 *   - 再平衡模式描述（updateRebalanceModeDescription）
 *
 * 挂载到 GT.panels.actions。所有函数通过 GT.panels.actions.* 访问。
 * 部分函数依赖 _lastGrossData / _lastMetrics，通过 GT.groupSettings.cache 读取。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) { console.warn('[panels.actions] GroupTest bootstrap missing'); return; }

    GT.panels = GT.panels || {};
    if (GT.panels.actions) { console.warn('[panels.actions] already loaded'); return; }

    var actions = {};

    function cache() {
        return GT.groupSettings && GT.groupSettings.cache ? GT.groupSettings.cache : null;
    }

    /* ════════════════════════════════════════════════════════════════
       工具函数
       ════════════════════════════════════════════════════════════════ */

    function escapeHtml(value) { return GT.escapeHTML(value); }

    actions.fmtFeeRate = function(value) {
        if (value == null || isNaN(value) || !isFinite(value)) return '—';
        var bp = value * 10000;
        return bp.toFixed(5) + ' bp';
    };

    actions.isRealFee = function(row) {
        return !!(row && row.product && row.product.fee && row.product.fee._is_real_fee);
    };

    actions.formatGroupProduct = function(product) {
        if (!product) return '—';
        if (typeof product === 'string') return product;
        var name = product.name || '';
        var desc = product.desc && product.desc !== name ? ' · ' + product.desc : '';
        return name + desc;
    };

    actions.formatGroupProducts = function(products) {
        return (products || []).map(actions.formatGroupProduct).join('、');
    };

    actions.escapeHtml = escapeHtml;

    /* ════════════════════════════════════════════════════════════════
       分组详情表格
       ════════════════════════════════════════════════════════════════ */

    actions.renderGroupDetailTable = function(rows, type) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        var html = '<table class="group-detail-table"><thead><tr><th>时间</th><th>收益</th><th>产品</th></tr></thead><tbody>';
        rows.forEach(function(row) {
            var d = new Date(row.timestamp);
            var time = isNaN(d.getTime()) ? row.timestamp : d.toLocaleString();
            html += '<tr><td>' + time + '</td><td>' + (row.return * 100).toFixed(3) + '%</td><td>' + actions.formatGroupProducts(row.products || []) + '</td></tr>';
        });
        return html + '</tbody></table>';
    };

    actions.renderGroupFrequency = function(rows, selectable) {
        if (!rows || !rows.length) return '<div class="group-detail-muted">暂无数据</div>';
        selectable = selectable !== false;
        var hasHighlight = false;
        var feeLabel = actions.isRealFee(rows[0]) ? ' (原始费率)' : '';
        var html = '';
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
                + '<td>' + actions.fmtFeeRate(meanRet) + '</td>'
                + '<td>' + actions.fmtFeeRate(fee.open) + '</td>'
                + '<td>' + actions.fmtFeeRate(fee.close_today) + '</td>'
                + '<td>' + actions.fmtFeeRate(fee.close_yesterday != null ? fee.close_yesterday : fee.close) + '</td>'
                + '<td>' + (row.count == null ? '—' : row.count) + '</td><td>' + (row.frequency == null ? '—' : (row.frequency * 100).toFixed(1) + '%') + '</td></tr>';
        });
        html += '</tbody></table>';
        return html;
    };

    /* ════════════════════════════════════════════════════════════════
       派生组面板
       ════════════════════════════════════════════════════════════════ */

    actions.productNamesForTester = function(testerId) {
        var subs = window.submissions || [];
        for (var i = 0; i < subs.length; i++) {
            if (String(subs[i].id) !== String(testerId)) continue;
            return (subs[i].products || []).map(function(product) {
                return typeof product === 'string' ? product : (product && (product.name || product.desc)) || '';
            }).filter(Boolean);
        }
        return [];
    };

    actions.effectiveDerivedProductNames = function(node, seen) {
        if (GT.groupSettings.groups && typeof GT.groupSettings.groups.effectiveProductNames === 'function') {
            return GT.groupSettings.groups.effectiveProductNames(node, {
                getProductsForTester: actions.productNamesForTester
            }, seen);
        }
        return [];
    };

    actions.groupDisplayKey = function(group, allGroups) {
        if (GT.groupSettings.groups && typeof GT.groupSettings.groups.displayKey === 'function') {
            return GT.groupSettings.groups.displayKey(group, allGroups);
        }
        if (!group) return '';
        return group.shortAlias || group.key || group.name || group.id || '';
    };

    actions.lsDisplayName = function(ls) {
        if (GT.groupSettings.lsConfigs && typeof GT.groupSettings.lsConfigs.displayName === 'function') {
            return GT.groupSettings.lsConfigs.displayName(ls);
        }
        return (ls && (ls.shortAlias || ls.name)) || 'Long-Short';
    };

    actions.serializeGroupFeeMap = function(feeMap) {
        return GT.groupSettings.groups.serializeFeeMap(feeMap);
    };

    actions.serializeGroupVariant = function(group, fallbackName) {
        return GT.groupSettings.groups.serializeVariant(group, fallbackName);
    };

    actions.collectSelectedDerivedProducts = function() {
        var names = [];
        document.querySelectorAll('.derived-product-checkbox:checked').forEach(function(cb) {
            var name = cb.getAttribute('data-product-name');
            if (name) names.push(name);
        });
        return names;
    };


    actions.findBaseGroupIdForResultGroup = function(groupIndex) {
        if (!GT.groupSettings.groups) return null;
        var sel = GT.panels && GT.panels.list && GT.panels.list.selection;
        var submissionId = sel && typeof sel.getFirstSubmissionId === 'function' ? sel.getFirstSubmissionId() : null;
        var factorAlias = sel && typeof sel.getFirstFactorAlias === 'function' ? sel.getFirstFactorAlias() : '';
        var all = GT.groupSettings.groups.getAll ? (GT.groupSettings.groups.getAll() || []) : [];
        var c = cache();
        var lastGrossData = c ? c.getLastGrossData() : null;
        var resultGroup = lastGrossData && lastGrossData[groupIndex] ? lastGrossData[groupIndex] : null;
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
        if (matches.length > 1 && lastGrossData && lastGrossData[groupIndex]) {
            var resultKey = lastGrossData[groupIndex].key;
            var byAlias = matches.filter(function(group) { return group.shortAlias === resultKey; });
            if (byAlias.length === 1) return byAlias[0].id;
        }
        return matches.length ? matches[0].id : null;
    };

    actions.makeUniqueGroupKey = function(name, ownId) {
        var c = cache();
        var lastMetrics = c ? c.getLastMetrics() : null;
        var base = name || ownId || '派生组';
        var key = base;
        var suffix = 2;
        while (lastMetrics && lastMetrics[key]) {
            key = base + ' #' + suffix++;
        }
        return key;
    };

    actions.removeGeneratedDerivedArtifacts = function(id) {
        var c = cache();
        var lastGrossData = c ? c.getLastGrossData() : null;
        var lastMetrics = c ? c.getLastMetrics() : null;
        var node = GT.groupSettings.groups ? GT.groupSettings.groups.get(id) : null;
        var key = node ? actions.groupDisplayKey(node) : null;
        if (lastGrossData) {
            lastGrossData = lastGrossData.filter(function(group) {
                return !(group && group.is_derived && group.derived && group.derived.id === id);
            });
            c.setLastGrossData(lastGrossData);
        }
        if (key && lastMetrics) {
            delete lastMetrics[key];
            c.setLastMetrics(lastMetrics);
        }
    };

    actions.defineDerivedGroup = function(groupIndex) {
        var productNames = actions.collectSelectedDerivedProducts();
        if (!productNames.length) {
            alert('请先勾选至少一个入组产品。');
            return;
        }
        var baseGroupId = actions.findBaseGroupIdForResultGroup(groupIndex);
        if (!baseGroupId) {
            alert('未找到对应基础组，请先在左侧面板创建分组组合。');
            return;
        }
        var productMask = {};
        productNames.forEach(function(pn) { productMask[pn] = true; });
        var newId;
        try {
            newId = GT.groupSettings.groups.add({
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
        actions.renderDerivedGroupsPanel(groupIndex);
    };

    actions.renderDerivedGroupsPanel = function(groupIndex) {
        var el = document.getElementById('group-derived-groups-panel');
        if (!el) return;

        var baseGroupId = actions.findBaseGroupIdForResultGroup(groupIndex);
        var derivedNodes = [];
        if (baseGroupId && GT.groupSettings.groups) {
            var allNodes = GT.groupSettings.groups.getAll();
            for (var i = 0; i < allNodes.length; i++) {
                if (allNodes[i].isDerived && allNodes[i].baseGroupId === baseGroupId) {
                    derivedNodes.push(allNodes[i]);
                }
            }
        }

        var c = cache();
        var grossData = c ? c.getLastGrossData() : [];

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
                var alias = actions.groupDisplayKey(node);
                var products = actions.effectiveDerivedProductNames(node);
                var generated = grossData.some(function(g) { return g && g.is_derived && g.derived && g.derived.id === node.id; });

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
        actions.bindDerivedGroupPanelEvents(groupIndex);
    };

    actions.bindDerivedGroupPanelEvents = function(groupIndex) {
        var selectAll = document.getElementById('derived-select-all-products');
        if (selectAll) {
            selectAll.addEventListener('change', function() {
                document.querySelectorAll('.derived-product-checkbox').forEach(function(cb) {
                    cb.checked = selectAll.checked;
                });
            });
        }
        var defineBtn = document.getElementById('derived-group-define-btn');
        if (defineBtn) defineBtn.addEventListener('click', function() { actions.defineDerivedGroup(groupIndex); });

        var quickBtn = document.getElementById('derived-group-quick-define-btn');
        if (quickBtn) {
            quickBtn.addEventListener('click', function() {
                document.querySelectorAll('.derived-product-checkbox').forEach(function(cb) {
                    var row = cb.closest('tr');
                    if (row && row.hasAttribute('data-highlight')) {
                        cb.checked = true;
                    }
                });
                actions.defineDerivedGroup(groupIndex);
            });
        }

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
            btn.addEventListener('click', function() {
                if (GT.core.runTest && typeof GT.core.runTest.generateDerivedGroup === 'function') {
                    GT.core.runTest.generateDerivedGroup(btn.getAttribute('data-derived-id'));
                }
            });
        });
        document.querySelectorAll('.derived-group-delete-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                if (GT.core.runTest && typeof GT.core.runTest.deleteDerivedGroup === 'function') {
                    GT.core.runTest.deleteDerivedGroup(btn.getAttribute('data-derived-id'));
                }
            });
        });
    };

    actions.openAddDerivedFromDetail = function(groupIndex) {
        var productNames = actions.collectSelectedDerivedProducts();
        if (!productNames.length) {
            alert('请先勾选至少一个入组产品。');
            return;
        }
        var baseGroupId = actions.findBaseGroupIdForResultGroup(groupIndex);
        if (!baseGroupId) {
            alert('无法匹配当前结果对应的基础组，请从分组列表中选择基础组后新建派生组。');
            return;
        }
        var input = document.getElementById('derived-group-name-input');
        var defaultName = '第' + (groupIndex + 1) + '组精选';
        var name = (input && input.value ? input.value.trim() : '') || defaultName;
        var draft = {
            addFlow: 'derived',
            preselectedBaseGroupId: baseGroupId,
            preselectedProducts: productNames,
            name: name,
            defaultName: name,
        };
        if (GT.modes && GT.tabs) {
            GT.modes.enterAdd('derived');
            GT.modes.setAddDraft(draft);
            GT.tabs.mountTab('config-derived');
            GT.tabs.renderTabActions();
        }
        var overlay = document.getElementById('group-detail-overlay');
        if (overlay) overlay.classList.remove('open');
    };

    /* ════════════════════════════════════════════════════════════════
       Long-Short 配置
       ════════════════════════════════════════════════════════════════ */

    actions.updateLongShortSummary = function() {
        var el = document.getElementById('long-short-summary');
        if (!el) return;
        var c = cache();
        var definitions = c ? c.getLongShortDefinitions() : [];
        if (!definitions.length) definitions = [GT.groupSettings.lsConfigs ? GT.groupSettings.lsConfigs.defaultLegacyDefinition() : { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' }];
        el.textContent = definitions.map(function(def) {
            return (def.name || 'Long-Short') + ': L(' + (def.longGroups || '1') + ') / S(' + (def.shortGroups || '末组') + ')';
        }).join('；');
    };

    actions.renderLongShortConfigList = function() {
        var el = document.getElementById('long-short-config-list');
        if (!el) return;
        var c = cache();
        var definitions = c ? c.getLongShortDefinitions() : [];
        if (!definitions.length) definitions = [GT.groupSettings.lsConfigs ? GT.groupSettings.lsConfigs.defaultLegacyDefinition() : { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' }];
        var html = '';
        definitions.forEach(function(def) {
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
                var lsId = row.getAttribute('data-ls-id');
                var c = cache();
                var definitions = c ? c.getLongShortDefinitions() : [];
                var def = definitions.find(function(item) { return item.id === lsId; });
                if (def) {
                    def[input.getAttribute('data-field')] = input.value;
                    c && c.setLongShortDefinitions(definitions);
                    actions.updateLongShortSummary();
                }
            });
        });
        el.querySelectorAll('.long-short-delete-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var lsId = btn.getAttribute('data-ls-id');
                var c = cache();
                var definitions = c ? c.getLongShortDefinitions() : [];
                definitions = definitions.filter(function(item) { return item.id !== lsId; });
                if (!definitions.length) definitions = [GT.groupSettings.lsConfigs ? GT.groupSettings.lsConfigs.defaultLegacyDefinition() : { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' }];
                c && c.setLongShortDefinitions(definitions);
                actions.renderLongShortConfigList();
                actions.updateLongShortSummary();
            });
        });
    };

    /* ════════════════════════════════════════════════════════════════
       再平衡模式描述
       ════════════════════════════════════════════════════════════════ */

    actions.updateRebalanceModeDescription = function() {
        var select = document.getElementById('rebalance_mode');
        var target = document.getElementById('rebalance_mode_description');
        if (!select || !target) return;
        var descriptions = {
            each_period: '每一期都把当前组内成员重新调成等权。适合比较"每期按最新排序重新建仓"的理论表现，换手通常最高。',
            buy_and_hold: '组内成员不变时保持原有持仓比例；只有成员进出组时才交易。更接近低换手的持有逻辑，也是默认模式。',
            recycle: '留存成员的持仓不动；有成员退出时，把释放出的资金优先分给新进成员。适合观察"旧仓尽量不动、只用退出资金补新仓"的过渡方式。',
        };
        target.textContent = descriptions[select.value] || '';
    };

    /* ════════════════════════════════════════════════════════════════
       暴露
       ════════════════════════════════════════════════════════════════ */

    GT.panels.actions = actions;
})();
