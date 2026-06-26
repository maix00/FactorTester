/**
 * panels/group_chip_list.js — "chip-list" 组件：候选列表 + 管理按钮
 *
 * 与 tab/chip/content 三件套里的小型摘要 chip 是两个不同的概念：
 *   - chip：摘要型小标签（保持不变，仍在大多数地方使用）
 *   - chip-list（本文件）：候选项逐条列出 + 管理入口，目前只用于
 *     "新建/编辑分组" 面板的产品路径栏与因子栏。
 *
 * 不依赖、不修改 product_path_selection_products.js 的现有信息层实现，只是复用它
 * 展示候选项详情（点击候选项打开既有 overlay）。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    GT.panels = GT.panels || {};

    function escapeHTML(str) { return GT.escapeHTML(str); }

    function selectionId(selection) {
        var utils = window.ProductPathSelectionUtils;
        return utils && utils.selectionId ? utils.selectionId(selection)
            : (selection ? String(selection.product_path_selection_id || selection.id || selection.selection_id || '') : '');
    }

    function selectionDisplayLabel(selection) {
        var utils = window.ProductPathSelectionUtils;
        if (utils && utils.selectionDisplayLabel) return utils.selectionDisplayLabel(selection);
        return selection ? (selection.product_group || selection.label || selection.name || selectionId(selection)) : '';
    }

    /**
     * @param {HTMLElement} container
     * @param {Object} options
     *   - selections: Array — candidate product-path selections
     *   - current: Object|null — currently selected one
     *   - onSelect: function(selection) — called when a candidate row is clicked
     *   - manageScope: { getCurrent: fn, setCurrent: fn(selection) } — drives the
     *     "管理" panel; scoped to a draft or a real group (never to page local-settings)
     *   - manageOpen: boolean — caller-owned toggle state (survives re-renders)
     *   - onToggleManage: function(nextOpen) — caller persists the toggle and re-renders
     */
    function _productPathChipHtml(sel) {
        var label = selectionDisplayLabel(sel) || '未命名';
        if (GT.backendSettings && typeof GT.backendSettings.renderChipHtml === 'function') {
            return GT.backendSettings.renderChipHtml('产品路径', label);
        }
        return escapeHTML(label);
    }

    function renderProductPathChipList(container, options) {
        options = options || {};
        var selections = options.selections || [];
        var current = options.current || null;
        var currentId = selectionId(current);
        var manageOpen = !!options.manageOpen;

        var html = '';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;">';
        html += '<span style="display:flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:#475467;">产品路径';
        html += '<span class="gt-chiplist-title-chip" data-chip-kind="product_path"></span>';
        html += '</span>';
        html += '<button type="button" class="gt-chiplist-manage-btn" data-kind="product_path" style="height:22px;padding:0 8px;border:1px solid #cbd5e1;border-radius:4px;background:' + (manageOpen ? '#e7f1ff' : '#fff') + ';color:#475569;font-size:11px;cursor:pointer;">' + (manageOpen ? '完成' : '管理') + '</button>';
        html += '</div>';

        if (!current) {
            html += '<div style="margin-bottom:6px;font-size:12px;color:#c2410c;">未选择产品路径</div>';
        }

        if (manageOpen) {
            html += '<div class="gt-chiplist-manage-host" data-kind="product_path" style="border:1px solid #e5e7eb;border-radius:6px;min-height:120px;"></div>';
        } else {
            html += '<div style="max-height:260px;overflow:auto;border:1px solid #e8eaed;border-radius:6px;">';
            if (!selections.length) {
                html += '<div style="color:#888;font-size:12px;padding:14px;text-align:center;">暂无产品路径候选，请点击"管理"新增</div>';
            } else {
                for (var i = 0; i < selections.length; i++) {
                    var sel = selections[i];
                    var sid = selectionId(sel);
                    var isActive = !!sid && sid === currentId;
                    html += '<div class="gt-chiplist-row" data-kind="product_path" data-selection-id="' + escapeHTML(sid) + '"'
                        + ' style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:5px 8px;cursor:pointer;'
                        + (isActive ? 'background:#e8f4fd;' : '')
                        + 'border-bottom:1px solid #f0f2f5;">';
                    // chip：点击弹出 info overlay（stopPropagation 阻止触发行选中）
                    html += '<span class="gt-backend-chip gt-chiplist-chip" data-kind="product_path" data-selection-id="' + escapeHTML(sid) + '"'
                        + ' style="cursor:pointer;max-width:calc(100% - 24px);">'
                        + _productPathChipHtml(sel) + '</span>';
                    // 选中标记：行尾部，不在 chip 内
                    html += '<span style="flex-shrink:0;font-size:11px;color:' + (isActive ? '#0078d4' : '#ccc') + ';min-width:12px;text-align:center;">' + (isActive ? '✓' : '') + '</span>';
                    html += '</div>';
                }
            }
            html += '</div>';
        }

        container.innerHTML = html;

        // 标题 chip 用 ChipRenderer.render（DOM 模式，不再手动拼 HTML）
        var titleHost = container.querySelector('.gt-chiplist-title-chip[data-chip-kind="product_path"]');
        if (titleHost && window.ChipRenderer && GT.backendSettings) {
            var store = GT.backendSettings.ensureGtLocalStore ? GT.backendSettings.ensureGtLocalStore() : null;
            if (current && store) {
                // 把 current product_path_selection_id 写入 store，让 ChipRenderer 取值
                store.set('product_path_selection', current);
                window.ChipRenderer.render(titleHost, {
                    chips: [{
                        key: 'product_path_selection',
                        chip_template: '产品路径: {label}',
                        source_keys: ['product_path_selection'],
                        value_resolvers: { label: '_pp_display_label' },
                        category: 'identity',
                    }],
                    store: store,
                    resolvers: {
                        _pp_display_label: function() {
                            return selectionDisplayLabel(current) || '已选';
                        },
                    },
                    escapeHTML: escapeHTML,
                    renderChipHtml: GT.backendSettings.renderChipHtml,
                });
            } else {
                titleHost.innerHTML = '';
            }
        }

        var manageBtn = container.querySelector('.gt-chiplist-manage-btn[data-kind="product_path"]');
        if (manageBtn) {
            manageBtn.addEventListener('click', function() {
                if (typeof options.onToggleManage === 'function') options.onToggleManage(!manageOpen);
            });
        }

        if (manageOpen) {
            var host = container.querySelector('.gt-chiplist-manage-host[data-kind="product_path"]');
            if (host && GT.backendSettings && typeof GT.backendSettings.renderProductPathManager === 'function' && options.manageScope) {
                GT.backendSettings.renderProductPathManager(host, options.manageScope);
            }
            return;
        }

        // 行点击 → 选中（排除 chip 上的点击）
        container.querySelectorAll('.gt-chiplist-row[data-kind="product_path"]').forEach(function(row) {
            row.addEventListener('click', function(e) {
                // 点击 chip 区域 → 只弹 overlay，不选中
                if (e.target.closest('.gt-chiplist-chip')) return;
                var sid = row.getAttribute('data-selection-id');
                var found = null;
                for (var i = 0; i < selections.length; i++) {
                    if (selectionId(selections[i]) === sid) { found = selections[i]; break; }
                }
                if (!found) return;
                if (typeof options.onSelect === 'function') options.onSelect(found);
            });
        });

        // chip 点击 → 弹出 info overlay
        container.querySelectorAll('.gt-chiplist-chip[data-kind="product_path"]').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var sid = chip.getAttribute('data-selection-id');
                var found = null;
                for (var i = 0; i < selections.length; i++) {
                    if (selectionId(selections[i]) === sid) { found = selections[i]; break; }
                }
                if (!found) return;
                if (GT.overlays && GT.overlays.productPathSelectionProducts && GT.backendSettings) {
                    GT.overlays.productPathSelectionProducts.open(
                        GT.backendSettings.productPathSelectionLabel(found),
                        GT.backendSettings.productPathSelectionProducts(found),
                        found
                    );
                }
            });
        });
    }

    /**
     * @param {HTMLElement} container
     * @param {Object} options
     *   - factors: Array — window.factorList entries ({alias, latex, backend_fields, param_defs, ...})
     *   - selected: string|Array<string> — currently selected alias(es)
     *   - multiple: boolean — true allows toggling several (add-flow); false is single-select (edit-flow)
     *   - onToggle: function(alias) — called when a candidate row is clicked
     */
    function _factorChipHtml(alias) {
        if (GT.backendSettings && typeof GT.backendSettings.renderChipHtml === 'function') {
            return GT.backendSettings.renderChipHtml('因子', alias);
        }
        return escapeHTML(alias);
    }

    function renderFactorChipList(container, options) {
        options = options || {};
        var factors = options.factors || [];
        var multiple = !!options.multiple;
        var selected = options.selected;
        var selectedSet = {};
        if (multiple) {
            (selected || []).forEach(function(alias) { selectedSet[alias] = true; });
        } else if (selected) {
            selectedSet[selected] = true;
        }

        var html = '';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;">';
        html += '<span style="display:flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:#475467;">因子' + (multiple ? ' <span style="color:red;">*</span>' : '');
        html += '<span class="gt-chiplist-title-chip" data-chip-kind="factor"></span>';
        html += '</span>';
        html += '</div>';

        html += '<div style="max-height:260px;overflow:auto;border:1px solid #e8eaed;border-radius:6px;">';
        if (!factors.length) {
            html += '<div style="color:#888;font-size:12px;padding:14px;text-align:center;">暂无因子候选</div>';
        } else {
            for (var i = 0; i < factors.length; i++) {
                var f = factors[i];
                var alias = f.alias || f.name || '';
                var isActive = !!selectedSet[alias];
                html += '<div class="gt-chiplist-row" data-kind="factor" data-factor-alias="' + escapeHTML(alias) + '"'
                    + ' style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:5px 8px;cursor:pointer;'
                    + (isActive ? 'background:#e8f4fd;' : '')
                    + 'border-bottom:1px solid #f0f2f5;">';
                // chip：点击弹出 FactorInfoOverlay（stopPropagation 阻止触发行选中）
                html += '<span class="gt-backend-chip gt-chiplist-chip" data-kind="factor" data-factor-alias="' + escapeHTML(alias) + '"'
                    + ' style="cursor:pointer;max-width:calc(100% - 24px);">'
                    + _factorChipHtml(alias) + '</span>';
                // 选中标记：行尾部，不在 chip 内
                html += '<span style="flex-shrink:0;font-size:11px;color:' + (isActive ? '#0078d4' : '#ccc') + ';min-width:12px;text-align:center;">' + (isActive ? '✓' : '') + '</span>';
                html += '</div>';
            }
        }
        html += '</div>';

        container.innerHTML = html;

        // 标题 chip 用 ChipRenderer.render（DOM 模式，不再手动拼 HTML）
        var titleHost = container.querySelector('.gt-chiplist-title-chip[data-chip-kind="factor"]');
        if (titleHost && window.ChipRenderer && GT.backendSettings) {
            var store = GT.backendSettings.ensureGtLocalStore ? GT.backendSettings.ensureGtLocalStore() : null;
            var factorChips = [];
            var factorLabels = {};
            if (multiple) {
                (selected || []).forEach(function(alias) {
                    var rk = '_fl_' + alias;
                    factorLabels[rk] = alias;
                    factorChips.push({
                        key: 'factor_alias_' + alias,
                        chip_template: '因子: {value}',
                        source_keys: [],
                        value_resolvers: { value: rk },
                        category: 'identity',
                    });
                });
            } else if (selected) {
                factorLabels['_fl'] = selected;
                factorChips.push({
                    key: 'factor_alias',
                    chip_template: '因子: {value}',
                    source_keys: [],
                    value_resolvers: { value: '_fl' },
                    category: 'identity',
                });
            }
            if (store && factorChips.length > 0) {
                var resolvers = {};
                Object.keys(factorLabels).forEach(function(rk) {
                    resolvers[rk] = (function(alias) { return function() { return alias; }; })(factorLabels[rk]);
                });
                window.ChipRenderer.render(titleHost, {
                    chips: factorChips,
                    store: store,
                    resolvers: resolvers,
                    escapeHTML: escapeHTML,
                    renderChipHtml: GT.backendSettings.renderChipHtml,
                });
            } else {
                titleHost.innerHTML = multiple ? '<span style="font-weight:400;font-size:11px;color:#888;">未选</span>' : '';
            }
        }

        // 行点击 → 选中/切换（排除 chip 上的点击）
        container.querySelectorAll('.gt-chiplist-row[data-kind="factor"]').forEach(function(row) {
            row.addEventListener('click', function(e) {
                // 点击 chip 区域 → 只弹 overlay，不切换选中
                if (e.target.closest('.gt-chiplist-chip')) return;
                var alias = row.getAttribute('data-factor-alias');
                if (!alias) return;
                if (typeof options.onToggle === 'function') options.onToggle(alias);
            });
        });

        // chip 点击 → 弹出 FactorInfoOverlay
        container.querySelectorAll('.gt-chiplist-chip[data-kind="factor"]').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var alias = chip.getAttribute('data-factor-alias');
                if (!alias) return;
                var entry = null;
                for (var i = 0; i < factors.length; i++) {
                    if ((factors[i].alias || factors[i].name) === alias) { entry = factors[i]; break; }
                }
                if (entry && window.FactorInfoOverlay) window.FactorInfoOverlay.open(entry);
            });
        });
    }

    GT.panels.renderProductPathChipList = renderProductPathChipList;
    GT.panels.renderFactorChipList = renderFactorChipList;

    GT.log('panels/group_chip_list loaded');
})();
