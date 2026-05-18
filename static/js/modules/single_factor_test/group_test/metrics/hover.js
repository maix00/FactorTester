/**
 * Hover popup for metrics table (works with sectioned table).
 *
 * Implementation notes:
 * - Uses event delegation so it works after table re-render.
 * - Popup is pointer-events:none to avoid hover flicker.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) return;
    GT.metrics = GT.metrics || {};

    function ensurePopup() {
        var popup = document.getElementById('metric-hover-popup');
        if (popup) return popup;
        popup = document.createElement('div');
        popup.id = 'metric-hover-popup';
        popup.style.cssText = [
            'display:none',
            'position:fixed',
            'z-index:9999',
            'background:#fff',
            'border:1px solid #d0d5dd',
            'border-radius:10px',
            'box-shadow:0 8px 30px rgba(0,0,0,0.18)',
            'padding:18px 20px',
            'max-width:420px',
            'min-width:280px',
            'pointer-events:none'
        ].join(';');
        document.body.appendChild(popup);
        return popup;
    }

    function getMeta(metricName) {
        var meta = (GT.metrics && GT.metrics.meta) || {};
        return {
            cn: (meta.cn || {})[metricName] || metricName,
            desc: (meta.desc || {})[metricName] || '',
            math: (meta.math || {})[metricName] || '',
        };
    }

    function positionPopup(popup, anchorRect) {
        var left = anchorRect.right + 12;
        var top = anchorRect.top - 10;
        var maxW = 420;
        if (left + maxW > window.innerWidth) left = anchorRect.left - (maxW + 12);

        var popupHeight = popup.offsetHeight || 200;
        if (top + popupHeight > window.innerHeight) top = window.innerHeight - popupHeight - 10;
        if (top < 10) top = 10;

        popup.style.left = left + 'px';
        popup.style.top = top + 'px';
    }

    var _activeCell = null;
    var _hideTimer = null;

    function showForCell(cell) {
        var metricName = cell.getAttribute('data-metric');
        if (!metricName) return;

        var popup = ensurePopup();
        var meta = getMeta(metricName);

        var html = '<div style="font-size:15px;font-weight:700;color:#0f4c81;margin-bottom:10px;padding-bottom:8px;border-bottom:2px solid #e5e7eb;">'
            + meta.cn + '</div>';
        if (meta.math) {
            html += '<div style="font-size:18px;text-align:center;margin:10px 0;padding:8px;background:#f8fafc;border-radius:6px;">'
                + meta.math + '</div>';
        }
        if (meta.desc) {
            html += '<div style="font-size:13px;color:#555;line-height:1.7;margin-top:8px;">' + meta.desc + '</div>';
        }

        popup.innerHTML = html;
        popup.style.display = 'block';
        positionPopup(popup, cell.getBoundingClientRect());

        if (window.MathJax && window.MathJax.typesetPromise) {
            window.MathJax.typesetPromise([popup]).catch(function(err) {
                try { console.warn('MathJax render error:', err); } catch (_) {}
            });
        }
    }

    function hidePopupSoon() {
        var popup = document.getElementById('metric-hover-popup');
        if (!popup) return;
        if (_hideTimer) clearTimeout(_hideTimer);
        _hideTimer = setTimeout(function() {
            popup.style.display = 'none';
            _activeCell = null;
        }, 80);
    }

    function bindOnce() {
        if (GT.metrics.hover && GT.metrics.hover._bound) return;

        document.addEventListener('mouseover', function(e) {
            var cell = e.target && e.target.closest ? e.target.closest('.metric-name-cell') : null;
            if (!cell) return;
            if (_hideTimer) { clearTimeout(_hideTimer); _hideTimer = null; }
            if (_activeCell === cell) return;
            _activeCell = cell;
            showForCell(cell);
        });

        document.addEventListener('mouseout', function(e) {
            if (!_activeCell) return;
            var to = e.relatedTarget;
            if (to && _activeCell.contains && _activeCell.contains(to)) return;
            hidePopupSoon();
        });

        GT.metrics.hover = GT.metrics.hover || {};
        GT.metrics.hover._bound = true;
    }

    bindOnce();
})();

