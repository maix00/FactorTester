/**
 * dom_utils.js — 单因子测试各模块共用的小工具（window.DomUtils）。
 *
 * 把散落在十几个模块里各写一遍的 escapeHTML / requestJSON / renderChipHtml 收敛到
 * 一处，避免重复与行为漂移。各模块可直接用 DomUtils.xxx，或保留同名薄封装委托过来。
 */
(function() {
    if (window.DomUtils) return;

    // HTML 转义（含单引号，属性值安全）。
    function escapeHTML(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // 统一的 JSON 请求：非 2xx 或 {success:false} 抛错，HTML 响应给出友好提示。
    function requestJSON(url, options) {
        options = options || {};
        var headers = Object.assign({ Accept: 'application/json' }, options.headers || {});
        return fetch(url, Object.assign({ credentials: 'same-origin' }, options, { headers: headers }))
            .then(function(response) {
                var contentType = response.headers.get('content-type') || '';
                if (contentType.indexOf('application/json') < 0) {
                    return response.text().then(function(text) {
                        var hint = text && text.trim().charAt(0) === '<'
                            ? '接口返回了 HTML，可能登录已失效'
                            : '接口未返回 JSON';
                        throw new Error(hint + ' (HTTP ' + response.status + ')');
                    });
                }
                return response.json().then(function(payload) {
                    if (!response.ok || (payload && payload.success === false)) {
                        throw new Error((payload && payload.error) || ('HTTP ' + response.status));
                    }
                    return payload;
                });
            });
    }

    // chip 内部 HTML：有 label 渲染「标签+值」，否则只渲染值。可注入 escapeFn。
    function renderChipHtml(label, value, escapeFn) {
        var esc = escapeFn || escapeHTML;
        var v = '<span class="gt-backend-chip-value">' + esc(value) + '</span>';
        if (!label) return v;
        return '<span class="gt-backend-chip-label">' + esc(label) + '</span>' + v;
    }

    window.DomUtils = {
        escapeHTML: escapeHTML,
        requestJSON: requestJSON,
        renderChipHtml: renderChipHtml,
    };
})();
