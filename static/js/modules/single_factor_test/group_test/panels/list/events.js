/**
 * panels/list/events.js — 事件绑定 + 选择/编辑状态同步
 *
 * 挂载到 GT.panels.list.events。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.panels = GT.panels || {};
    GT.panels.list = GT.panels.list || {};

    var H, R, SEL;

    function _ensureDeps() {
        if (!H) H = GT.panels.list._helpers;
        if (!R) R = GT.panels.list.render;
    }

    function _setSEL(s) { SEL = s; }

    // =========================================================================
    // Selection / edit-mode sync
    // =========================================================================

    function toggleBatchSelection(batch) {
        _ensureDeps();
        if (!batch || !batch.items || batch.items.length === 0) return;
        if (!SEL) return;
        var allSelected = batch.items.every(function(bg) { return SEL.isSelected(bg.id); });
        if (allSelected) {
            for (var i = 0; i < batch.items.length; i++) { SEL.remove(batch.items[i].id); }
        } else {
            var ids = [];
            for (var i = 0; i < batch.items.length; i++) { ids.push(batch.items[i].id); }
            SEL.setBatch(ids);
        }
        syncEditMode();
    }

    function syncEditMode() {
        if (!SEL) return;
        var selCount = SEL.count();
        if (selCount > 0) {
            if (GT.tabs && GT.tabs.enterEditMode) GT.tabs.enterEditMode(SEL.getAll());
        } else {
            if (GT.tabs && GT.tabs.exitEditMode) GT.tabs.exitEditMode();
        }
    }

    // =========================================================================
    // Event binding (called by index.js after each fullRender)
    // =========================================================================

    function bindEvents(container, state) {
        _ensureDeps();
        // state = { fullRender, expandedBatches, lsSectionExpanded, getAddGroupBatchMap }
        var fullRender = state.fullRender;
        var batchMapRef = state.getAddGroupBatchMap || function() { return H.getAddGroupBatchMap(); };

        container.querySelectorAll('.unified-chip-toggle-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                if (state.showFullChips) {
                    state.showFullChips.val = !state.showFullChips.val;
                }
                if (typeof fullRender === 'function') fullRender();
            });
        });

        // ── LS section ──

        container.querySelectorAll('.unified-ls-row').forEach(function(row) {
            row.addEventListener('click', function(e) {
                if (e.target.closest('button')) return;
            });
        });

        container.querySelectorAll('.unified-ls-edit-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-ls-id');
                var data = GT.groupSettings.lsConfigs && GT.groupSettings.lsConfigs.get(id);
                if (data && R) R.lsShowModal(data);
            });
        });

        container.querySelectorAll('.unified-ls-del-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-ls-id');
                if (!confirm('确定删除此多空配置？')) return;
                try { GT.groupSettings.lsConfigs.remove(id); } catch (err) { alert('删除失败: ' + err.message); }
            });
        });

        // ── LS swap buttons ──
        container.querySelectorAll('.unified-ls-swap-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.getAttribute('data-ls-id');
                var ls = GT.groupSettings.lsConfigs && GT.groupSettings.lsConfigs.get(id);
                if (!ls) return;
                try {
                    // 只传交换后的 id，update 内部会自动重新派生 shortAlias
                    GT.groupSettings.lsConfigs.update(id, {
                        longGroupId: ls.shortGroupId,
                        shortGroupId: ls.longGroupId
                    });
                } catch (err) { alert('交换失败: ' + err.message); }
            });
        });

        // ── Batch delete buttons ──
        container.querySelectorAll('.unified-batch-del-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var addGroupBatchKey = this.getAttribute('data-batch-key');
                var ids = H.addGroupBatchGroupIds(addGroupBatchKey);
                if (ids.length === 0) return;
                try {
                    for (var i = 0; i < ids.length; i++) {
                        GT.groupSettings.groups.remove(ids[i]);
                    }
                } catch (err) { alert('删除失败: ' + err.message); }
            });
        });

        // ── Base group delete buttons ──
        container.querySelectorAll('.unified-bg-del-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var bgId = this.getAttribute('data-bg-id');
                try { GT.groupSettings.groups.remove(bgId); } catch (err) { alert('删除失败: ' + err.message); }
            });
        });

        // ── Base group rows ──
        container.querySelectorAll('.unified-bg-row').forEach(function(row) {
            row.addEventListener('click', function(e) {
                if (e.target.closest('button') || e.target.closest('.unified-backend-chip')) return;
                var id = this.getAttribute('data-bg-id');
                if (!SEL) return;
                SEL.toggle(id);
                syncEditMode();
            });
        });

        // ── Backend-registered clickable chips; overlays/data resolve lazily on click. ──
        // Non-actionable chips (factor / splitCount / letter summaries) must bubble so a
        // click anywhere on a batch header still selects the batch's base groups.
        container.querySelectorAll('.unified-backend-chip').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                var action = this.getAttribute('data-chip-action') || '';
                if (!action) return;
                e.stopPropagation();
                var groupId = this.getAttribute('data-gid') || '';
                var group = GT.groupSettings.groups && GT.groupSettings.groups.get(groupId);
                if (!group) return;
                if (action === 'product-path-selection-products' && GT.overlays && GT.overlays.productPathSelectionProducts) {
                    var selection = H.nodeProductPathSelection(group);
                    var products = H.productPathSelectionProducts(selection);
                    var label = H.productPathSelectionLabel(selection);
                    GT.overlays.productPathSelectionProducts.open(label, products, selection);
                } else if (action === 'toggle-product-mask') {
                    if (GT.backendSettings && typeof GT.backendSettings.toggleProductMask === 'function') {
                        GT.backendSettings.toggleProductMask(groupId);
                    }
                    if (typeof fullRender === 'function') fullRender();
                }
            });
        });

        // ── Tree nodes ──
        container.querySelectorAll('.unified-node-header').forEach(function(header) {
            header.addEventListener('click', function(e) {
                if (e.target.closest('button') || e.target.closest('.unified-backend-chip') || e.target.closest('.unified-tree-expand')) return;
                var nodeId = this.parentElement.getAttribute('data-node-id');
                if (!SEL) return;
                SEL.toggle(nodeId);
                syncEditMode();
            });
        });

        // ── Derived delete ──
        container.querySelectorAll('.unified-dg-del-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var dgId = this.getAttribute('data-dg-id');
                try { GT.groupSettings.groups.remove(dgId); } catch (err) { alert('删除失败: ' + err.message); }
            });
        });
    }

    /**
     * Build the delegated container-level click handler.
     * Called once in mount(); survives fullRender because of event delegation.
     */
    function buildContainerDelegate(expandedBatchesRef, lsSectionExpandedRef, fullRenderFn) {
        return function containerClick(e) {
            _ensureDeps();

            // LS section expand/collapse
            var lsExpandEl = e.target.closest('.ls-section-expand');
            if (lsExpandEl) {
                e.stopPropagation();
                lsSectionExpandedRef.val = !lsSectionExpandedRef.val;
                fullRenderFn();
                return;
            }

            // Batch expand/collapse
            var expandEl = e.target.closest('.unified-batch-expand');
            if (expandEl) {
                e.stopPropagation();
                var header = expandEl.closest('.unified-batch-header');
                if (!header) return;
                var key = header.getAttribute('data-batch-key');
                expandedBatchesRef[key] = !expandedBatchesRef[key];
                fullRenderFn();
                return;
            }

            // Tree node expand triangle → toggle children
            var treeExpand = e.target.closest('.unified-tree-expand');
            if (treeExpand) {
                e.stopPropagation();
                var nodeEl = treeExpand.closest('.unified-tree-node');
                var nodeId = nodeEl ? nodeEl.getAttribute('data-node-id') : null;
                if (nodeId && GT.groupSettings.groups && GT.groupSettings.groups.toggleExpanded) {
                    GT.groupSettings.groups.toggleExpanded(nodeId);
                    fullRenderFn();
                }
                return;
            }

            // Batch header row → toggle selection (= multi-select the batch's first-level base
            // groups and enter edit mode). Only actionable chips (e.g. the product-path chip that
            // opens an overlay) block selection; summary chips fall through.
            var batchHeader = e.target.closest('.unified-batch-header');
            var actionableChip = e.target.closest('.unified-backend-chip[data-chip-action]:not([data-chip-action=""])');
            if (batchHeader && !e.target.closest('button') && !actionableChip) {
                var addGroupBatchKey = batchHeader.getAttribute('data-batch-key');
                var batchMap = H.getAddGroupBatchMap();
                toggleBatchSelection(batchMap[addGroupBatchKey]);
            }
        };
    }

    // =========================================================================
    // Export
    // =========================================================================

    GT.panels.list.events = {
        _setSEL: _setSEL,
        toggleBatchSelection: toggleBatchSelection,
        syncEditMode: syncEditMode,
        bindEvents: bindEvents,
        buildContainerDelegate: buildContainerDelegate,
    };
})();
