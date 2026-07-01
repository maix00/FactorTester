/**
 * panels/add/derived.js — 派生组 addFlow + editAction
 *
 * - addFlow: 'derived' — 新建派生组（无 defaultTab，config tabs 自动展示）
 * - editAction: 'create-derived' — 从选中行创建派生组
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.panels) { GT.panels = {}; }
    if (!GT.panels.add) { GT.panels.add = {}; }

    var M = GT.modes;
    var _mounted = false;

    function _getGroup(id) {
        return GT.groupSettings.groups ? GT.groupSettings.groups.get(id) : null;
    }

    function _buildDerivedAddDraft(ctx) {
        var ids = (ctx && ctx.ids) ? ctx.ids : [];
        if (ids.length !== 1) return { addFlow: 'derived' };
        var selected = _getGroup(ids[0]);
        if (!selected) return { addFlow: 'derived' };
        var draft = { addFlow: 'derived' };
        draft.preselectedParentId = selected.id;
        draft.preselectedParentLabel = selected.name || selected.shortAlias || selected.id;
        if (selected.productMask) {
            var parentMask = selected.productMask || {};
            var hasOwnMask = Object.keys(parentMask).length > 0;
            if (hasOwnMask) {
                draft.preselectedProducts = Object.keys(parentMask).filter(function(k) { return parentMask[k]; });
            }
        }
        return draft;
    }

    function _buildDerivedDraftFromState(ctx) {
        var draft = { addFlow: 'derived' };
        var activeId = ctx.activeDerivedId || ctx.activeBaseId || null;
        if (activeId) {
            draft.preselectedParentId = activeId;
            var active = _getGroup(activeId);
            if (active) {
                draft.preselectedParentLabel = active.name || active.shortAlias || active.id;
                if (active.productMask) {
                    draft.preselectedProducts = Object.keys(active.productMask).filter(function(k) { return active.productMask[k]; });
                }
            }
        }
        return draft;
    }

    // 复制(clone)：和派生一样走可编辑的派生表单（主界面即分组设置），但用源组的
    // 设置预填草稿，让用户改部分设置后再保存——不再即时复制。
    function _buildCloneDraft(ctx) {
        var ids = (ctx && ctx.ids) ? ctx.ids : [];
        if (ids.length !== 1) return null;
        var src = _getGroup(ids[0]);
        if (!src) return null;
        var draft = { addFlow: 'derived', cloneFromId: src.id };
        draft.preselectedParentId = src.id;
        draft.preselectedParentLabel = src.name || src.shortAlias || src.id;
        draft.defaultName = (src.shortAlias || src.name || '组') + ' 副本';
        if (src.splitCount) draft.splitCount = src.splitCount;
        if (src.productMask) {
            var picked = Object.keys(src.productMask).filter(function(k) { return src.productMask[k]; });
            if (picked.length) draft.preselectedProducts = picked;
        }
        return draft;
    }

    function _submitDerived(draft, helpers) {
        if (!draft) { alert('提交草稿丢失'); return; }
        var parentId = draft.preselectedParentId;
        if (!parentId) {
            alert('请先从列表中选择一个分组或派生组作为上级');
            return;
        }
        var parentNode = _getGroup(parentId);
        var resolvedName = draft.name || draft.defaultName;
        if (!resolvedName || !resolvedName.trim()) {
            resolvedName = (parentNode && (parentNode.shortAlias || parentNode.name)) || '派生组';
        }
        var selectedProducts = draft.selectedProducts || [];
        var allProducts = _productRowsForParent(parentNode);
        var productMask = {};
        if (selectedProducts.length > 0 && selectedProducts.length < allProducts.length) {
            for (var i = 0; i < selectedProducts.length; i++) productMask[selectedProducts[i]] = true;
        }
        var config = {
            name: resolvedName,
            parentId: parentId,
            productMask: productMask,
            splitCount: draft.splitCount || (parentNode && parentNode.splitCount) || 1,
        };
        try {
            GT.groupSettings.groups.add(config);
        } catch (err) {
            alert('创建派生组失败: ' + (err && err.message || err));
            return;
        }
        if (parentNode && parentNode._expanded === false && GT.groupSettings.groups) {
            GT.groupSettings.groups.toggleExpanded(parentId);
        }
        helpers.exitAdd();
    }

    function _productsForParent(parentNode) {
        if (!parentNode) return [];
        if (GT.panels.actions && typeof GT.panels.actions.effectiveDerivedProductNames === 'function') {
            var names = GT.panels.actions.effectiveDerivedProductNames(parentNode) || [];
            if (names.length) return names;
        }
        if (GT.groupSettings.groups && typeof GT.groupSettings.groups.effectiveProductNames === 'function') {
            return GT.groupSettings.groups.effectiveProductNames(parentNode) || [];
        }
        return [];
    }

    function _rootNode(node) {
        var current = node;
        var seen = {};
        while (current && current.parentId && GT.groupSettings.groups && GT.groupSettings.groups.get) {
            if (seen[current.id]) break;
            seen[current.id] = true;
            current = GT.groupSettings.groups.get(current.parentId);
        }
        return current || node;
    }

    function _rootProductMap(parentNode) {
        var root = _rootNode(parentNode);
        var selection = root && root.product_path_selection;
        var raw = selection && ((Array.isArray(selection.products) && selection.products.length)
            ? selection.products
            : (selection.product_groups || []));
        var map = {};
        (raw || []).forEach(function(item) {
            var product = typeof item === 'string' ? { name: item, desc: '' } : item;
            if (product && product.name) {
                map[product.name] = {
                    name: product.name,
                    desc: product.desc || product.description || '',
                };
            }
        });
        return map;
    }

    function _productRowsForParent(parentNode) {
        var names = _productsForParent(parentNode);
        var meta = _rootProductMap(parentNode);
        return names.map(function(name) {
            var item = meta[name] || {};
            return {
                name: name,
                desc: item.desc || '',
            };
        });
    }

    function _displayKey(group) {
        if (!group) return '';
        if (GT.groupSettings.groups && typeof GT.groupSettings.groups.displayKey === 'function') {
            return GT.groupSettings.groups.displayKey(group);
        }
        return group.shortAlias || group.name || group.id || '';
    }

    function _escape(str) {
        return GT.escapeHTML ? GT.escapeHTML(str) : String(str == null ? '' : str);
    }

    function render(container) {
        if (!container) return;
        var draft = M && M.getAddDraft ? M.getAddDraft() : null;
        if (!draft) {
            container.innerHTML = '<div style="padding:12px;color:#64748b;font-size:12px;">派生组草稿不存在。</div>';
            return;
        }
        var parentNode = _getGroup(draft.preselectedParentId);
        var products = _productRowsForParent(parentNode);
        var selected = {};
        var productNames = products.map(function(product) { return product.name; });
        var selectedList = Array.isArray(draft.selectedProducts) ? draft.selectedProducts : (draft.preselectedProducts || productNames);
        selectedList.forEach(function(name) { selected[name] = true; });
        var html = '';
        html += '<div style="border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:12px;">';
        html += '<div style="display:grid;grid-template-columns:minmax(72px,max-content) minmax(0,1fr);gap:8px 12px;align-items:center;font-size:12px;">';
        html += '<div style="color:#667085;">上级</div>';
        html += '<div style="color:#1f2937;font-weight:600;">' + _escape(parentNode ? _displayKey(parentNode) : '未选择') + '</div>';
        html += '<label for="derived-group-name-input" style="color:#667085;margin:0;">名称</label>';
        html += '<input type="text" id="derived-group-name-input" value="' + _escape(draft.name || '') + '" placeholder="' + _escape((parentNode && (_displayKey(parentNode) + ':派生组')) || '派生组') + '" style="width:100%;max-width:360px;height:28px;box-sizing:border-box;padding:4px 8px;border:1px solid #d0d5dd;border-radius:4px;font-size:12px;margin:0!important;">';
        html += '</div>';
        html += '<div style="border-top:1px solid #eef2f7;margin:12px 0;"></div>';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">';
        html += '<span style="font-size:12px;font-weight:700;color:#475467;">品种筛选</span>';
        html += '<span style="display:inline-flex;gap:6px;">';
        html += '<button type="button" id="derived-select-all" style="height:24px;padding:0 8px;border:1px solid #94a3b8;border-radius:4px;background:#ffffff;color:#334155;font-size:11px;font-weight:600;cursor:pointer;">全选</button>';
        html += '<button type="button" id="derived-clear-all" style="height:24px;padding:0 8px;border:1px solid #94a3b8;border-radius:4px;background:#ffffff;color:#334155;font-size:11px;font-weight:600;cursor:pointer;">清空</button>';
        html += '</span>';
        html += '</div>';
        if (!products.length) {
            html += '<div style="padding:12px;color:#c2410c;background:#fff7ed;border:1px solid #fed7aa;border-radius:6px;font-size:12px;">当前上级没有可筛选品种。</div>';
        } else {
            html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px;max-height:260px;overflow:auto;border:1px solid #e8eaed;border-radius:6px;padding:8px;">';
            for (var i = 0; i < products.length; i++) {
                var product = products[i];
                var name = product.name;
                var desc = product.desc && product.desc !== name ? product.desc : '';
                html += '<label class="derived-product-option" title="' + _escape(desc ? name + ' · ' + desc : name) + '" style="display:flex;align-items:center;gap:6px;min-width:0;font-size:12px;color:#344054;cursor:pointer;">';
                html += '<input type="checkbox" class="derived-product-cb" value="' + _escape(name) + '"' + (selected[name] ? ' checked' : '') + ' style="width:14px;height:14px;flex-shrink:0;">';
                html += '<span style="min-width:0;display:flex;flex-direction:column;line-height:1.25;">'
                    + '<span style="font-family:monospace;color:#334155;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _escape(name) + '</span>'
                    + (desc ? '<span style="color:#94a3b8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _escape(desc) + '</span>' : '')
                    + '</span>';
                html += '</label>';
            }
            html += '</div>';
        }
        html += '</div>';
        container.innerHTML = html;

        function syncDraft() {
            var input = document.getElementById('derived-group-name-input');
            var cbs = Array.prototype.slice.call(container.querySelectorAll('.derived-product-cb'));
            var picked = cbs.filter(function(cb) { return cb.checked; }).map(function(cb) { return cb.value; });
            M.updateAddDraft({
                name: input ? input.value : '',
                selectedProducts: picked,
            });
        }
        var nameInput = document.getElementById('derived-group-name-input');
        if (nameInput) nameInput.addEventListener('input', syncDraft);
        container.querySelectorAll('.derived-product-cb').forEach(function(cb) {
            cb.addEventListener('change', syncDraft);
        });
        var selectAll = document.getElementById('derived-select-all');
        if (selectAll) selectAll.addEventListener('click', function() {
            M.updateAddDraft({ selectedProducts: productNames.slice(), name: nameInput ? nameInput.value : (draft.name || '') });
            render(container);
        });
        var clearAll = document.getElementById('derived-clear-all');
        if (clearAll) clearAll.addEventListener('click', function() {
            M.updateAddDraft({ selectedProducts: [], name: nameInput ? nameInput.value : (draft.name || '') });
            render(container);
        });
    }

    function mount(container) {
        _mounted = true;
        render(container || document.getElementById('add-derived'));
    }

    function unmount() {
        _mounted = false;
    }

    function refresh() {
        if (_mounted) render(document.getElementById('add-derived'));
    }

    if (M) {
        M.registerAddFlow({
            flow: 'derived',
            priority: 10,
            defaultTab: 'add-derived',
            condition: function(ctx) {
                if (ctx && ctx.groups && ctx.groups.length >= 1) {
                    for (var i = 0; i < ctx.groups.length; i++) {
                        if (ctx.groups[i].parentId) return true;
                    }
                }
                return false;
            },
            buildDraft: function(ctx) {
                if (ctx && ctx.ids && ctx.ids.length === 1) {
                    return _buildDerivedAddDraft(ctx);
                }
                return _buildDerivedDraftFromState(ctx);
            },
            onSubmit: _submitDerived,
            submitLabel: '创建派生组',
            submitTitle: '创建派生组'
        });

        M.registerEditAction({
            name: 'create-derived',
            label: '创建派生组',
            title: '创建派生组',
            priority: 10,
            condition: function(ctx) {
                return ctx && ctx.count === 1;
            },
            action: function(ctx, helpers) {
                if (!ctx || ctx.ids.length !== 1) { alert('请选择 1 行来创建派生组'); return; }
                var draft = _buildDerivedAddDraft(ctx);
                if (!draft.preselectedParentId) {
                    alert('无法识别选中的分组类型');
                    return;
                }
                helpers.exitEdit();
                M.enterAdd('derived');
                M.setAddDraft(draft);
                helpers.mountTab('add-derived');
                helpers.renderActions();
            },
            standalone: true
        });

        // 复制：和派生共用可编辑表单，预填源组设置后允许修改再保存。
        M.registerEditAction({
            name: 'clone',
            label: '<i class="fas fa-copy"></i>',
            title: '复制为派生组（可编辑后保存）',
            priority: 40,
            condition: function(ctx) { return ctx && ctx.count === 1; },
            action: function(ctx, helpers) {
                var draft = _buildCloneDraft(ctx);
                if (!draft) { alert('请选择 1 行来复制'); return; }
                helpers.exitEdit();
                M.enterAdd('derived');
                M.setAddDraft(draft);
                helpers.mountTab('add-derived');
                helpers.renderActions();
            },
            standalone: true
        });
    }

    GT.panels.add.derived = {
        mount: mount,
        unmount: unmount,
        refresh: refresh,
        render: render,
    };

    GT.log('panels/add/derived loaded');
})();
