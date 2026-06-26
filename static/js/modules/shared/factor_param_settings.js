/** Factor-param selection utility helpers — mirrors ProductPathSelectionUtils for factor-library params. */
(function() {
    if (window.FactorParamSelectionUtils) return;

    /* ── helpers ── */

    function clone(value) {
        if (value == null || typeof value !== 'object') return value;
        if (Array.isArray(value)) return value.map(clone);
        var out = {};
        Object.keys(value).forEach(function(key) { out[key] = clone(value[key]); });
        return out;
    }

    function escapeHTML(str) {
        return String(str == null ? '' : str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /* ── param identity (analogous to selectionId / selectionIdentity) ── */

    /**
     * Unique id for a factor-param entry.
     * Prefers factor_alias + scope_key + owner_username combo.
     */
    function factorParamId(param) {
        if (!param) return '';
        var parts = [
            param.factor_alias || param.factorAlias || '',
            param.scope_key || param.product_group || param.productGroup || '',
            param.owner_username || param.ownerUsername || ''
        ].map(function(s) { return String(s || '').trim(); });
        return parts.join('::');
    }

    /**
     * Stable identity for dedup & comparison.
     */
    function factorParamIdentity(param) {
        if (!param) return '';
        var ff = param.factor_family_alias || param.factorFamilyAlias || '';
        var fa = param.factor_alias || param.factorAlias || '';
        var scope = param.scope_key || param.product_group || param.productGroup || '';
        var owner = param.owner_username || param.ownerUsername || '';
        return [ff, fa, scope, owner].map(function(s) { return String(s || '').trim(); }).join('|');
    }

    /**
     * Display label for a single factor param.
     */
    function factorParamDisplayLabel(param) {
        if (!param) return '';
        var alias = param.factor_alias || param.factorAlias || factorParamId(param);
        var source = factorParamSourceLabel(param);
        return source ? alias + ' · ' + source : alias;
    }

    /**
     * 因子库参数行所属的"产品组标签"——独立于现有的"现场"/"产品组"语义：
     * - scope_key 为后端 DEFAULT_SCOPE_KEY（'default'）或历史遗留的中文'默认'
     *   时表示该因子库参数未绑定任何产品组；
     * - 否则 scope_key 即为绑定的产品组名称。
     */
    function factorLibraryScopeLabel(scope) {
        if (!scope || scope === 'default' || scope === '默认') return '未绑定产品组';
        return '产品组: ' + scope;
    }

    function factorParamSourceLabel(param) {
        if (!param) return '';
        var scope = param.scope_key || param.product_group || param.productGroup || '';
        if (scope === '现场') return '现场';
        if (scope) return factorLibraryScopeLabel(scope);
        var owner = param.owner_alias || param.ownerUsername || param.owner_username || '';
        if (owner) return owner;
        return '因子库';
    }

    /* ── selection/grouping helpers (analogous to productGroupToSelection) ── */

    /**
     * Convert a factor-overview item to a param-selection shape,
     * keeping the full params dict for rendering the param table.
     */
    function factorItemToParamSelection(item) {
        if (!item) return null;
        return {
            factor_alias: item.factor_alias || item.factorAlias || '',
            factor_family_alias: item.factor_family_alias || item.factorFamilyAlias || '',
            factor_family_name: item.factor_family_name || item.factorFamilyName || '',
            owner_username: item.owner_username || item.ownerUsername || '',
            owner_alias: item.owner_alias || item.ownerAlias || '',
            owner_organization_name: item.owner_organization_name || item.ownerOrganizationName || '',
            scope_key: item.scope_key || item.product_group || item.productGroup || '',
            template_name: item.template_name || item.templateName || item.config_name || '',
            params: item.params || {},
            // flattened for display
            paramsSummary: factorParamId(item)
        };
    }

    /**
     * Group factor params by scope_key (product_group).
     * Returns an object { scopeKey: [paramSelection, ...] }
     */
    function groupByScope(params) {
        var groups = {};
        (params || []).forEach(function(p) {
            var key = p.scope_key || 'default';
            if (!groups[key]) groups[key] = [];
            groups[key].push(p);
        });
        return groups;
    }

    /* ── dedupe ── */

    function dedupe(params) {
        var seen = {};
        var out = [];
        (params || []).forEach(function(p) {
            var id = factorParamIdentity(p);
            if (!id || seen[id]) return;
            seen[id] = true;
            out.push(p);
        });
        return out;
    }

    /* ── manual / ad-hoc session param (analogous to manualSelection) ── */

    /**
     * Represents a "现场" (in-session) factor param row — params from the current page session.
     */
    function sessionParamSelection(factorAlias, factorFamilyAlias, params) {
        params = params || {};
        var id = 'session_' + (factorAlias || Date.now().toString(36)) + '_' + Math.random().toString(36).slice(2, 7);
        return {
            factor_alias: factorAlias || '',
            factor_family_alias: factorFamilyAlias || '',
            owner_username: '',
            owner_alias: '',
            scope_key: '现场',
            params: params,
            paramsSummary: factorAlias || '',
            _session_id: id,
            source_type: 'session'
        };
    }

    /* ── param rows → compact table rendering ── */

    /**
     * Build an HTML table row for one factor param.
     * @param {Object} param — a paramSelection
     * @param {Array} paramDefs — the factor family's param definitions [{alias, label, default_value, ...}]
     */
    function renderParamRow(param, paramDefs, selection) {
        paramDefs = paramDefs || [];
        var alias = escapeHTML(param.factor_alias || '');
        var scope = param.scope_key || '';
        var sourceBadge = '';
        if (scope === '现场') {
            sourceBadge = '<span style="display:inline-block;padding:0 5px;border-radius:3px;background:#fef3c7;color:#92400e;font-size:10px;font-weight:600;">现场</span>';
        } else if (!scope || scope === 'default' || scope === '默认') {
            sourceBadge = '<span style="display:inline-block;padding:0 5px;border-radius:3px;background:#ede9fe;color:#5b21b6;font-size:10px;font-weight:600;">因子库 · 未绑定产品组</span>';
        } else {
            sourceBadge = '<span style="display:inline-block;padding:0 5px;border-radius:3px;background:#dbeafe;color:#1e40af;font-size:10px;font-weight:600;">因子库 · 产品组: ' + escapeHTML(scope) + '</span>';
        }

        var cells = paramDefs.map(function(def) {
            var key = def.alias || def.name || '';
            var val = param.params && param.params[key] !== undefined ? param.params[key] : '';
            return '<td style="padding:5px 8px;font-size:11px;border-bottom:1px solid #f1f5f9;">' + escapeHTML(String(val)) + '</td>';
        }).join('');

        // selection 模式（IC 多选 / group_test 单选）：行首加勾选框，行高亮当前已选。
        var selectCell = '';
        var rowStyle = 'background:#fff;';
        if (selection && selection.mode) {
            var inputType = selection.mode === 'multi' ? 'checkbox' : 'radio';
            selectCell = '<td style="padding:5px 4px;border-bottom:1px solid #f1f5f9;text-align:center;width:28px;">' +
                '<input type="' + inputType + '" class="fps-select-row" data-fps-select-alias="' + alias + '"' +
                (selection.active ? ' checked' : '') + '></td>';
            if (selection.active) rowStyle = 'background:#e8f4fd;';
        }

        return '<tr style="' + rowStyle + '">' +
            selectCell +
            '<td style="padding:5px 8px;border-bottom:1px solid #f1f5f9;white-space:nowrap;">' +
            '<span style="font-weight:600;color:#1e293b;">' + alias + '</span> ' + sourceBadge +
            '</td>' +
            cells +
            '<td style="padding:5px 8px;border-bottom:1px solid #f1f5f9;text-align:center;">' +
            '<button type="button" class="fps-remove-row" data-fps-alias="' + escapeHTML(alias) + '" style="height:22px;padding:0 7px;border:1px solid #fecaca;border-radius:4px;background:#fff5f5;color:#b91c1c;font-size:11px;cursor:pointer;">✕</button>' +
            '</td>' +
            '</tr>';
    }

    /**
     * Build a header row from paramDefs.
     */
    function renderTableHeader(paramDefs, hasSelectCol) {
        var cells = paramDefs.map(function(def) {
            return '<th style="padding:6px 8px;font-size:11px;font-weight:600;color:#475569;text-align:left;border-bottom:2px solid #e2e8f0;background:#f8fafc;">' + escapeHTML(def.label || def.alias || def.name || '') + '</th>';
        }).join('');
        return '<thead><tr>' +
            (hasSelectCol ? '<th style="padding:6px 4px;border-bottom:2px solid #e2e8f0;background:#f8fafc;width:28px;"></th>' : '') +
            '<th style="padding:6px 8px;font-size:11px;font-weight:600;color:#475569;text-align:left;border-bottom:2px solid #e2e8f0;background:#f8fafc;">因子</th>' +
            cells +
            '<th style="padding:6px 8px;font-size:11px;font-weight:600;color:#475569;text-align:center;border-bottom:2px solid #e2e8f0;background:#f8fafc;width:40px;"></th>' +
            '</tr></thead>';
    }

    /* ── manual builder for "现场" param rows ── */

    /**
     * mountManualFactorParamBuilder(options)
     *
     * Analogous to mountManualPathGroupBuilder but simpler:
     * - a text input for factor alias
     * - renders a mini-form with paramDefs fields
     * - on "add" calls options.onAddParam
     */
    function mountManualFactorParamBuilder(options) {
        options = options || {};
        var host = options.host;
        if (!host) return null;
        var prefix = String(options.prefix || 'fps-builder');
        var paramDefs = options.paramDefs || [];

        function id(suffix) { return prefix + '-' + suffix; }

        var html = '';
        html += '<div class="factor-param-manual-builder" style="border:1px solid #e5e7eb;border-radius:8px;background:#f9fafb;padding:12px;min-width:0;">';
        html += '<div style="font-size:12px;font-weight:700;color:#334155;margin-bottom:8px;">' + escapeHTML(options.title || '现场新增因子参数') + '</div>';
        // factor alias input
        html += '<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">';
        html += '<label style="font-size:11px;color:#64748b;white-space:nowrap;">因子别名</label>';
        html += '<input id="' + id('alias') + '" type="text" placeholder="如 MmRet_250401" style="flex:1;height:28px;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;">';
        html += '</div>';
        // param fields
        paramDefs.forEach(function(def) {
            var key = def.alias || def.name || '';
            html += '<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">';
            html += '<label style="font-size:11px;color:#64748b;white-space:nowrap;width:60px;">' + escapeHTML(def.label || key) + '</label>';
            html += '<input id="' + id('param-' + key) + '" type="text" placeholder="' + escapeHTML(String(def.default_value !== undefined ? def.default_value : '')) + '" value="' + escapeHTML(String(def.default_value !== undefined ? def.default_value : '')) + '" style="flex:1;height:28px;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;">';
            html += '</div>';
        });
        html += '<div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:8px;">';
        html += '<span id="' + id('status') + '" style="font-size:11px;color:#64748b;"></span>';
        html += '<button type="button" id="' + id('add') + '" style="height:28px;padding:0 12px;border:none;border-radius:4px;background:#2563eb;color:#fff;font-size:12px;cursor:pointer;">' + escapeHTML(options.addLabel || '新增到参数列表') + '</button>';
        html += '</div>';
        html += '</div>';
        host.innerHTML = html;

        function collectParams() {
            var params = {};
            paramDefs.forEach(function(def) {
                var key = def.alias || def.name || '';
                var input = document.getElementById(id('param-' + key));
                if (!input) return;
                var raw = input.value.trim();
                if (raw === '') {
                    params[key] = def.default_value;
                } else if (!isNaN(raw) && raw !== '') {
                    params[key] = Number(raw);
                } else {
                    params[key] = raw;
                }
            });
            return params;
        }

        var addBtn = document.getElementById(id('add'));
        if (addBtn) {
            addBtn.addEventListener('click', function() {
                var aliasInput = document.getElementById(id('alias'));
                var alias = aliasInput ? aliasInput.value.trim() : '';
                if (!alias) {
                    var status = document.getElementById(id('status'));
                    if (status) status.textContent = '请输入因子别名';
                    return;
                }
                var params = collectParams();
                if (typeof options.onAddParam === 'function') {
                    options.onAddParam(alias, params);
                }
                // reset
                if (aliasInput) aliasInput.value = '';
            });
        }

        return {
            destroy: function() { host.innerHTML = ''; }
        };
    }

    /* ── tab renderer (analogous to renderSelectionSettingsTab) ── */

    /**
     * renderFactorParamSettingsTab(options)
     *
     * options: {
     *   host: DOM element,
     *   prefix: string,
     *   factorFamilyAlias: string,
     *   paramDefs: [{ alias, label, default_value, ... }],
     *   currentFactorParams: [paramSelection],     // currently selected params
     *   libraryFactorParams: [paramSelection],     // from factor library (grouped by scope)
     *   scopes: [string],                          // available scopes
     *   onSetDefault: function(paramSelection),
     *   onRemoveParam: function(paramSelection),
     *   onAddParam: function(factorAlias, params),
     *   createLabel / createDefaultLabel,
     *   escapeHTML: function,
     *
     *   // 选择模式（IC 多选 / group_test 单选）；不传则保持原候选管理行为（如页面）。
     *   selectionMode: 'multi' | 'single',
     *   selectedIds: [string],            // selectionMode==='multi'：已选 alias 列表
     *   currentSelection: string,         // selectionMode==='single'：当前选中 alias
     *   onToggle: function(alias),        // selectionMode==='multi'：勾选/取消
     *   onSetDefault: function(alias),    // selectionMode==='single'：选中
     * }
     */
    function renderFactorParamSettingsTab(options) {
        options = options || {};
        var host = options.host;
        if (!host) return;
        var escapeFn = options.escapeHTML || escapeHTML;
        var paramDefs = options.paramDefs || [];
        var currentParams = Array.isArray(options.currentFactorParams) ? options.currentFactorParams : [];
        var libraryParams = Array.isArray(options.libraryFactorParams) ? options.libraryFactorParams : [];
        if (options.selectionMode !== 'multi' && options.selectionMode !== 'single') {
            throw new Error('renderFactorParamSettingsTab: selectionMode 必须是 "multi" 或 "single"');
        }
        var selectionMode = options.selectionMode;
        var selectedIdSet = {};
        (options.selectedIds || []).forEach(function(id) { selectedIdSet[String(id)] = true; });
        var currentSelection = String(options.currentSelection || '');
        function isActive(alias) {
            return selectionMode === 'multi' ? !!selectedIdSet[String(alias)] : String(alias) === currentSelection;
        }

        var html = '';
        html += '<div class="backend-settings-grid factor-param-settings-tab">';

        // ── 1. selection summary（已选个数 / 当前选中）──
        html += '<div class="gt-backtest-setting-row">';
        if (selectionMode === 'multi') {
            var selCount = currentParams.filter(function(p) { return isActive(p.factor_alias); }).length;
            html += '<span class="gt-backtest-setting-label">已选</span>';
            html += '<span class="gt-backtest-setting-control"><span class="gt-backend-chip unified-backend-chip">' +
                '<span class="gt-backend-chip-label">已选</span><span class="gt-backend-chip-value">' + selCount + ' / ' + currentParams.length + '</span>' +
                '</span></span>';
        } else {
            html += '<span class="gt-backtest-setting-label">当前选中</span>';
            html += '<span class="gt-backtest-setting-control"><span class="gt-backend-chip unified-backend-chip">' +
                '<span class="gt-backend-chip-label">因子</span><span class="gt-backend-chip-value">' + escapeFn(currentSelection || '无') + '</span>' +
                '</span></span>';
        }
        html += '</div>';

        // ── 2. param table ──
        html += '<div class="gt-backtest-setting-row" style="grid-column:1 / -1;">';
        html += '<span class="gt-backtest-setting-label">参数列表</span>';
        html += '</div>';
        html += '<div style="grid-column:1 / -1;overflow-x:auto;border:1px solid #e2e8f0;border-radius:8px;">';
        html += '<table style="width:100%;border-collapse:collapse;">';
        html += renderTableHeader(paramDefs, true);
        html += '<tbody id="' + escapeFn(options.prefix || 'fps') + '-param-tbody">';
        if (!currentParams.length) {
            html += '<tr><td colspan="' + (paramDefs.length + 3) + '" style="padding:16px;text-align:center;color:#94a3b8;font-size:12px;">暂无参数行，请在下方新增或从因子库加载</td></tr>';
        } else {
            currentParams.forEach(function(p) {
                html += renderParamRow(p, paramDefs, { mode: selectionMode, active: isActive(p.factor_alias) });
            });
        }
        html += '</tbody></table>';
        html += '</div>';

        // ── 3. library params grouped by scope ──
        if (libraryParams.length) {
            var grouped = groupByScope(libraryParams);
            html += '<div class="gt-backtest-setting-row" style="grid-column:1 / -1;">';
            html += '<span class="gt-backtest-setting-label">因子库参数</span>';
            html += '<span class="gt-backtest-setting-control"><span class="gt-backend-chip unified-backend-chip">' +
                '<span class="gt-backend-chip-label">总计</span><span class="gt-backend-chip-value">' + libraryParams.length + '行</span>' +
                '</span></span>';
            html += '</div>';

            html += '<div style="grid-column:1 / -1;display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;">';
            Object.keys(grouped).sort().forEach(function(scope) {
                var count = grouped[scope].length;
                html += '<button type="button" class="fps-scope-toggle" data-fps-scope="' + escapeFn(scope) + '" style="padding:4px 10px;border:1px solid #d0d5dd;border-radius:4px;background:#fff;color:#475569;font-size:11px;cursor:pointer;">' +
                    escapeFn(factorLibraryScopeLabel(scope)) + ' (' + count + ')' +
                    '</button>';
            });
            html += '</div>';

            Object.keys(grouped).sort().forEach(function(scope) {
                html += '<div class="fps-scope-group" data-fps-scope-group="' + escapeFn(scope) + '" style="grid-column:1 / -1;display:none;border:1px solid #e2e8f0;border-radius:8px;margin-bottom:8px;">';
                html += '<div style="padding:8px 10px;background:#f8fafc;border-bottom:1px solid #e2e8f0;font-size:12px;font-weight:600;color:#334155;">' + escapeFn(factorLibraryScopeLabel(scope)) + ' (' + grouped[scope].length + ')</div>';
                html += '<div style="overflow-x:auto;">';
                html += '<table style="width:100%;border-collapse:collapse;">';
                html += '<thead><tr>';
                html += '<th style="padding:5px 8px;font-size:10px;color:#94a3b8;text-align:left;border-bottom:1px solid #f1f5f9;">因子</th>';
                paramDefs.forEach(function(def) {
                    html += '<th style="padding:5px 8px;font-size:10px;color:#94a3b8;text-align:left;border-bottom:1px solid #f1f5f9;">' + escapeFn(def.label || def.alias || '') + '</th>';
                });
                html += '<th style="padding:5px 8px;font-size:10px;color:#94a3b8;text-align:center;border-bottom:1px solid #f1f5f9;width:50px;">操作</th>';
                html += '</tr></thead><tbody>';
                grouped[scope].forEach(function(p) {
                    var cells = paramDefs.map(function(def) {
                        var key = def.alias || def.name || '';
                        var val = p.params && p.params[key] !== undefined ? p.params[key] : '';
                        return '<td style="padding:4px 8px;font-size:11px;border-bottom:1px solid #f8fafc;">' + escapeFn(String(val)) + '</td>';
                    }).join('');
                    html += '<tr style="background:#fff;transition:background .12s;" onmouseover="this.style.background=\'#f8fafc\'" onmouseout="this.style.background=\'#fff\'">';
                    html += '<td style="padding:4px 8px;border-bottom:1px solid #f8fafc;"><span style="font-weight:500;color:#1e293b;">' + escapeFn(p.factor_alias || '') + '</span></td>';
                    html += cells;
                    html += '<td style="padding:4px 8px;border-bottom:1px solid #f8fafc;text-align:center;">';
                    html += '<button type="button" class="fps-load-row" data-fps-load="' + escapeFn(factorParamId(p)) + '" style="height:22px;padding:0 8px;border:1px solid #bbf7d0;border-radius:4px;background:#f0fdf4;color:#166534;font-size:11px;cursor:pointer;">加载</button>';
                    html += '</td>';
                    html += '</tr>';
                });
                html += '</tbody></table>';
                html += '</div>';
                html += '</div>';
            });

            // scope toggle logic (added after render via event delegation)
            host.addEventListener('click', function(e) {
                var toggle = e.target.closest('.fps-scope-toggle');
                if (!toggle) return;
                var scope = toggle.getAttribute('data-fps-scope');
                var group = host.querySelector('.fps-scope-group[data-fps-scope-group="' + CSS.escape(scope) + '"]');
                if (!group) return;
                var visible = group.style.display !== 'none';
                group.style.display = visible ? 'none' : '';
                toggle.style.background = visible ? '#fff' : '#eff6ff';
                toggle.style.borderColor = visible ? '#d0d5dd' : '#bfdbfe';
                toggle.style.color = visible ? '#475569' : '#1d4ed8';
            });
        }

        // ── 4. manual builder ──
        html += '<div style="grid-column:1 / -1;margin-top:4px;">';
        html += '<div id="' + escapeFn((options.prefix || 'fps') + '-manual-builder') + '"></div>';
        html += '</div>';

        html += '</div>';
        host.innerHTML = html;

        // mount manual builder
        mountManualFactorParamBuilder({
            host: host.querySelector('#' + (options.prefix || 'fps') + '-manual-builder'),
            prefix: options.prefix || 'fps',
            title: options.manualTitle || '现场新增因子参数',
            addLabel: options.addLabel || '新增到参数列表',
            paramDefs: paramDefs,
            onAddParam: function(factorAlias, params) {
                if (typeof options.onAddParam === 'function') {
                    options.onAddParam(factorAlias, params);
                }
            }
        });

        // load-row buttons
        host.querySelectorAll('.fps-load-row').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var id = this.getAttribute('data-fps-load');
                var allParams = currentParams.concat(libraryParams);
                var match = allParams.filter(function(p) { return factorParamId(p) === id; })[0];
                if (match && typeof options.onLoadFromLibrary === 'function') {
                    options.onLoadFromLibrary(match);
                }
            });
        });

        // remove-row buttons in the current param table
        var tbody = host.querySelector('#' + (options.prefix || 'fps') + '-param-tbody');
        if (tbody) {
            tbody.addEventListener('click', function(e) {
                var removeBtn = e.target.closest('.fps-remove-row');
                if (!removeBtn) return;
                var alias = removeBtn.getAttribute('data-fps-alias');
                if (alias && typeof options.onRemoveParam === 'function') {
                    options.onRemoveParam(alias);
                }
            });
            // selection 模式：勾选框/单选框切换选中（multi → onToggle；single → onSetDefault）
            if (selectionMode) {
                tbody.addEventListener('change', function(e) {
                    var input = e.target.closest('.fps-select-row');
                    if (!input) return;
                    var alias = input.getAttribute('data-fps-select-alias');
                    if (!alias) return;
                    if (selectionMode === 'multi' && typeof options.onToggle === 'function') {
                        options.onToggle(alias);
                    } else if (selectionMode === 'single' && typeof options.onSetDefault === 'function') {
                        options.onSetDefault(alias);
                    }
                });
            }
        }
    }

    /* ── public API ── */

    window.FactorParamSelectionUtils = {
        clone: clone,
        escapeHTML: escapeHTML,
        factorParamId: factorParamId,
        factorParamIdentity: factorParamIdentity,
        factorParamDisplayLabel: factorParamDisplayLabel,
        factorParamSourceLabel: factorParamSourceLabel,
        factorLibraryScopeLabel: factorLibraryScopeLabel,
        factorItemToParamSelection: factorItemToParamSelection,
        groupByScope: groupByScope,
        dedupe: dedupe,
        sessionParamSelection: sessionParamSelection,
        renderParamRow: renderParamRow,
        renderTableHeader: renderTableHeader,
        mountManualFactorParamBuilder: mountManualFactorParamBuilder,
        renderFactorParamSettingsTab: renderFactorParamSettingsTab,
        renderChipHtml: (window.ProductPathSelectionUtils && window.ProductPathSelectionUtils.renderChipHtml) || function(label, value, escapeFn) {
            escapeFn = escapeFn || escapeHTML;
            if (value !== undefined && value !== null && value !== '') {
                return '<span class="gt-backend-chip-label">' + escapeFn(label || '') + '</span>'
                    + '<span class="gt-backend-chip-value">' + escapeFn(value) + '</span>';
            }
            return '<span class="gt-backend-chip-value">' + escapeFn(String(label == null ? '' : label)) + '</span>';
        },
    };
})();
