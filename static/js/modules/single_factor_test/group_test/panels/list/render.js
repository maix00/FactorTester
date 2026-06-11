/**
 * panels/list/render.js — 渲染函数
 *
 * 所有 HTML 渲染逻辑集中在此，通过 H 访问 helpers。
 * 挂载到 GT.panels.list.render。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.panels = GT.panels || {};
    GT.panels.list = GT.panels.list || {};

    var H, REG, SEL;

    function _ensureDeps() {
        if (!H) H = GT.panels.list._helpers;
        if (!REG) REG = window.GT_CONFIG_REGISTRY;
    }

    function _setSEL(s) { SEL = s; }

    // =========================================================================
    // LS (Long-Short) modal helpers
    // =========================================================================

    var _lsModalId = 'unified-ls-form-modal';
    var _lsFormId = 'unified-ls-form';

    function lsShowModal(editData) {
        _ensureDeps();
        var existing = H.$(_lsModalId);
        if (existing) existing.remove();

        var isEdit = !!editData;
        var title = isEdit ? '编辑多空配置' : '新增多空配置';

        var dgOptions = [];
        if (GT.groupSettings.groups && GT.groupSettings.groups.list) {
            dgOptions = GT.groupSettings.groups.list();
        }

        var html = '<div id="' + _lsModalId + '" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:10000;">';
        html += '<div style="background:#fff;border-radius:8px;padding:24px;min-width:460px;max-width:560px;box-shadow:0 8px 32px rgba(0,0,0,0.2);">';
        html += '<h3 style="margin:0 0 16px 0;">' + title + '</h3>';
        html += '<form id="' + _lsFormId + '" onsubmit="return false;">';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">名称 <span style="color:red;">*</span></span>';
        html += '<input type="text" id="lsf_name" value="' + H.escapeHTML(isEdit ? editData.name : '') + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '</label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">多头组 <span style="color:red;">*</span></span>';
        html += '<select id="lsf_longGroupId" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '<option value="">— 选择派生组 —</option>';
        var longSel = isEdit ? editData.longGroupId : '';
        for (var i = 0; i < dgOptions.length; i++) {
            var sel = dgOptions[i].id === longSel ? ' selected' : '';
            html += '<option value="' + H.escapeHTML(dgOptions[i].id) + '"' + sel + '>' + H.escapeHTML(dgOptions[i].name || dgOptions[i].id) + '</option>';
        }
        html += '</select></label>';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">空头组 <span style="color:red;">*</span></span>';
        html += '<select id="lsf_shortGroupId" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '<option value="">— 选择派生组 —</option>';
        var shortSel = isEdit ? editData.shortGroupId : '';
        for (var j = 0; j < dgOptions.length; j++) {
            var sel2 = dgOptions[j].id === shortSel ? ' selected' : '';
            html += '<option value="' + H.escapeHTML(dgOptions[j].id) + '"' + sel2 + '>' + H.escapeHTML(dgOptions[j].name || dgOptions[j].id) + '</option>';
        }
        html += '</select></label>';

        html += '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">';
        html += '<button type="button" id="lsf-cancel" style="padding:6px 16px;border:1px solid #ddd;border-radius:4px;background:#f6f8fa;cursor:pointer;">取消</button>';
        html += '<button type="submit" id="lsf-save" style="padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">' + (isEdit ? '保存' : '新增') + '</button>';
        html += '</div>';
        html += '</form></div></div>';

        document.body.insertAdjacentHTML('beforeend', html);
        H.$(_lsModalId)._editId = isEdit ? editData.id : null;

        H.$('lsf-cancel').addEventListener('click', lsCloseModal);
        H.$(_lsFormId).addEventListener('submit', lsHandleFormSubmit);
        H.$(_lsModalId).addEventListener('click', function(e) { if (e.target === this) lsCloseModal(); });
    }

    function lsCloseModal() {
        _ensureDeps();
        var m = H.$(_lsModalId);
        if (m) m.remove();
    }

    function lsHandleFormSubmit(e) {
        _ensureDeps();
        e.preventDefault();
        var editId = H.$(_lsModalId)._editId;
        var data = {
            name: H.$('lsf_name').value.trim(),
            longGroupId: H.$('lsf_longGroupId').value,
            shortGroupId: H.$('lsf_shortGroupId').value,
        };
        try {
            if (editId) { GT.groupSettings.lsConfigs.update(editId, data); }
            else { GT.groupSettings.lsConfigs.add(data); }
            lsCloseModal();
        } catch (err) { alert('操作失败: ' + err.message); }
    }

    // =========================================================================
    // Derived add-child / edit / delete modals
    // =========================================================================

    var _dgModalId = 'unified-dg-form-modal';
    var _dgFormId = 'unified-dg-form';

    function dgShowModal(editData, parentNodeId) {
        _ensureDeps();
        var existing = H.$(_dgModalId);
        if (existing) existing.remove();

        var isEdit = !!editData;
        var isAddChild = !isEdit && !!parentNodeId;
        var title = isEdit ? '编辑派生组' : (isAddChild ? '新增子派生组' : '新增派生组');

        var bgs = GT.groupSettings.groups.getAll();
        var html = '<div id="' + _dgModalId + '" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:10000;">';
        html += '<div style="background:#fff;border-radius:8px;padding:24px;min-width:480px;max-width:600px;box-shadow:0 8px 32px rgba(0,0,0,0.2);">';
        html += '<h3 style="margin:0 0 16px 0;">' + title + '</h3>';
        html += '<form id="' + _dgFormId + '" onsubmit="return false;">';

        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">名称 <span style="color:red;">*</span></span>';
        html += '<input type="text" id="dg-f-name" value="' + H.escapeHTML(isEdit ? editData.name : '') + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;" required>';
        html += '</label>';

        if (!isEdit) {
            html += '<label style="display:block;margin-bottom:12px;">';
            html += '<span style="display:block;font-size:13px;margin-bottom:4px;">基础组 <span style="color:red;">*</span></span>';
            html += '<select id="dg-f-parentId" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;">';
            html += '<option value="">— 选择 —</option>';
            for (var i = 0; i < bgs.length; i++) {
                html += '<option value="' + H.escapeHTML(bgs[i].id) + '">' + H.escapeHTML(bgs[i].label) + ' (' + H.escapeHTML(bgs[i].factorAlias) + ')</option>';
            }
            html += '</select></label>';
        }

        // product mask
        html += '<label style="display:block;margin-bottom:12px;">';
        html += '<span style="display:block;font-size:13px;margin-bottom:4px;">品种筛选（留空=全选）</span>';
        html += '<div id="dg-f-product-mask" style="max-height:120px;overflow-y:auto;border:1px solid #ddd;border-radius:4px;padding:4px 8px;">';
        var testerProds = [];
        if (isEdit) { testerProds = H.nodeProducts(editData); }
        else if (parentNodeId) { var pn = GT.groupSettings.groups && GT.groupSettings.groups.get(parentNodeId); testerProds = pn ? H.nodeProducts(pn) : []; }
        else {
            var allPs = {};
            for (var bi = 0; bi < bgs.length; bi++) {
                var pp = H.testerProducts(bgs[bi].testerId);
                for (var pi = 0; pi < pp.length; pi++) { allPs[pp[pi].name] = pp[pi]; }
            }
            testerProds = Object.keys(allPs).map(function(k) { return allPs[k]; });
        }
        var existingMask = (editData && editData.productMask) ? editData.productMask : {};
        for (var ti = 0; ti < testerProds.length; ti++) {
            var pName = testerProds[ti].name;
            var checked = Object.keys(existingMask).length === 0 ? ' checked' : (existingMask[pName] ? ' checked' : '');
            html += '<label style="display:inline-block;margin-right:12px;font-size:12px;"><input type="checkbox" class="dg-f-prod" value="' + H.escapeHTML(pName) + '"' + checked + '> ' + H.escapeHTML(pName) + '</label>';
        }
        html += '</div></label>';

        html += '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">';
        html += '<button type="button" id="dg-f-cancel" style="padding:6px 16px;border:1px solid #ddd;border-radius:4px;background:#f6f8fa;cursor:pointer;">取消</button>';
        html += '<button type="submit" id="dg-f-save" style="padding:6px 16px;border:none;border-radius:4px;background:#0078d4;color:#fff;cursor:pointer;">' + (isEdit ? '保存' : '新增') + '</button>';
        html += '</div>';
        html += '</form></div></div>';

        document.body.insertAdjacentHTML('beforeend', html);
        H.$(_dgModalId)._editId = isEdit ? editData.id : null;
        H.$(_dgModalId)._parentId = parentNodeId || null;

        H.$('dg-f-cancel').addEventListener('click', dgCloseModal);
        H.$(_dgFormId).addEventListener('submit', dgHandleSubmit);
        H.$(_dgModalId).addEventListener('click', function(e) { if (e.target === this) dgCloseModal(); });
    }

    function dgCloseModal() {
        _ensureDeps();
        var m = H.$(_dgModalId);
        if (m) m.remove();
    }

    function dgHandleSubmit(e) {
        _ensureDeps();
        e.preventDefault();
        var modal = H.$(_dgModalId);
        var editId = modal._editId;
        var parentId = modal._parentId;
        var data = { name: H.$('dg-f-name').value.trim(), parentId: parentId || null };
        if (!editId) {
            data.parentId = H.$('dg-f-parentId').value;
            if (!data.parentId) { alert('请选择基础组'); return; }
        }
        var cbs = document.querySelectorAll('#dg-f-product-mask .dg-f-prod');
        var mask = {};
        if (cbs.length > 0) { for (var i = 0; i < cbs.length; i++) { mask[cbs[i].value] = cbs[i].checked; } }
        data.productMask = mask;

        try {
            if (editId) { GT.groupSettings.groups.update(editId, data); }
            else { GT.groupSettings.groups.add(data); }
            dgCloseModal();
        } catch (err) { alert('操作失败: ' + err.message); }
    }

    // =========================================================================
    // Render functions
    // =========================================================================

    function _renderLSSection(lsSectionExpanded) {
        _ensureDeps();
        var items = GT.groupSettings.lsConfigs.getAll();
        if (items.length === 0) return '';
        var h = '';

        h += '<div class="unified-section-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 4px;margin-bottom:4px;border-bottom:2px solid #e0e7ff;cursor:pointer;" id="ls-section-header">';
        h += '<div style="display:flex;align-items:center;gap:6px;">';
        h += '<span class="ls-section-expand" style="font-size:18px;line-height:1;width:20px;text-align:center;">' + (lsSectionExpanded ? '▾' : '▸') + '</span>';
        h += '<span style="font-size:14px;font-weight:700;color:#3730a3;">⚡ Long-Short 组</span>';
        h += '<span style="font-size:11px;color:#666;">(' + items.length + ')</span>';
        h += '</div>';
        h += '</div>';

        if (lsSectionExpanded) {
            h += '<div id="ls-section-body" style="margin-left:8px;border-left:2px solid #e0e7ff;padding-left:4px;">';
            h += '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
            h += '<tbody>';

            for (var i = 0; i < items.length; i++) {
                var item = items[i];

                h += '<tr class="unified-ls-row" data-ls-id="' + H.escapeHTML(item.id) + '" style="cursor:pointer;border-bottom:1px solid #e8eaed;">';

                h += '<td style="padding:6px 8px;white-space:nowrap;">';
                h += '<span style="font-weight:600;color:#4338ca;font-size:13px;">' + H.escapeHTML(item.shortAlias || item.name) + '</span>';
                h += '</td>';

                h += '<td style="padding:2px 4px;width:100%;">';
                var longDg = H.getGroup(item.longGroupId);
                var shortDg = H.getGroup(item.shortGroupId);
                h += '<div style="display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding:2px 0;">';
                h += '<span style="font-size:10px;color:#3b82f6;font-weight:600;margin-right:4px;">📈</span>';
                if (longDg) h += H.renderAllChipsForGroup(longDg);
                h += '</div>';
                h += '<div style="display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding:2px 0;">';
                h += '<span style="font-size:10px;color:#8b5cf6;font-weight:600;margin-right:4px;">📉</span>';
                if (shortDg) h += H.renderAllChipsForGroup(shortDg);
                h += '</div>';
                h += '</td>';

                h += '<td style="padding:6px 8px;text-align:right;white-space:nowrap;">';
                h += '<button class="unified-ls-swap-btn" data-ls-id="' + H.escapeHTML(item.id) + '" title="交换多头/空头" style="padding:1px 5px;font-size:13px;border:1px solid #c7d2fe;border-radius:3px;background:#eef2ff;color:#4338ca;cursor:pointer;margin-right:4px;">🔄</button>';
                h += '<button class="unified-ls-del-btn" data-ls-id="' + H.escapeHTML(item.id) + '" style="padding:1px 5px;font-size:11px;border:1px solid #fca5a5;border-radius:3px;background:#fef2f2;color:#dc2626;cursor:pointer;">✕</button>';
                h += '</td></tr>';
            }
            h += '</tbody></table>';
            h += '</div>';
        }
        return h;
    }

    function _renderBaseSection(expandedBatches, collapsedIds) {
        _ensureDeps();
        var items = GT.groupSettings.groups.getAll();
        if (items.length === 0) {
            return '<div class="unified-section-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 4px;margin-bottom:4px;border-bottom:2px solid #e2e8f0;">'
                + '<span style="font-size:14px;font-weight:700;color:#1e293b;">📦 分组组合</span></div>'
                + '<div style="padding:16px;text-align:center;color:#888;font-size:12px;">暂无分组组合</div>';
        }
        var batches = H.buildBatches(items);
        var h = '';
        h += '<div class="unified-section-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 4px;margin-bottom:4px;border-bottom:2px solid #e2e8f0;">';
        h += '<span style="font-size:14px;font-weight:700;color:#1e293b;">📦 分组组合</span>';
        h += '<span style="font-size:11px;color:#666;">' + items.length + ' 个组 / ' + batches.length + ' 批</span>';
        h += '</div>';

        for (var bi = 0; bi < batches.length; bi++) {
            var batch = batches[bi];
            var batchId = batch.key;
            var isExpanded = batches.length === 1 ? true : (expandedBatches[batchId] === true);
            var isCollapsed = collapsedIds && collapsedIds[batchId];

            var batchLetter = '';
            if (batch.items.length > 0) {
                var extractLetter = GT.groupSettings.groups && GT.groupSettings.groups.extractLetter;
                if (extractLetter) {
                    batchLetter = extractLetter(batch.items[0].shortAlias) || '';
                }
            }

            var testerLabel = H.testerLabel(batch.testerId);
            var batchAllSelected = batch.items.every(function(bg) { return SEL && SEL.isSelected(bg.id); });
            var batchHeaderStyle = 'display:flex;align-items:center;flex-wrap:wrap;gap:2px 6px;padding:6px 8px;margin-top:4px;border-radius:6px;cursor:pointer;font-size:13px;';
            if (batchAllSelected && batch.items.length > 0) {
                batchHeaderStyle += 'background:#eef2ff;box-shadow:inset 3px 0 0 #6366f1;';
            } else {
                batchHeaderStyle += 'background:#f1f5f9;';
            }
            h += '<div class="unified-batch-header' + (batchAllSelected && batch.items.length > 0 ? ' gt-row-selected' : '') + '" data-batch-key="' + H.escapeHTML(batchId) + '" data-selected="' + (batchAllSelected ? '1' : '0') + '" style="' + batchHeaderStyle + '">';
            h += '<span class="unified-batch-expand" style="margin-right:6px;width:20px;text-align:center;cursor:pointer;font-size:18px;line-height:1;">' + (isExpanded ? '▾' : '▸') + '</span>';
            h += '<span class="unified-batch-selector" style="display:inline-flex;align-items:center;gap:6px;flex:1;">';
            if (batchLetter) {
                h += '<span style="font-weight:700;color:#4338ca;min-width:24px;">' + H.escapeHTML(batchLetter) + '</span>';
            }
            h += '<span style="font-weight:600;">' + H.escapeHTML(batch.factorAlias) + '</span>';
            h += '<span style="color:#555;">' + H.escapeHTML(testerLabel) + '</span>';
            h += '<span style="color:#888;font-size:11px;">' + batch.groupCount + '组</span>';
            h += '</span>';
            h += '<button class="unified-batch-del-btn" data-batch-key="' + H.escapeHTML(batchId) + '" style="margin-left:auto;padding:1px 5px;font-size:11px;border:1px solid #fca5a5;border-radius:3px;background:#fef2f2;color:#dc2626;cursor:pointer;flex-shrink:0;">✕</button>';
            h += '</div>';

            if (isExpanded && !isCollapsed) {
                var batchBodyStyle = 'margin-left:16px;border-left:2px solid #e2e8f0;padding-left:8px;';
                if (batchAllSelected && batch.items.length > 0) {
                    batchBodyStyle += 'background:rgba(238,242,255,0.5);border-left-color:#a5b4fc;border-radius:0 6px 6px 0;';
                }
                h += '<div class="unified-batch-body" style="' + batchBodyStyle + '">';
                for (var ri = 0; ri < batch.items.length; ri++) {
                    var bg = batch.items[ri];
                    var bgSelected = SEL && SEL.isSelected(bg.id);

                    h += '<div class="unified-bg-row" data-bg-id="' + H.escapeHTML(bg.id) + '" style="display:flex;align-items:center;flex-wrap:wrap;gap:2px 6px;padding:4px 6px;border-radius:6px;border-bottom:1px solid #f0f0f0;font-size:12px;' + (bgSelected ? 'background:#eef2ff;box-shadow:inset 3px 0 0 #6366f1;' : '') + '">';
                    h += '<span style="width:6px;height:6px;border-radius:50%;background:#6366f1;margin-right:8px;flex-shrink:0;"></span>';
                    if (bg.shortAlias) {
                        h += '<span style="font-weight:600;color:#4338ca;min-width:32px;font-size:13px;margin-right:8px;">' + H.escapeHTML(bg.shortAlias) + '</span>';
                    }
                    var allChips = (REG && typeof REG.getAllChips === 'function') ? REG.getAllChips(bg) : [];
                    h += '<span style="display:flex;flex-wrap:wrap;align-items:center;gap:4px;flex:1;min-width:0;">';
                    for (var ci = 0; ci < allChips.length; ci++) {
                        var chip = allChips[ci];
                        var s = chip.style || H.CHIP_STYLE_PLAIN;
                        if (chip.category === 'config') continue;
                        if (chip.label === 'tester') {
                            h += '<span class="unified-tester-chip" data-tester-id="' + H.escapeHTML(bg.testerId) + '" style="' + s + ';">' + chip.html + '</span>';
                        } else {
                            h += '<span style="' + s + ';">' + chip.html + '</span>';
                        }
                    }
                    h += '</span>';
                    h += '<span style="display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end;flex-shrink:0;">';
                    for (ci = 0; ci < allChips.length; ci++) {
                        chip = allChips[ci];
                        if (chip.category !== 'config') continue;
                        s = chip.style || H.CHIP_STYLE_PLAIN;
                        if (chip.onClick) {
                            var cls2 = ' class="unified-config-chip" data-gid="' + H.escapeHTML(bg.id) + '" data-chip-label="' + H.escapeHTML(chip.label) + '"';
                            h += '<span' + cls2 + ' style="' + s + ';">' + chip.html + '</span>';
                        } else {
                            h += '<span style="' + s + ';">' + chip.html + '</span>';
                        }
                    }
                    h += '</span>';
                    h += '<button class="unified-bg-del-btn" data-bg-id="' + H.escapeHTML(bg.id) + '" style="margin-left:4px;padding:1px 5px;font-size:11px;border:1px solid #fca5a5;border-radius:3px;background:#fef2f2;color:#dc2626;cursor:pointer;">✕</button>';
                    h += '</div>';
                    h += _renderDerivedTreeForBase(bg.id, expandedBatches);
                }
                h += '</div>';
            }
        }
        return h;
    }

    function _renderDerivedTreeForBase(rootGroupId, expandedBatches) {
        _ensureDeps();
        if (!GT.groupSettings.groups) return '';
        var allNodes = GT.groupSettings.groups.getAll();
        var myNodes = [];
        for (var i = 0; i < allNodes.length; i++) {
            if (allNodes[i].parentId === rootGroupId) {
                myNodes.push(allNodes[i]);
            }
        }
        if (myNodes.length === 0) return '';

        // Build tree nodes from flat list using parentId
        var treeById = {};
        for (var j = 0; j < myNodes.length; j++) {
            var n = myNodes[j];
            n.children = [];
            treeById[n.id] = n;
        }
        // Link children (grandchildren, etc.) by walking parentId chain within myNodes
        for (var j = 0; j < myNodes.length; j++) {
            var n2 = myNodes[j];
            var allFlat = GT.groupSettings.groups.getAll();
            for (var ki = 0; ki < allFlat.length; ki++) {
                if (allFlat[ki].parentId === n2.id) {
                    var childId = allFlat[ki].id;
                    if (treeById[childId]) {
                        treeById[n2.id].children.push(treeById[childId]);
                    }
                }
            }
        }

        var roots = [];
        for (var k = 0; k < myNodes.length; k++) {
            var pid = myNodes[k].parentId;
            if (!pid || pid === rootGroupId) {
                var treeNode = treeById[myNodes[k].id];
                if (treeNode) roots.push(treeNode);
            }
        }

        if (roots.length === 0) return '';

        var h = '<div class="unified-derived-subtree" style="margin-left:16px;border-left:2px solid #c7d2fe;padding-left:8px;">';
        for (var r = 0; r < roots.length; r++) {
            h += _renderNode(roots[r], 0, expandedBatches);
        }
        h += '</div>';
        return h;
    }

    function _renderDerivedSection() {
        return '';
    }

    function _renderNode(node, depth, expandedBatches) {
        _ensureDeps();
        if (!node) return '';
        var indent = depth * 18;
        var isExp = (node._expanded !== false);
        var shortAlias = H.deriveShortAlias(node);
        var products = H.nodeProducts(node);
        var chips = H.deriveOverrideChips(node);
        var prodExpanded = REG && REG._expandedProducts && REG._expandedProducts[node.id] === true;
        var hasKids = node.children && node.children.length > 0;

        var nodeSelected = SEL && SEL.isSelected(node.id);
        var rowStyle = 'display:flex;align-items:center;flex-wrap:wrap;padding:4px 6px;border-radius:6px;border-bottom:1px solid #f0f0f0;font-size:12px;gap:2px 6px;';
        if (nodeSelected) { rowStyle += 'background:#eef2ff;box-shadow:inset 3px 0 0 #6366f1;'; }

        var h = '';
        h += '<div class="unified-tree-node" data-node-id="' + H.escapeHTML(node.id) + '" style="padding:4px 0;">';

        h += '<div class="unified-node-header" style="' + rowStyle + 'margin-left:' + indent + 'px;cursor:pointer;">';
        h += '<span style="width:6px;height:6px;border-radius:50%;background:#6366f1;margin-right:8px;flex-shrink:0;"></span>';
        if (hasKids) {
            h += '<span class="unified-tree-expand" style="width:20px;text-align:center;margin-right:2px;font-size:14px;line-height:1;flex-shrink:0;">' + (isExp ? '▾' : '▸') + '</span>';
        } else {
            h += '<span style="width:20px;margin-right:2px;flex-shrink:0;"></span>';
        }
        if (shortAlias) {
            h += '<span style="font-weight:600;color:#4338ca;min-width:32px;font-size:13px;margin-right:8px;">' + H.escapeHTML(shortAlias) + '</span>';
        }
        h += '<span style="flex:1;"></span>';
        if (chips.length > 0) {
            h += '<span style="display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end;flex-shrink:0;margin-right:4px;">';
            for (var dci = 0; dci < chips.length; dci++) {
                var dchip = chips[dci];
                var ds = dchip.style || H.CHIP_STYLE_PLAIN;
                var dcls = dchip.onClick ? ' class="unified-config-chip" data-dgid="' + H.escapeHTML(node.id) + '" data-chip-label="' + H.escapeHTML(dchip.label) + '"' : '';
                h += '<span' + dcls + ' style="' + ds + ';">' + dchip.html + '</span>';
            }
            h += '</span>';
        }
        var tri = prodExpanded ? '▾' : '▸';
        h += '<span class="unified-dg-product-chip" data-dg-id="' + H.escapeHTML(node.id) + '" style="display:inline-flex;align-items:center;cursor:pointer;background:#c7d2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#312e81;margin-right:8px;flex-shrink:0;">📋 ' + products.length + '品种 ' + tri + '</span>';
        h += '<button class="unified-dg-del-btn" data-dg-id="' + H.escapeHTML(node.id) + '" style="margin-left:4px;padding:1px 5px;font-size:11px;border:1px solid #fca5a5;border-radius:3px;background:#fef2f2;color:#dc2626;cursor:pointer;">✕</button>';
        h += '</div>';

        if (prodExpanded && products.length > 0) {
            h += '<div class="unified-dg-product-list" style="margin-left:' + (indent + 34) + 'px;padding:4px 8px;border-left:2px solid #c7d2fe;font-size:11px;">';
            for (var pi = 0; pi < products.length; pi++) {
                var pn = products[pi].name;
                var pd = products[pi].desc || '';
                h += '<div style="padding:2px 0;display:flex;align-items:baseline;">';
                h += '<a href="/products?product=' + encodeURIComponent(pn) + '" target="_blank" style="color:#0078d4;text-decoration:none;font-weight:600;margin-right:8px;" onclick="event.stopPropagation();">' + H.escapeHTML(pn) + '</a>';
                if (pd) {
                    h += '<span style="color:#9ca3af;">' + H.escapeHTML(pd) + '</span>';
                }
                h += '</div>';
            }
            h += '</div>';
        }

        if (isExp && hasKids) {
            for (var ci = 0; ci < node.children.length; ci++) {
                h += _renderNode(node.children[ci], depth + 1, expandedBatches);
            }
        }
        h += '</div>';
        return h;
    }

    // =========================================================================
    // Export
    // =========================================================================

    GT.panels.list.render = {
        _setSEL: _setSEL,
        lsShowModal: lsShowModal,
        lsCloseModal: lsCloseModal,
        dgShowModal: dgShowModal,
        dgCloseModal: dgCloseModal,
        renderLSSection: _renderLSSection,
        renderBaseSection: _renderBaseSection,
        renderDerivedTreeForBase: _renderDerivedTreeForBase,
        renderDerivedSection: _renderDerivedSection,
        renderNode: _renderNode,
    };
})();
