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
        renderGroupDetail: renderGroupDetail
    };

})(jQuery, window);
