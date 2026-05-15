(function(global) {
    'use strict';

    function clamp(value, minValue, maxValue) {
        return Math.min(Math.max(value, minValue), maxValue);
    }

    function resolveElement(maybeElement, selector) {
        if (maybeElement) return maybeElement;
        if (!selector) return null;
        return document.querySelector(selector);
    }

    function parseMaxWidthPx(computedMaxWidth, fallbackPx) {
        if (!computedMaxWidth || computedMaxWidth === 'none') return fallbackPx;
        var parsed = parseFloat(computedMaxWidth);
        return Number.isFinite(parsed) ? parsed : fallbackPx;
    }

    function createResizableTreeContainer(options) {
        var opts = options || {};
        var outer = resolveElement(opts.outerElement, opts.outerSelector);
        var inner = resolveElement(opts.innerElement, opts.innerSelector);
        if (!outer || !inner) return null;

        var minWidth = Number.isFinite(opts.minWidth) ? opts.minWidth : 260;
        var initialWidth = Number.isFinite(opts.initialWidth) ? opts.initialWidth : 340;
        var minHeight = Number.isFinite(opts.minHeight) ? opts.minHeight : 120;
        var initialHeight = Number.isFinite(opts.initialHeight) ? opts.initialHeight : null;
        var maxWidthFallback = Number.isFinite(opts.maxWidthFallback) ? opts.maxWidthFallback : Math.floor(window.innerWidth * 0.62);
        var desktopMediaQuery = opts.desktopMediaQuery || '(max-width: 1024px)';
        var mobileInnerHeight = opts.mobileInnerMaxHeight || '38vh';
        var resizeDirection = opts.resizeDirection || 'both'; // 'horizontal', 'vertical', 'both'
        var followOuterHeight = !!opts.followOuterHeight;

        outer.style.width = 'fit-content';
        outer.style.minWidth = '0';
        outer.style.flex = '0 0 auto';
        if (opts.outerMaxWidth) outer.style.maxWidth = opts.outerMaxWidth;

        inner.style.boxSizing = 'border-box';
        inner.style.minWidth = String(minWidth) + 'px';
        inner.style.minHeight = String(minHeight) + 'px';
        if (opts.maxWidth) inner.style.maxWidth = opts.maxWidth;
        if (!inner.style.width || inner.style.width === '100%') {
            inner.style.width = String(initialWidth) + 'px';
        }
        if (initialHeight && (!inner.style.height || inner.style.height === 'auto')) {
            inner.style.height = String(initialHeight) + 'px';
        }
        inner.style.resize = resizeDirection;
        inner.style.overflowX = 'auto';
        inner.style.overflowY = 'auto';

        var resizeObserver = null;
        var outerResizeObserver = null;

        function syncHeightFromOuter() {
            if (!followOuterHeight) return;
            var outerRect = outer.getBoundingClientRect();
            if (!outerRect.height || outerRect.height <= 1) return;
            var outerStyle = window.getComputedStyle(outer);
            var available =
                outerRect.height -
                (parseFloat(outerStyle.paddingTop) || 0) -
                (parseFloat(outerStyle.paddingBottom) || 0) -
                (parseFloat(outerStyle.borderTopWidth) || 0) -
                (parseFloat(outerStyle.borderBottomWidth) || 0);
            var parent = inner.parentElement;
            if (parent) {
                Array.prototype.forEach.call(parent.children, function(child) {
                    if (child === inner) return;
                    var childStyle = window.getComputedStyle(child);
                    available -= child.getBoundingClientRect().height;
                    available -= (parseFloat(childStyle.marginTop) || 0) + (parseFloat(childStyle.marginBottom) || 0);
                });
            }
            if (available > minHeight) {
                inner.style.height = Math.round(available) + 'px';
            }
        }

        function sync() {
            var isMobile = window.matchMedia(desktopMediaQuery).matches;
            if (isMobile) {
                outer.style.width = '100%';
                outer.style.flexBasis = 'auto';
                inner.style.width = '100%';
                inner.style.minWidth = '0';
                inner.style.minHeight = '0';
                inner.style.resize = 'none';
                if (mobileInnerHeight) {
                    inner.style.maxHeight = mobileInnerHeight;
                }
                return;
            }

            inner.style.minWidth = String(minWidth) + 'px';
            inner.style.minHeight = String(minHeight) + 'px';
            inner.style.resize = resizeDirection;
            inner.style.maxHeight = '';

            var innerStyle = window.getComputedStyle(inner);
            var maxWidthPx = parseMaxWidthPx(innerStyle.maxWidth, maxWidthFallback);
            var measured = inner.getBoundingClientRect().width;
            if (measured <= 1) {
                measured = parseFloat(inner.style.width) || initialWidth;
            }
            var targetInnerWidth = clamp(measured, minWidth, maxWidthPx);
            inner.style.width = Math.round(targetInnerWidth) + 'px';

            var outerStyle = window.getComputedStyle(outer);
            var chromeWidth =
                (parseFloat(outerStyle.paddingLeft) || 0) +
                (parseFloat(outerStyle.paddingRight) || 0) +
                (parseFloat(outerStyle.borderLeftWidth) || 0) +
                (parseFloat(outerStyle.borderRightWidth) || 0);
            var targetOuterWidth = Math.ceil(targetInnerWidth + chromeWidth);
            outer.style.width = String(targetOuterWidth) + 'px';
            outer.style.flexBasis = String(targetOuterWidth) + 'px';
            syncHeightFromOuter();
        }

        function onWindowResize() {
            maxWidthFallback = Math.floor(window.innerWidth * 0.62);
            sync();
        }

        sync();

        if (global.ResizeObserver) {
            resizeObserver = new global.ResizeObserver(function() {
                sync();
            });
            resizeObserver.observe(inner);
            if (followOuterHeight) {
                outerResizeObserver = new global.ResizeObserver(function() {
                    syncHeightFromOuter();
                });
                outerResizeObserver.observe(outer);
            }
        }

        global.addEventListener('resize', onWindowResize);

        return {
            sync: sync,
            destroy: function() {
                global.removeEventListener('resize', onWindowResize);
                if (resizeObserver) {
                    resizeObserver.disconnect();
                    resizeObserver = null;
                }
                if (outerResizeObserver) {
                    outerResizeObserver.disconnect();
                    outerResizeObserver = null;
                }
            }
        };
    }

    global.setupResizableTreeContainer = createResizableTreeContainer;
})(window);
