/** Product-path selection utility helpers shared by test modules. */
(function() {
    if (window.ProductPathSelectionUtils) return;

    function clone(value) {
        if (value == null || typeof value !== 'object') return value;
        if (Array.isArray(value)) return value.map(clone);
        var out = {};
        Object.keys(value).forEach(function(key) { out[key] = clone(value[key]); });
        return out;
    }

    function selectionId(selection) {
        return selection ? String(selection.product_path_selection_id || selection.selection_id || selection.id || '') : '';
    }

    function selectionLabel(selection) {
        if (!selection) return '';
        return selection.product_group || selection.label || selection.name || selectionId(selection);
    }

    function selectionSourceLabel(selection) {
        if (!selection) return '';
        if (selection.product_group_template_id || selection.product_group || selection.product_group_name) return '产品组';
        if (selection.path_id) return '路径组';
        return '现场';
    }

    function selectionDisplayLabel(selection) {
        var label = selectionLabel(selection);
        var source = selectionSourceLabel(selection);
        return source ? label + ' · ' + source : label;
    }

    function selectionProducts(selection) {
        var raw = selection && ((Array.isArray(selection.products) && selection.products.length)
            ? selection.products
            : (selection.product_groups || []));
        return (raw || []).map(function(item) {
            if (typeof item === 'string') return { name: item, desc: '' };
            return item && item.name ? { name: item.name, desc: item.desc || '' } : null;
        }).filter(Boolean);
    }

    function productGroupToSelection(group) {
        group = group || {};
        var id = String(group.id || group.product_group_template_id || group.name || '');
        var products = (group.product_names || group.products || []).map(function(item) {
            return typeof item === 'string' ? { name: item, desc: '' } : item;
        }).filter(Boolean);
        return {
            id: id,
            product_path_selection_id: id,
            product_group_template_id: id,
            path_id: id,
            product_group: group.name || group.product_group || id,
            label: group.name || group.product_group || id,
            selected_paths: (group.paths || group.selected_paths || []).slice(),
            paths: (group.paths || group.selected_paths || []).slice(),
            products: products,
            product_groups: products,
        };
    }

    function compactSelection(selection, serialization) {
        var id = selectionId(selection);
        if (!selection || !id) return null;
        serialization = serialization || {};
        var idKeys = serialization.id_keys || ['product_path_selection_id', 'selection_id', 'id'];
        var referenceKeys = serialization.product_group_reference_keys || ['product_group_template_id', 'path_id'];
        var sourceType = serialization.product_group_source_type || 'user_product_group_template';
        var manualPathKeys = serialization.manual_path_keys || ['paths', 'selected_paths'];
        var productGroupId = '';
        referenceKeys.forEach(function(key) {
            if (!productGroupId && selection[key]) productGroupId = String(selection[key]);
        });
        if (!productGroupId && selection.source_type === sourceType) {
            idKeys.forEach(function(key) {
                if (!productGroupId && selection[key]) productGroupId = String(selection[key]);
            });
        }
        if (productGroupId) return { product_path_selection_id: productGroupId };
        var paths = [];
        manualPathKeys.forEach(function(key) {
            if (!paths.length && Array.isArray(selection[key])) paths = selection[key];
        });
        var compact = { product_path_selection_id: id };
        if (Array.isArray(paths) && paths.length) {
            compact.paths = paths.map(function(path) { return String(path || '').trim(); }).filter(Boolean);
        }
        return compact;
    }

    function selectionIdentity(selection) {
        if (!selection) return '';
        var templateId = selection.product_group_template_id || selection.path_id || '';
        if (templateId) return 'template:' + String(templateId);
        var paths = selection.paths || selection.selected_paths || [];
        if (Array.isArray(paths) && paths.length) {
            return 'paths:' + paths.map(function(path) { return String(path || '').trim(); })
                .filter(Boolean)
                .sort()
                .join('|');
        }
        var id = selectionId(selection);
        return id ? 'id:' + id : '';
    }

    function dedupe(selections) {
        var seen = {};
        var out = [];
        (selections || []).forEach(function(selection) {
            var id = selectionIdentity(selection);
            if (!id || seen[id]) return;
            seen[id] = true;
            out.push(selection);
        });
        return out;
    }

    function escapeHTML(str) {
        return String(str == null ? '' : str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function manualSelection(name, paths) {
        var id = 'manual_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 7);
        return {
            id: id,
            product_path_selection_id: id,
            selection_id: id,
            source_type: 'runtime_manual_path_group',
            label: name || '现场路径组',
            name: name || '现场路径组',
            paths: (paths || []).slice(),
            selected_paths: (paths || []).slice(),
            products: [],
            product_groups: [],
        };
    }

    function positivePaths(paths) {
        return (paths || []).filter(function(path) { return String(path || '').charAt(0) !== '-'; });
    }

    function exclusionsCoveredBy(paths, positive) {
        return (paths || []).filter(function(path) {
            path = String(path || '');
            if (path.charAt(0) !== '-') return false;
            var leafPath = path.substring(1);
            return (positive || []).some(function(includedPath) {
                return leafPath === includedPath || leafPath.indexOf(includedPath + '/') === 0;
            });
        });
    }

    function negativeProductPath(parentPath, productName) {
        var basePath = String(parentPath || '').slice(-10) === '/_products'
            ? String(parentPath || '')
            : String(parentPath || '') + '/_products';
        return '-' + basePath + '/' + productName;
    }

    function addDraftPaths(state, paths, negative) {
        var next = state.draftPaths.slice();
        (paths || []).forEach(function(path) {
            path = String(path || '').trim();
            if (!path) return;
            if (negative && path.charAt(0) !== '-') path = '-' + path;
            if (!negative && path.charAt(0) === '-') path = path.substring(1);
            if (next.indexOf(path) < 0) next.push(path);
        });
        state.draftPaths = next;
    }

    function mountManualPathGroupBuilder(options) {
        options = options || {};
        var host = options.host;
        if (!host) return null;
        if (host.__manualProductPathBuilder && typeof host.__manualProductPathBuilder.destroy === 'function') {
            host.__manualProductPathBuilder.destroy();
        }
        var prefix = String(options.prefix || 'pps-builder');
        var state = {
            selectedPaths: [],
            draftPaths: [],
            tree: null,
            treeSizer: null,
        };

        function id(suffix) { return prefix + '-' + suffix; }
        function query(suffix) { return host.querySelector('#' + id(suffix)); }

        function renderDraft() {
            var target = query('draft-paths');
            if (!target) return;
            var paths = state.draftPaths || [];
            if (!paths.length) {
                target.innerHTML = '<div style="padding:12px;color:#888;font-size:12px;line-height:1.6;">从左侧产品树勾选路径后，点击“正新增”或“负新增”。正新增路径下的单个产品也可以在展开后做负新增。</div>';
                return;
            }
            var html = '';
            html += '<div style="padding:7px 9px;border-bottom:1px solid #eef2f7;font-size:12px;font-weight:700;color:#475467;">当前路径规则 <span style="font-weight:500;color:#94a3b8;">' + paths.length + '</span></div>';
            paths.forEach(function(path) {
                var negative = String(path).charAt(0) === '-';
                var clean = negative ? String(path).substring(1) : String(path);
                html += '<div style="border-bottom:1px solid #f1f5f9;">';
                html += '<div style="display:grid;grid-template-columns:22px minmax(0,1fr) auto auto;gap:6px;align-items:start;padding:6px 8px;">';
                html += '<span style="display:inline-flex;align-items:center;justify-content:center;width:19px;height:18px;border-radius:4px;background:' + (negative ? '#fef2f2' : '#ecfdf3') + ';color:' + (negative ? '#b42318' : '#166534') + ';font-weight:700;font-size:12px;">' + (negative ? '-' : '+') + '</span>';
                html += '<span style="font-family:monospace;font-size:11px;color:#334155;word-break:break-all;line-height:1.35;">' + escapeHTML(clean) + '</span>';
                if (negative) html += '<span></span>';
                else html += '<button type="button" data-pps-builder-show-products="' + escapeHTML(clean) + '" style="height:22px;padding:0 7px;border:1px solid #dbeafe;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:11px;cursor:pointer;">产品</button>';
                html += '<button type="button" data-pps-builder-remove-path="' + escapeHTML(path) + '" style="height:22px;padding:0 7px;border:1px solid #fecaca;border-radius:4px;background:#fff5f5;color:#b91c1c;font-size:11px;cursor:pointer;">移除</button>';
                html += '</div>';
                html += '<div data-pps-builder-products-for="' + escapeHTML(clean) + '" style="display:none;padding:0 8px 7px 36px;"></div>';
                html += '</div>';
            });
            target.innerHTML = html;
            target.querySelectorAll('[data-pps-builder-remove-path]').forEach(function(button) {
                button.addEventListener('click', function() {
                    var path = this.getAttribute('data-pps-builder-remove-path');
                    state.draftPaths = state.draftPaths.filter(function(item) { return item !== path; });
                    renderDraft();
                });
            });
            target.querySelectorAll('[data-pps-builder-show-products]').forEach(function(button) {
                button.addEventListener('click', function() {
                    renderProductsForExclusion(this.getAttribute('data-pps-builder-show-products'));
                });
            });
        }

        function renderProductsForExclusion(path) {
            var slot = null;
            host.querySelectorAll('[data-pps-builder-products-for]').forEach(function(node) {
                if (node.getAttribute('data-pps-builder-products-for') === path) slot = node;
            });
            if (!slot) return;
            if (slot.style.display !== 'none' && slot.innerHTML) {
                slot.style.display = 'none';
                return;
            }
            slot.style.display = '';
            slot.innerHTML = '<div style="font-size:11px;color:#888;padding:5px 0;">加载产品...</div>';
            fetch('/get_products?path=' + encodeURIComponent(path), { headers: { Accept: 'application/json' } })
                .then(function(response) { return response.json().catch(function() { return []; }); })
                .then(function(products) {
                    var html = '';
                    (products || []).forEach(function(product) {
                        var name = product.product_name || product.title || product.name || '';
                        if (!name) return;
                        var exclusion = negativeProductPath(path, name);
                        var excluded = state.draftPaths.indexOf(exclusion) >= 0;
                        html += '<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;align-items:center;padding:4px 0;border-top:1px solid #f1f5f9;">';
                        html += '<span style="min-width:0;font-size:11px;color:#475467;"><b style="font-family:monospace;color:#334155;">' + escapeHTML(name) + '</b>' + (product.desc ? ' <span style="color:#94a3b8;">' + escapeHTML(product.desc) + '</span>' : '') + '</span>';
                        html += '<button type="button" data-pps-builder-exclude-product="' + escapeHTML(exclusion) + '" style="height:22px;padding:0 7px;border:1px solid ' + (excluded ? '#bfdbfe' : '#fecaca') + ';border-radius:4px;background:' + (excluded ? '#eff6ff' : '#fef2f2') + ';color:' + (excluded ? '#1d4ed8' : '#b42318') + ';font-size:11px;cursor:pointer;">' + (excluded ? '已排除' : '负新增') + '</button>';
                        html += '</div>';
                    });
                    slot.innerHTML = html || '<div style="font-size:11px;color:#888;padding:5px 0;">无产品</div>';
                    slot.querySelectorAll('[data-pps-builder-exclude-product]').forEach(function(button) {
                        button.addEventListener('click', function() {
                            addDraftPaths(state, [this.getAttribute('data-pps-builder-exclude-product')], true);
                            renderDraft();
                            renderProductsForExclusion(path);
                        });
                    });
                }).catch(function() {
                    slot.innerHTML = '<div style="font-size:11px;color:#d92d20;padding:5px 0;">产品加载失败</div>';
                });
        }

        function mountTree() {
            var treeEl = query('tree');
            if (!treeEl || !window.ProductSelector || !window.jQuery) return;
            treeEl.style.fontSize = '11px';
            treeEl.style.lineHeight = '1.35';
            window.ProductSelector.createTree(window.jQuery(treeEl), {
                onInit: function(tree) { state.tree = tree; },
                onSelect: function(paths) { state.selectedPaths = paths || []; },
            });
            if (typeof window.setupResizableTreeContainer === 'function') {
                state.treeSizer = window.setupResizableTreeContainer({
                    outerElement: query('tree-panel'),
                    innerElement: treeEl,
                    minWidth: 240,
                    initialWidth: Number(options.initialTreeWidth || 320),
                    minHeight: 180,
                    initialHeight: Number(options.initialTreeHeight || 300),
                    maxWidth: options.maxTreeWidth || 'min(52vw, 620px)',
                    maxWidthFallback: Number(options.maxTreeWidthFallback || 620),
                    resizeDirection: 'both',
                    desktopMediaQuery: '(max-width: 960px)',
                    mobileInnerMaxHeight: '360px',
                });
            } else {
                treeEl.style.boxSizing = 'border-box';
                treeEl.style.minWidth = '240px';
                treeEl.style.minHeight = '180px';
                treeEl.style.maxWidth = options.maxTreeWidth || 'min(52vw, 620px)';
                treeEl.style.resize = 'both';
                treeEl.style.overflow = 'auto';
            }
        }

        function create(setAsDefault) {
            var nameInput = query('new-name');
            var status = query('status');
            var name = nameInput ? nameInput.value.trim() : '';
            var paths = state.draftPaths.slice();
            if (!name || !paths.length) {
                if (status) status.textContent = '请填写名称和路径';
                return;
            }
            var selection = manualSelection(name, paths);
            if (typeof options.onCreate === 'function') options.onCreate(selection, { setAsDefault: !!setAsDefault });
            state.draftPaths = [];
            if (nameInput) nameInput.value = '';
            renderDraft();
            if (status) status.textContent = '已新增';
        }

        var title = options.title || '现场新增路径组';
        var html = '';
        html += '<div class="product-path-manual-builder" style="border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:10px;min-width:0;">';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;">';
        html += '<span style="font-size:12px;font-weight:700;color:#334155;">' + escapeHTML(title) + '</span>';
        html += '<span id="' + id('status') + '" style="font-size:12px;color:#64748b;"></span>';
        html += '</div>';
        html += '<input id="' + id('new-name') + '" type="text" placeholder="路径组名称" style="width:100%;box-sizing:border-box;height:30px;margin-bottom:8px;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;">';
        html += '<div style="display:grid;grid-template-columns:auto minmax(280px,1fr);gap:10px;align-items:start;min-width:0;">';
        html += '<div id="' + id('tree-panel') + '" style="min-width:0;">';
        html += '<div style="display:flex;gap:6px;margin-bottom:6px;">';
        html += '<button type="button" id="' + id('add-positive') + '" style="height:26px;padding:0 9px;border:1px solid #bbf7d0;border-radius:4px;background:#f0fdf4;color:#166534;font-size:12px;cursor:pointer;">+ 正新增</button>';
        html += '<button type="button" id="' + id('add-negative') + '" style="height:26px;padding:0 9px;border:1px solid #fecaca;border-radius:4px;background:#fef2f2;color:#b42318;font-size:12px;cursor:pointer;">- 负新增</button>';
        html += '</div>';
        html += '<div id="' + id('tree') + '" class="product-tree-scrollbox" style="width:320px;height:300px;overflow:auto;border:1px solid #e1e4e8;border-radius:6px;padding:6px;background:#fff;font-size:11px;line-height:1.35;"></div>';
        html += '</div>';
        html += '<div style="min-width:0;">';
        html += '<div id="' + id('draft-paths') + '" style="height:300px;overflow:auto;border:1px solid #e5e7eb;border-radius:6px;background:#fff;"></div>';
        html += '<div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:8px;">';
        html += '<button type="button" id="' + id('clear-draft') + '" style="height:28px;padding:0 10px;border:1px solid #cbd5e1;border-radius:4px;background:#fff;color:#475569;font-size:12px;cursor:pointer;">清空</button>';
        html += '<button type="button" id="' + id('create') + '" style="height:28px;padding:0 12px;border:1px solid #bfdbfe;border-radius:4px;background:#eff6ff;color:#1d4ed8;font-size:12px;cursor:pointer;">' + escapeHTML(options.createLabel || '新增') + '</button>';
        html += '<button type="button" id="' + id('create-default') + '" style="height:28px;padding:0 12px;border:none;border-radius:4px;background:#2563eb;color:#fff;font-size:12px;cursor:pointer;">' + escapeHTML(options.createDefaultLabel || '新增并设为默认') + '</button>';
        html += '</div>';
        html += '</div></div></div>';
        host.innerHTML = html;

        renderDraft();
        mountTree();
        var addPositiveBtn = query('add-positive');
        if (addPositiveBtn) addPositiveBtn.addEventListener('click', function() {
            addDraftPaths(state, state.selectedPaths, false);
            state.draftPaths = positivePaths(state.draftPaths)
                .concat(exclusionsCoveredBy(state.draftPaths, positivePaths(state.draftPaths)));
            renderDraft();
        });
        var addNegativeBtn = query('add-negative');
        if (addNegativeBtn) addNegativeBtn.addEventListener('click', function() {
            addDraftPaths(state, state.selectedPaths, true);
            renderDraft();
        });
        var clearDraftBtn = query('clear-draft');
        if (clearDraftBtn) clearDraftBtn.addEventListener('click', function() {
            state.draftPaths = [];
            renderDraft();
        });
        var createBtn = query('create');
        if (createBtn) createBtn.addEventListener('click', function() { create(false); });
        var createDefaultBtn = query('create-default');
        if (createDefaultBtn) createDefaultBtn.addEventListener('click', function() { create(true); });

        var api = {
            destroy: function() {
                if (state.treeSizer && typeof state.treeSizer.destroy === 'function') state.treeSizer.destroy();
                state.treeSizer = null;
            },
        };
        host.__manualProductPathBuilder = api;
        return api;
    }

    function renderChipHtml(labelOrText, value, escapeFn) {
        escapeFn = escapeFn || escapeHTML;
        if (value !== undefined && value !== null && value !== '') {
            return '<span class="gt-backend-chip-label">' + escapeFn(labelOrText || '') + '</span>'
                + '<span class="gt-backend-chip-value">' + escapeFn(value) + '</span>';
        }
        var text = String(labelOrText == null ? '' : labelOrText).trim();
        var match = text.match(/^([^:：]{1,16})[:：]\s*(.*)$/);
        if (match && match[2]) {
            return '<span class="gt-backend-chip-label">' + escapeFn(match[1]) + '</span>'
                + '<span class="gt-backend-chip-value">' + escapeFn(match[2]) + '</span>';
        }
        return '<span class="gt-backend-chip-value">' + escapeFn(text) + '</span>';
    }

    function renderSelectionSettingsTab(options) {
        options = options || {};
        var host = options.host;
        if (!host) return;
        var escapeFn = options.escapeHTML || escapeHTML;
        var selections = Array.isArray(options.selections) ? options.selections : [];
        var current = options.currentSelection || null;
        var currentId = selectionId(current);
        var currentLabel = current ? selectionDisplayLabel(current) : '无';
        var builderId = (options.prefix || 'pps') + '-manual-builder';
        var allowRemove = options.allowRemove || function(selection) {
            return selection && (selection.source_type === 'runtime_manual_path_group' || !(selection.product_group_template_id || selection.product_group || selection.product_group_name || selection.path_id));
        };
        var productCount = options.productCount || function(selection) { return selectionProducts(selection).length; };
        var pathCount = options.pathCount || function(selection) {
            var paths = selection && (selection.paths || selection.selected_paths || []);
            return Array.isArray(paths) ? paths.length : 0;
        };

        var html = '';
        html += '<div class="backend-settings-grid product-path-settings-tab">';
        html += '<div class="gt-backtest-setting-row">';
        html += '<span class="gt-backtest-setting-label">' + escapeFn(options.currentLabel || '当前默认') + '</span>';
        html += '<span class="gt-backtest-setting-control"><span class="gt-backend-chip unified-backend-chip">' + renderChipHtml('产品路径', currentLabel, escapeFn) + '</span></span>';
        html += '</div>';
        (options.extraRows || []).forEach(function(row) {
            if (!row) return;
            html += '<div class="gt-backtest-setting-row">';
            html += '<span class="gt-backtest-setting-label">' + escapeFn(row.label || '') + '</span>';
            html += '<span class="gt-backtest-setting-control">' + (row.html || '') + '</span>';
            html += '</div>';
        });
        html += '<div class="gt-backtest-setting-row">';
        html += '<span class="gt-backtest-setting-label">候选列表</span>';
        html += '<span class="gt-backtest-setting-control"><span class="gt-backend-chip unified-backend-chip">' + renderChipHtml('产品路径候选', String(selections.length) + '项', escapeFn) + '</span></span>';
        html += '</div>';
        html += '<div class="single-factor-page-product-path-list" style="grid-column:1 / -1;">';
        if (!selections.length) {
            html += '<div style="padding:14px;color:#888;font-size:12px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;">暂无产品路径组，请在下方新增。</div>';
        }
        selections.forEach(function(selection) {
            var id = selectionId(selection);
            var active = id && id === currentId;
            var label = selectionDisplayLabel(selection);
            html += '<div class="product-path-selection-item' + (active ? ' active' : '') + '" style="display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:6px;align-items:center;padding:7px 8px;border:1px solid #e2e8f0;border-radius:6px;margin-bottom:6px;background:' + (active ? '#eff6ff' : '#fff') + ';">';
            html += '<button type="button" data-pps-tab-open="' + escapeFn(id) + '" style="min-width:0;text-align:left;border:none;background:transparent;padding:0;cursor:pointer;">';
            html += '<div class="gt-backend-chip unified-backend-chip" style="display:inline-flex;">' + renderChipHtml('产品路径', label, escapeFn) + '</div>';
            html += '<div style="font-size:11px;color:#64748b;margin-top:3px;">' + pathCount(selection) + ' 路径 · ' + productCount(selection) + ' 产品' + (active ? ' · 默认' : '') + '</div>';
            html += '</button>';
            html += '<button type="button" data-pps-tab-default="' + escapeFn(id) + '" class="gt-backend-chip unified-backend-chip" style="border:1px solid #cbd5e1;background:#fff;cursor:pointer;">' + renderChipHtml(active ? '默认' : (options.setDefaultLabel || '设为默认'), '', escapeFn) + '</button>';
            if (allowRemove(selection)) {
                html += '<button type="button" data-pps-tab-remove="' + escapeFn(id) + '" style="height:24px;padding:0 7px;border:1px solid #fecaca;border-radius:4px;background:#fff5f5;color:#b91c1c;font-size:11px;cursor:pointer;">移除</button>';
            } else {
                html += '<span style="font-size:11px;color:#94a3b8;">产品组</span>';
            }
            html += '</div>';
        });
        html += '</div>';
        html += '<div id="' + escapeFn(builderId) + '" style="grid-column:1 / -1;"></div>';
        html += '</div>';
        host.innerHTML = html;

        host.querySelectorAll('[data-pps-tab-open]').forEach(function(button) {
            button.addEventListener('click', function(event) {
                event.preventDefault();
                var id = this.getAttribute('data-pps-tab-open');
                var selection = selections.filter(function(item) { return selectionId(item) === id; })[0] || null;
                if (selection && typeof options.onOpen === 'function') options.onOpen(selection);
            });
        });
        host.querySelectorAll('[data-pps-tab-default]').forEach(function(button) {
            button.addEventListener('click', function(event) {
                event.preventDefault();
                var id = this.getAttribute('data-pps-tab-default');
                var selection = selections.filter(function(item) { return selectionId(item) === id; })[0] || null;
                if (selection && typeof options.onSetDefault === 'function') options.onSetDefault(selection);
            });
        });
        host.querySelectorAll('[data-pps-tab-remove]').forEach(function(button) {
            button.addEventListener('click', function(event) {
                event.preventDefault();
                var id = this.getAttribute('data-pps-tab-remove');
                var selection = selections.filter(function(item) { return selectionId(item) === id; })[0] || null;
                if (selection && typeof options.onRemove === 'function') options.onRemove(selection);
            });
        });
        mountManualPathGroupBuilder({
            host: host.querySelector('#' + builderId),
            prefix: options.prefix || 'pps',
            title: options.manualTitle || '现场新增路径组',
            createLabel: options.createLabel || '新增',
            createDefaultLabel: options.createDefaultLabel || '新增并设为默认',
            onCreate: function(selection, meta) {
                if (typeof options.onCreate === 'function') options.onCreate(selection, meta || {});
            },
        });
    }

    window.ProductPathSelectionUtils = {
        clone: clone,
        cloneList: function(list) { return Array.isArray(list) ? list.map(clone) : []; },
        selectionId: selectionId,
        selectionLabel: selectionLabel,
        selectionSourceLabel: selectionSourceLabel,
        selectionDisplayLabel: selectionDisplayLabel,
        selectionIdentity: selectionIdentity,
        selectionProducts: selectionProducts,
        productGroupToSelection: productGroupToSelection,
        compactSelection: compactSelection,
        dedupe: dedupe,
        manualSelection: manualSelection,
        mountManualPathGroupBuilder: mountManualPathGroupBuilder,
        renderSelectionSettingsTab: renderSelectionSettingsTab,
        renderChipHtml: renderChipHtml,
    };
})();
