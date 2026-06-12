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

    var H, REG, R, SEL;

    function _ensureDeps() {
        if (!H) H = GT.panels.list._helpers;
        if (!REG) REG = window.GT_CONFIG_REGISTRY;
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
                if (!confirm('确定删除此批次（共 ' + ids.length + ' 组）？')) return;
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
                if (!confirm('确定删除此基础组？')) return;
                try { GT.groupSettings.groups.remove(bgId); } catch (err) { alert('删除失败: ' + err.message); }
            });
        });

        // ── Base group rows ──
        container.querySelectorAll('.unified-bg-row').forEach(function(row) {
            row.addEventListener('click', function(e) {
                if (e.target.closest('button') || e.target.closest('.unified-config-chip') || e.target.closest('.unified-tester-chip')) return;
                var id = this.getAttribute('data-bg-id');
                if (!SEL) return;
                SEL.toggle(id);
                syncEditMode();
            });
        });

        // ── Config chips (base + derived) ──
        container.querySelectorAll('.unified-config-chip').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var chipLabel = this.getAttribute('data-chip-label');
                var gid = this.getAttribute('data-gid');
                var dgid = this.getAttribute('data-dgid');
                var group = null;
                var synthGroup = null;
                if (gid) {
                    group = GT.groupSettings.groups && GT.groupSettings.groups.get(gid);
                    synthGroup = group;
                } else if (dgid) {
                    group = GT.groupSettings.groups && GT.groupSettings.groups.get(dgid);
                    synthGroup = H.synthGroupForDerivedNode(group);
                }
                if (!group || !synthGroup) return;
                if (REG && typeof REG.getChips === 'function') {
                    var chips = REG.getChips(synthGroup);
                    for (var ci = 0; ci < chips.length; ci++) {
                        if (chips[ci].label === chipLabel && typeof chips[ci].onClick === 'function') {
                            chips[ci].onClick(this, synthGroup);
                            break;
                        }
                    }
                }
            });
        });

        // ── Tester chips ──
        container.querySelectorAll('.unified-tester-chip').forEach(function(chip) {
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var testerId = this.getAttribute('data-tester-id');
                if (GT.overlays && GT.overlays.testerProducts) {
                    var products = H.testerProducts(testerId);
                    var label = H.testerLabel(testerId);
                    GT.overlays.testerProducts.open(label, products);
                }
            });
        });

        // ── Tree nodes ──
        container.querySelectorAll('.unified-node-header').forEach(function(header) {
            header.addEventListener('click', function(e) {
                if (e.target.closest('button') || e.target.closest('.unified-config-chip') || e.target.closest('.unified-dg-product-chip') || e.target.closest('.unified-tree-expand')) return;
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
                if (!confirm('确定删除此派生组及其所有子节点？')) return;
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

            // Derived product chip → toggle product list
            var prodChip = e.target.closest('.unified-dg-product-chip');
            if (prodChip) {
                e.stopPropagation();
                var dgId = prodChip.getAttribute('data-dg-id');
                if (REG && REG._expandedProducts) {
                    REG._expandedProducts[dgId] = !REG._expandedProducts[dgId];
                }
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

            // Batch header row → toggle selection
            var batchHeader = e.target.closest('.unified-batch-header');
            if (batchHeader && !e.target.closest('button')) {
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
