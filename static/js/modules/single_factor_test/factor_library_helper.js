(function() {
    if (window.SingleFactorLibraryHelper) return;

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function normalizeScope(scope) {
        if (!scope || scope === 'default') return 'default';
        return String(scope);
    }

    function inferScopeFromSubmissionId(submissionId) {
        var submissions = Array.isArray(window.submissions) ? window.submissions : [];
        var submission = submissions.find(function(sub) {
            return String(sub.id) === String(submissionId);
        });
        return normalizeScope(submission && submission.product_group);
    }

    function bindLongPress(anchor, options) {
        options = options || {};
        if (!anchor || anchor.getAttribute('data-library-longpress-bound') === '1') return;
        anchor.setAttribute('data-library-longpress-bound', '1');
        var longPressTimer = null;

        function cancelLongPress() {
            if (longPressTimer) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        }

        anchor.addEventListener('pointerdown', function() {
            cancelLongPress();
            longPressTimer = setTimeout(function() {
                var factorAlias = typeof options.getFactorAlias === 'function'
                    ? options.getFactorAlias(anchor)
                    : (anchor.getAttribute('data-factor-alias') || anchor.textContent.trim());
                if (!factorAlias) return;
                var defaultProductGroup = typeof options.getProductGroup === 'function'
                    ? options.getProductGroup(anchor)
                    : options.productGroup;
                showAddToLibraryPopover(anchor, factorAlias, {
                    productGroup: defaultProductGroup,
                    popoverClass: options.popoverClass,
                });
            }, options.delay || 600);
        });

        anchor.addEventListener('pointermove', function(e) {
            if (longPressTimer && Math.abs(e.movementX || 0) + Math.abs(e.movementY || 0) > 5) {
                cancelLongPress();
            }
        });
        anchor.addEventListener('pointerup', cancelLongPress);
        anchor.addEventListener('pointercancel', cancelLongPress);
        anchor.addEventListener('pointerleave', cancelLongPress);
    }

    async function showAddToLibraryPopover(anchor, factorAlias, options) {
        options = options || {};
        var popoverClass = options.popoverClass || 'factor-add-to-library-popover';
        document.querySelectorAll('.factor-add-to-library-popover,.ic-add-to-library-popover,.group-add-to-library-popover').forEach(function(el) {
            el.remove();
        });

        var popover = document.createElement('div');
        popover.className = popoverClass + ' factor-add-to-library-popover';
        popover.innerHTML = '<div style="padding:12px;text-align:center;color:#aaa;">加载中...</div>';
        document.body.appendChild(popover);

        var rect = anchor.getBoundingClientRect();
        popover.style.cssText = 'position:fixed;z-index:4000;background:#fff;border:1px solid #d0d5dd;border-radius:10px;box-shadow:0 12px 32px rgba(0,0,0,.18);min-width:280px;max-width:360px;overflow:hidden;left:' + Math.min(rect.left, window.innerWidth - 310) + 'px;top:' + (rect.bottom + 6) + 'px;';

        var defaultScope = normalizeScope(options.productGroup);
        var factorFamilyAlias = window.factorFamilyAlias || '';

        try {
            var resp = await fetch('/custom-factors/api/param-config-scopes');
            var data = await resp.json();
            var scopes = data.success ? (data.product_groups || data.scopes || []) : [];
            scopes = scopes.map(normalizeScope);
            if (scopes.indexOf('default') === -1) scopes.unshift('default');
            if (defaultScope && scopes.indexOf(defaultScope) === -1) scopes.push(defaultScope);

            var scopeOptions = scopes.map(function(scope) {
                var label = scope === 'default' ? '默认产品组' : scope;
                var selected = scope === defaultScope ? ' selected' : '';
                return '<option value="' + esc(scope) + '"' + selected + '>' + esc(label) + '</option>';
            }).join('');

            popover.innerHTML = ''
                + '<div style="padding:14px 16px;border-bottom:1px solid #f0f0f0;">'
                + '<strong style="font-size:14px;">📌 添加到因子库</strong>'
                + '<div style="font-size:12px;color:#666;margin-top:4px;">' + esc(factorAlias) + '</div>'
                + '</div>'
                + '<div style="padding:12px 16px;">'
                + '<label style="font-size:12px;color:#333;display:block;margin-bottom:4px;">目标产品组</label>'
                + '<select class="form-select factor-add-to-lib-scope-select" style="width:100%;">' + scopeOptions + '</select>'
                + '</div>'
                + '<div style="padding:0 16px 14px;display:flex;gap:8px;justify-content:flex-end;">'
                + '<button type="button" class="param-btn factor-add-to-lib-cancel">取消</button>'
                + '<button type="button" class="param-btn btn-primary factor-add-to-lib-confirm">确认添加</button>'
                + '</div>'
                + '<div class="factor-add-to-lib-msg" style="padding:0 16px 12px;font-size:12px;display:none;"></div>';
        } catch (e) {
            popover.innerHTML = '<div style="padding:16px;color:#d40000;">加载失败</div>';
        }

        var cancelBtn = popover.querySelector('.factor-add-to-lib-cancel');
        if (cancelBtn) cancelBtn.addEventListener('click', function() { popover.remove(); });
        var confirmBtn = popover.querySelector('.factor-add-to-lib-confirm');
        if (confirmBtn) confirmBtn.addEventListener('click', async function() {
            var scopeSelect = popover.querySelector('.factor-add-to-lib-scope-select');
            var scopeKey = scopeSelect ? scopeSelect.value : 'default';
            var msgEl = popover.querySelector('.factor-add-to-lib-msg');
            try {
                var addResp = await fetch('/custom-factors/api/param-configs/' + encodeURIComponent(factorFamilyAlias) + '/add-factor', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ factor_alias: factorAlias, product_group: scopeKey })
                });
                var addData = await addResp.json();
                if (msgEl) {
                    msgEl.style.display = 'block';
                    if (addData.success) {
                        msgEl.style.color = addData.skipped ? '#b08800' : '#28a745';
                        msgEl.textContent = addData.skipped ? (addData.message || '已存在，跳过') : '✅ 已添加到因子库';
                    } else {
                        msgEl.style.color = '#d40000';
                        msgEl.textContent = '✗ ' + (addData.error || '添加失败');
                    }
                }
                setTimeout(function() { popover.remove(); }, 1500);
            } catch (e) {
                if (msgEl) {
                    msgEl.style.display = 'block';
                    msgEl.style.color = '#d40000';
                    msgEl.textContent = '✗ 网络错误';
                }
            }
        });

        setTimeout(function() {
            document.addEventListener('pointerdown', function closeOnOutside(e) {
                if (!popover.contains(e.target) && e.target !== anchor) {
                    popover.remove();
                    document.removeEventListener('pointerdown', closeOnOutside);
                }
            });
        }, 100);
    }

    window.SingleFactorLibraryHelper = {
        bindLongPress: bindLongPress,
        inferScopeFromSubmissionId: inferScopeFromSubmissionId,
        showAddToLibraryPopover: showAddToLibraryPopover,
    };
})();
