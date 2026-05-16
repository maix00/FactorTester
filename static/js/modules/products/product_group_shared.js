/**
 * Product Group Shared — 产品组 API 和渲染的共享模块。
 * 供 product_group_manager.js 和 category_filter_module.js 共用。
 * 依赖：jQuery, window.escHtml（或内联实现）
 */
(function($, window) {
    'use strict';

    var _escHtml = window.escHtml || function(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    // ── API ──────────────────────────────────────────────────────────────────

    function _api(method, url, body) {
        var opts = { method: method, headers: {'Content-Type': 'application/json'} };
        if (body) opts.body = JSON.stringify(body);
        return fetch(url, opts).then(function(r) { return r.json(); });
    }

    /** GET /api/product-groups → {groups: [...]} or [] */
    function fetchGroups() {
        return _api('GET', '/api/product-groups').then(function(resp) {
            return (resp && resp.groups) ? resp.groups : [];
        }).catch(function() {
            return [];
        });
    }

    /** GET /api/product-groups/<name> → {group: {...}} or null */
    function fetchGroupDetail(name) {
        return _api('GET', '/api/product-groups/' + encodeURIComponent(name)).then(function(resp) {
            return (resp && resp.group) ? resp.group : null;
        }).catch(function() {
            return null;
        });
    }

    /** POST /api/product-groups → {success, group} */
    function createGroup(name, paths) {
        return _api('POST', '/api/product-groups', {name: name, paths: paths});
    }

    /** PUT /api/product-groups/<name> → {success, group} */
    function updateGroup(name, paths) {
        return _api('PUT', '/api/product-groups/' + encodeURIComponent(name), {paths: paths});
    }

    /** DELETE /api/product-groups/<name> → {success} */
    function deleteGroup(name) {
        return _api('DELETE', '/api/product-groups/' + encodeURIComponent(name));
    }

    /** PUT /api/product-groups/reorder → {success} */
    function reorderGroups(names) {
        return _api('PUT', '/api/product-groups/reorder', {names: names});
    }

    /** PUT /api/product-groups/<oldName>/rename → {success} */
    function renameGroup(oldName, newName) {
        return _api('PUT', '/api/product-groups/' + encodeURIComponent(oldName) + '/rename', {name: newName});
    }

    // ── Render ───────────────────────────────────────────────────────────────

    /**
     * 渲染产品组列表 HTML 字符串。
     * @param {Array} groups - 产品组数组 [{name, paths, product_count, product_names}, ...]
     * @param {string} [activeName] - 高亮的当前组名
     * @param {object} [opts]
     * @param {boolean} [opts.showDelete=true] - 是否显示删除按钮
     * @param {string} [opts.itemClass='pg-group-item'] - 每个 item 的 CSS 类
     * @param {string} [opts.emptyText='暂无产品组'] - 空列表提示
     * @returns {string} HTML
     */
    function renderGroupListHTML(groups, activeName, opts) {
        opts = opts || {};
        var showDel = opts.showDelete !== false;
        var itemClass = opts.itemClass || 'pg-group-item';
        var emptyText = opts.emptyText || '暂无产品组';

        if (!groups || groups.length === 0) {
            return '<div style="color:#888; font-size:12px;">' + _escHtml(emptyText) + '</div>';
        }
        var html = '';
        for (var i = 0; i < groups.length; i++) {
            var g = groups[i];
            var cnt = (g.product_count != null) ? g.product_count : (g.product_names ? g.product_names.length : (g.paths ? g.paths.length : 0));
            var activeStyle = (activeName && g.name === activeName) ? ' style="background:#e8f0fe; font-weight:600;"' : '';
            html += '<div class="' + itemClass + '" data-name="' + _escHtml(g.name) + '"' + activeStyle + '>' +
                '<span style="flex:1; cursor:pointer;" class="pg-group-name">' + _escHtml(g.name) + ' (' + cnt + '个产品)</span>';
            if (showDel) {
                html += '<button class="pg-group-del" data-name="' + _escHtml(g.name) + '" title="删除" style="background:none; border:none; color:#d32f2f; cursor:pointer; font-size:14px;">&times;</button>';
            }
            html += '</div>';
        }
        return html;
    }

    /**
     * 渲染产品详情 HTML（产品名 + desc）。
     * @param {object} group - {product_names: [...], ...}
     * @param {object} [descMap] - {productName: desc} 映射表
     * @returns {string} HTML
     */
    function renderProductDetailHTML(group, descMap) {
        descMap = descMap || {};
        var names = group && group.product_names ? group.product_names : [];
        if (!names.length) return '';
        var html = '';
        for (var i = 0; i < names.length; i++) {
            var pn = names[i];
            var desc = descMap[pn] || '';
            html += '<div style="padding:2px 0; display:flex; border-bottom:1px solid #f0f2f5;">' +
                '<span style="color:#888; min-width:22px;">' + (i + 1) + '.</span>' +
                '<span style="flex:1;">' + _escHtml(pn) + '</span>' +
                (desc ? '<span style="color:#888; font-size:10px; text-align:right;">' + _escHtml(desc) + '</span>' : '') +
            '</div>';
        }
        return html;
    }

    /**
     * 渲染路径列表 HTML（含产品占位区）。点击路径后异步加载该路径下的产品。
     * @param {Array} paths - 树路径数组
     * @param {string} [containerClass=''] - 可选的外层容器 class
     * @returns {string} HTML
     */
    function renderPathListHTML(paths, containerClass) {
        containerClass = containerClass || '';
        if (!paths || !paths.length) return '';
        var html = '<div class="pg-path-list ' + containerClass + '">';
        html += '<div style="font-size:11px; font-weight:600; color:#555; margin-bottom:4px;">🗂️ 路径（' + paths.length + '）</div>';
        for (var i = 0; i < paths.length; i++) {
            html += '<div class="pg-path-item" data-path="' + _escHtml(paths[i]) + '" style="padding:4px 8px; margin-bottom:2px; border-radius:4px; cursor:pointer; font-size:11px; font-family:monospace; transition:background 0.15s;">' +
                _escHtml(paths[i]) + '</div>';
            html += '<div class="pg-path-products" data-path="' + _escHtml(paths[i]) + '" style="display:none; padding-left:16px; margin-bottom:4px;"></div>';
        }
        html += '</div>';
        return html;
    }

    /**
     * 异步加载路径下的产品，渲染到指定容器。
     * 期望容器通过 $(container).closest('.pg-path-item').next('.pg-path-products') 定位。
     * @param {string} path - 树路径
     * @param {jQuery|Element} $trigger - 点击的路径元素
     */
    function loadProductsForPath(path, $trigger) {
        var $productsSlot = $($trigger).closest('.pg-path-item').next('.pg-path-products');
        if (!$productsSlot.length) {
            // fallback: 按 data-path 查找
            $productsSlot = $('.pg-path-products[data-path="' + _escHtml(path) + '"]').first();
        }
        if (!$productsSlot.length) return;

        // toggle：如果已展开则折叠
        if ($productsSlot.is(':visible') && $productsSlot.html()) {
            $productsSlot.slideUp(150);
            return;
        }

        $productsSlot.html('<div style="font-size:11px; color:#888;">加载中...</div>').slideDown(150);

        $.get('/get_products', { path: path })
            .done(function(data) {
                if (data && data.length) {
                    var html = '<ol style="margin:0; padding-left:14px; font-size:11px;">';
                    data.forEach(function(p) {
                        html += '<li style="margin-bottom:2px;">' + _escHtml(p.title || p.name || '') +
                            (p.desc ? ' <span style="color:#888;font-size:10px;">' + _escHtml(p.desc) + '</span>' : '') +
                            '</li>';
                    });
                    html += '</ol>';
                    $productsSlot.html(html);
                } else {
                    $productsSlot.html('<span style="color:#888;font-size:11px;">无产品</span>');
                }
            })
            .fail(function() {
                $productsSlot.html('<span style="color:#d00;font-size:11px;">加载失败</span>');
            });
    }

    /**
     * 渲染可展开的产品组列表（统一 UI：管理/导入/抽屉）。
     *
     * items: [{name, paths:[], meta...}, ...]
     * $container: jQuery 容器
     * opts:
     *   mode: 'manage' | 'import' | 'readonly'
     *   selected: {name: true}  -- 选中状态
     *   expanded: {name: true}  -- 展开状态
     *   editing: {name: true}   -- 正在编辑（名称变 input）
     *   showAddButton: true     -- 顶部显示 + 号方块
     *   newItemPlaceholder: {name} | null  -- 底部编辑中的空新方块（最多一个，由 onAdd 设置）
     *   dragHandle: '.cls'      -- SortableJS handle（null = 不可拖拽）
     *   onAdd()                 -- + 号点击回调
     *   onToggle(name)          -- 单击行进入/退出选中态（调用方负责互斥）
     *   onEditName(name)        -- 双击名字进入输入框编辑
     *   onSave(name, newName, isPlaceholder)  -- 保存图标回调（调用方负责保存/提交/更新路径）
     *   onExpand(name)          -- 展开回调
     *   onCollapse(name)        -- 折叠回调
     */
    function renderExpandableGroupList(items, $container, opts) {
        opts = opts || {};
        var mode = opts.mode || 'readonly';
        var selected = opts.selected || {};
        var expanded = opts.expanded || {};
        var editing = opts.editing || {};         // 输入框模式（名字变input）
        var showAddButton = !!opts.showAddButton;
        var newItemPlaceholder = opts.newItemPlaceholder || null;  // {name: 'xxx'} | null
        var dragHandle = opts.dragHandle || null;

        // 构建完整渲染列表：占位项在最前（替代加号行），已有项倒序
        var renderItems = [];
        if (newItemPlaceholder) {
            renderItems.push({ name: newItemPlaceholder.name, paths: [], _placeholder: true });
        }
        // items 倒序：最新在前
        for (var i = items.length - 1; i >= 0; i--) {
            renderItems.push(items[i]);
        }

        var html = '';

        // ── + 号方块（仅在无 placeholder 时显示） ──
        if (showAddButton && !newItemPlaceholder) {
            html += '<div class="pg-exp-add-block" style="margin-bottom:8px;border:2px dashed #d0d5dd;border-radius:6px;background:#fafbfc;padding:6px 10px;display:flex;align-items:center;justify-content:center;min-height:34px;box-sizing:border-box;">';
            html += '<button class="pg-exp-add-act" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #aaa;background:transparent;color:#888;font-size:14px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;padding:0;box-sizing:border-box;" title="新增">+</button>';
            html += '</div>';
        }

        if (!renderItems.length) {
            html += '<div style="color:#888;text-align:center;padding:12px;">暂无数据</div>';
            $container.html(html);
        } else {
            html += '<div class="pg-expandable-list" style="font-size:13px;">';
            renderItems.forEach(function(item, idx) {
            var name = item.name || '';
            var title = item._displayName || name;
            var editValue = item._editValue != null ? item._editValue : title;
            var paths = item.paths || [];
            var isPlaceholder = !!item._placeholder;
            var isSel = (!isPlaceholder && !!selected[name]);
            var isExp = !isPlaceholder && !!expanded[name];
            var isEditing = isPlaceholder || !!editing[name];
            var isFromGroup = !!item._fromGroup;
            var isPlaceholderSelected = isPlaceholder;  // placeholder 自动进入选中+编辑态
            var showSave = (isSel || isPlaceholderSelected) && mode !== 'import' && !isFromGroup;
            var showDelete = isPlaceholder
                ? isPlaceholderSelected
                : (mode === 'manage' || mode === 'readonly');
            var pathCount = paths.length;

            // 占位方块：虚线框 + 浅背景
            var itemStyle = 'border-radius:6px;margin-bottom:6px;overflow:hidden;';
            if (isPlaceholder) {
                itemStyle += 'border:2px dashed #c0c7d0;background:#fdfdfd;';
            } else if (isSel) {
                itemStyle += 'background:#d0e4ff;border:2px solid #4a90d9;';
            } else {
                itemStyle += 'background:#f6f8fa;border:1px solid #e1e4e8;';
            }

            html += '<div class="pg-exp-item" data-name="' + _escHtml(name) + '" data-idx="' + idx + '" data-placeholder="' + (isPlaceholder ? '1' : '0') + '" style="' + itemStyle + '">';

            // ── 主行：拖拽手柄 + 名称/输入框 + 路径数 + 操作图标 ──
            html += '<div class="pg-exp-header" style="display:flex;align-items:center;gap:6px;padding:6px 10px;min-height:34px;">';
            // 占位项留空对齐
            if (isPlaceholder) {
                html += '<span style="width:16px;flex-shrink:0;"></span>';
            }
            // 占位项没有拖拽手柄
            if (dragHandle && !isPlaceholder) {
                html += '<i class="fas fa-grip-vertical ' + dragHandle.replace('.','') + '" style="color:#888;cursor:grab;flex-shrink:0;"></i>';
            }
            // 名称 or 编辑框
            if (isEditing) {
                html += '<input class="pg-exp-name-input" data-name="' + _escHtml(name) + '" type="text" value="' + _escHtml(editValue) + '" style="flex:1;min-width:0;font-size:13px;height:28px;padding:0 6px;border:1px solid #4a90d9;border-radius:4px;box-sizing:border-box;line-height:28px;margin:0;">';
            } else {
                html += '<span class="pg-exp-name" data-name="' + _escHtml(name) + '" title="' + _escHtml(title) + '" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:' + (isSel ? '600' : '400') + ';cursor:text;">' + _escHtml(title) + '</span>';
                if (isFromGroup) {
                    html += '<span style="background:#6c63ff;color:#fff;font-size:10px;padding:1px 5px;border-radius:3px;flex-shrink:0;font-weight:600;line-height:1.4;">产品组</span>';
                }
                if (isSel && mode !== 'import' && !isFromGroup) {
                    html += '<span style="background:#e7f1ff;color:#145da0;border:1px solid #9cc7f2;font-size:10px;padding:1px 5px;border-radius:3px;flex-shrink:0;font-weight:600;line-height:1.4;">编辑中</span>';
                }
            }
            html += '<span style="color:#888;font-size:11px;flex-shrink:0;">(' + pathCount + '条)</span>';

            // 操作图标组（选中态显示保存/展开/删除；非选中态只显示展开）
            html += '<span class="pg-exp-actions" style="display:flex;align-items:center;gap:4px;flex-shrink:0;">';
            if (!isPlaceholder) {
                html += '<i class="fas fa-' + (isExp ? 'chevron-up' : 'chevron-down') + ' pg-exp-toggle-icon" data-name="' + _escHtml(name) + '" title="' + (isExp ? '折叠' : '展开') + '" style="color:#666;cursor:pointer;font-size:14px;"></i>';
            }
            if (showSave) {
                html += '<i class="fas fa-save pg-exp-save-icon" data-name="' + _escHtml(name) + '" title="保存" style="color:#4a90d9;cursor:pointer;font-size:14px;"></i>';
            }
            if (showDelete) {
                html += '<i class="fas fa-trash pg-exp-del-icon" data-name="' + _escHtml(name) + '" title="删除" style="color:#d00;cursor:pointer;font-size:13px;"></i>';
            }
            html += '</span>';
            html += '</div>';

            // ── 展开区域：路径 + 产品 ──
            html += '<div class="pg-exp-body" data-name="' + _escHtml(name) + '" style="' + (isExp ? '' : 'display:none;') + 'padding:0 10px 8px 10px;background:#fafbfc;border-top:1px solid #e1e4e8;">';
            if (isExp) {
                html += '<div class="pg-exp-paths" style="padding-top:6px;">';
                paths.forEach(function(path, pi) {
                    html += '<div class="pg-exp-path-item" data-name="' + _escHtml(name) + '" data-path="' + _escHtml(path) + '" data-pi="' + pi + '" data-fromgroup="' + (item._fromGroup ? '1' : '0') + '" style="border:1px solid #e1e4e8;border-radius:4px;margin-bottom:4px;overflow:hidden;">';
                    html += '<div class="pg-exp-path-hdr" style="display:flex;align-items:center;justify-content:space-between;padding:4px 8px;background:#f0f2f5;cursor:pointer;font-size:12px;font-family:monospace;word-break:break-word;">';
                    html += '<span style="flex:1;min-width:0;">' + _escHtml(path) + '</span>';
                    if (mode !== 'readonly' && mode !== 'import' && (isSel || isPlaceholderSelected) && !isFromGroup) {
                        html += '<button class="pg-exp-path-del" data-name="' + _escHtml(name) + '" data-path="' + _escHtml(path) + '" data-pi="' + pi + '" title="删除路径" style="background:none;border:none;color:#d00;cursor:pointer;font-size:12px;padding:1px 4px;margin-left:6px;flex-shrink:0;line-height:1;"><i class="fas fa-times"></i></button>';
                    }
                    html += '</div>';
                    html += '<div class="pg-exp-path-prods" data-path="' + _escHtml(path) + '" style="display:none;padding:4px 8px 4px 16px;font-size:12px;color:#888;"></div>';
                    html += '</div>';
                });
                html += '</div>';
            }
            html += '</div>';

            html += '</div>'; // .pg-exp-item
        });
        html += '</div>';

        $container.html(html);
        }
        // 注意：空列表分支在上面已调用 $container.html(html)

        // ── + 号点击 ──
        if (showAddButton) {
            $container.off('click.pgexp', '.pg-exp-add-act').on('click.pgexp', '.pg-exp-add-act', function(e) {
                e.stopPropagation();
                if (opts.onAdd) opts.onAdd();
            });
        }

        // ── 事件绑定 ──

        // 单击行 → 进入/退出选中态（toggle）
        // 导入：单击=多选（toggle选中状态）
        $container.off('click.pgexp', '.pg-exp-header').on('click.pgexp', '.pg-exp-header', function(e) {
            if ($(e.target).closest('.pg-exp-actions').length) return;
            if ($(e.target).closest('input').length) return;
            var $item = $(this).closest('.pg-exp-item');
            var name = $item.data('name');

            if (mode === 'import') {
                if (opts.onToggle) opts.onToggle(name);
                return;
            }

            if (opts.onToggle) opts.onToggle(name);
        });

        // 双击名字文字 → 进入输入框编辑
        $container.off('dblclick.pgexp', '.pg-exp-name').on('dblclick.pgexp', '.pg-exp-name', function(e) {
            e.stopPropagation();
            var name = $(this).data('name');
            if (opts.onEditName) opts.onEditName(name);
        });

        // 展开/折叠（选中态图标）
        $container.off('click.pgexp', '.pg-exp-toggle-icon').on('click.pgexp', '.pg-exp-toggle-icon', function(e) {
            e.stopPropagation();
            var $icon = $(this);
            var name = $icon.data('name');
            var $body = $icon.closest('.pg-exp-item').find('.pg-exp-body');
            if (!expanded[name]) {
                expanded[name] = true;
                $icon.removeClass('fa-chevron-down').addClass('fa-chevron-up');
                // 如果 body 还没有路径内容，动态填充
                if (!$body.find('.pg-exp-paths').length) {
                    var item = null;
                    for (var i = 0; i < items.length; i++) {
                        if (items[i].name === name) { item = items[i]; break; }
                    }
                    if (item && item.paths && item.paths.length) {
                        var ph = '<div class="pg-exp-paths" style="padding-top:6px;">';
                        item.paths.forEach(function(path, pi) {
                            ph += '<div class="pg-exp-path-item" data-name="' + _escHtml(name) + '" data-path="' + _escHtml(path) + '" data-pi="' + pi + '" data-fromgroup="' + (item._fromGroup ? '1' : '0') + '" style="border:1px solid #e1e4e8;border-radius:4px;margin-bottom:4px;overflow:hidden;">';
                            ph += '<div class="pg-exp-path-hdr" style="display:flex;align-items:center;justify-content:space-between;padding:4px 8px;background:#f0f2f5;cursor:pointer;font-size:12px;font-family:monospace;word-break:break-word;">';
                            ph += '<span style="flex:1;min-width:0;">' + _escHtml(path) + '</span>';
                            if (mode !== 'readonly' && mode !== 'import' && !!selected[name] && !item._fromGroup) {
                                ph += '<button class="pg-exp-path-del" data-name="' + _escHtml(name) + '" data-path="' + _escHtml(path) + '" data-pi="' + pi + '" title="删除路径" style="background:none;border:none;color:#d00;cursor:pointer;font-size:12px;padding:1px 4px;margin-left:6px;flex-shrink:0;line-height:1;"><i class="fas fa-times"></i></button>';
                            }
                            ph += '</div>';
                            ph += '<div class="pg-exp-path-prods" data-path="' + _escHtml(path) + '" style="display:none;padding:4px 8px 4px 16px;font-size:12px;color:#888;"></div>';
                            ph += '</div>';
                        });
                        ph += '</div>';
                        $body.prepend(ph);
                    }
                }
                $body.slideDown(150);
                if (opts.onExpand) opts.onExpand(name);
            } else {
                delete expanded[name];
                $icon.removeClass('fa-chevron-up').addClass('fa-chevron-down');
                $body.slideUp(150);
                if (opts.onCollapse) opts.onCollapse(name);
            }
        });

        // 删除（选中态图标）
        $container.off('click.pgexp', '.pg-exp-del-icon').on('click.pgexp', '.pg-exp-del-icon', function(e) {
            e.stopPropagation();
            var name = $(this).data('name');
            if (opts.onDelete) opts.onDelete(name);
        });

        // 删除路径
        $container.off('click.pgexp', '.pg-exp-path-del').on('click.pgexp', '.pg-exp-path-del', function(e) {
            e.stopPropagation();
            var $btn = $(this);
            var name = $btn.data('name');
            var path = $btn.data('path');
            if (opts.onDeletePath) opts.onDeletePath(name, path);
        });

        // 路径展开（异步加载产品）
        $container.off('click.pgexp', '.pg-exp-path-hdr').on('click.pgexp', '.pg-exp-path-hdr', function(e) {
            // 不触发删除按钮
            if ($(e.target).closest('.pg-exp-path-del').length) return;
            e.stopPropagation();
            var $hdr = $(this);
            var path = $hdr.closest('.pg-exp-path-item').data('path');
            var $prods = $hdr.siblings('.pg-exp-path-prods');
            if ($prods.is(':visible')) {
                $prods.slideUp(150);
                return;
            }
            $prods.html('加载中...').slideDown(150);
            $.get('/get_products', { path: path })
                .done(function(data) {
                    if (data && data.length) {
                        var h = '<div style="font-size:12px;">';
                        data.forEach(function(prod) {
                            h += '<div style="padding:2px 0;">' + _escHtml(prod.title || prod.name || '') + (prod.desc ? ' <span style="color:#888;font-size:10px;">' + _escHtml(prod.desc) + '</span>' : '') + '</div>';
                        });
                        h += '</div>';
                        $prods.html(h);
                    } else {
                        $prods.html('<span style="color:#888;">无产品</span>');
                    }
                })
                .fail(function() {
                    $prods.html('<span style="color:#d00;">加载失败</span>');
                });
        });

        // 保存图标
        $container.off('click.pgexp', '.pg-exp-save-icon').on('click.pgexp', '.pg-exp-save-icon', function(e) {
            e.stopPropagation();
            var name = $(this).data('name');
            var $inp = $container.find('.pg-exp-name-input[data-name="' + _escHtml(name) + '"]');
            var newName = $inp.length ? $inp.val().trim() : name;
            if (!newName) return;
            var isPlaceholder = String($(this).closest('.pg-exp-item').data('placeholder')) === '1';
            if (opts.onSave) opts.onSave(name, newName, isPlaceholder);
        });

        // 名称输入框：Enter/blur → 保存名字，退出输入框（保持选中态）
        $container.off('keydown.pgexp blur.pgexp', '.pg-exp-name-input')
            .on('keydown.pgexp', '.pg-exp-name-input', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    var $inp = $(this);
                    var name = $inp.data('name');
                    var newName = $inp.val().trim();
                    if (!newName) return;
                    var isPlaceholder = String($inp.closest('.pg-exp-item').data('placeholder')) === '1';
                    if (opts.onSave) opts.onSave(name, newName, isPlaceholder);
                }
            })
            .on('blur.pgexp', '.pg-exp-name-input', function() {
                var $inp = $(this);
                var name = $inp.data('name');
                var newName = $inp.val().trim();
                if (!newName) return;
                var isPlaceholder = String($inp.closest('.pg-exp-item').data('placeholder')) === '1';
                if (opts.onSave) opts.onSave(name, newName, isPlaceholder);
            });

        // SortableJS 拖拽
        if (dragHandle && window.Sortable) {
            var el = $container.find('.pg-expandable-list')[0];
            if (el) {
                if (el._sortable) el._sortable.destroy();
                window.Sortable.create(el, {
                    animation: 150,
                    handle: dragHandle,
                    onEnd: function() {
                        var names = [];
                        $(el).find('.pg-exp-item').each(function() {
                            names.push($(this).data('name'));
                        });
                        if (opts.onReorder) opts.onReorder(names);
                    }
                });
            }
        }
    }

    /**
     * 渲染产品组完整详情：路径列表 + 点击路径加载产品。
     * 整个内容替换到 $container 中，并绑定路径点击事件。
     * @param {object} group - {paths: [...], ...}
     * @param {jQuery} $container - 渲染目标容器
     * @param {string} [title] - 可选标题
     */
    function renderGroupDetail(group, $container, title) {
        var paths = group && group.paths ? group.paths : [];
        var html = '';
        if (title) {
            html += '<div style="font-size:13px; font-weight:600; color:#333; margin-bottom:6px;">' + _escHtml(title) + '</div>';
        }
        if (paths.length) {
            html += renderPathListHTML(paths);
        } else {
            html += '<div style="color:#888;font-size:12px;">该组没有路径</div>';
        }
        $container.html(html);

        // 绑定路径点击事件
        $container.off('click.pgpath', '.pg-path-item').on('click.pgpath', '.pg-path-item', function() {
            var path = $(this).data('path');
            loadProductsForPath(path, $(this));
        });
    }

    // ── Export ───────────────────────────────────────────────────────────────
    window.ProductGroupShared = {
        fetchGroups: fetchGroups,
        fetchGroupDetail: fetchGroupDetail,
        createGroup: createGroup,
        updateGroup: updateGroup,
        deleteGroup: deleteGroup,
        reorderGroups: reorderGroups,
        renameGroup: renameGroup,
        renderGroupListHTML: renderGroupListHTML,
        renderProductDetailHTML: renderProductDetailHTML,
        renderPathListHTML: renderPathListHTML,
        loadProductsForPath: loadProductsForPath,
        renderGroupDetail: renderGroupDetail,
        renderExpandableGroupList: renderExpandableGroupList
    };

})(jQuery, window);
