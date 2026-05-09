/**
 * param_drawer_utils.js
 * 参数抽屉公共工具 — math/desc 渲染
 * shared by custom_factor_editor.html (JS-rendered drawer)
 *             parameter_module.html  (server-rendered drawer, optional typeset call)
 */

/**
 * 在参数抽屉中渲染数学公式 + 因子说明。
 *
 * @param {string}      mathExpr      LaTeX 表达式（不含 $$ 包装）
 * @param {string}      description   因子说明（Markdown 文本）
 * @param {HTMLElement} mathBlockEl   显示公式的容器元素
 * @param {HTMLElement} descBlockEl   说明折叠区外层容器
 * @param {HTMLElement} descRenderedEl 实际渲染 HTML 的目标元素
 */
window.renderDrawerMathAndDesc = function(mathExpr, description, mathBlockEl, descBlockEl, descRenderedEl) {
    // ── 数学公式 ──
    if (mathBlockEl) {
        var expr = (mathExpr || '').trim();
        if (expr) {
            mathBlockEl.textContent = '$$ ' + expr + ' $$';
            mathBlockEl.style.display = '';
        } else {
            mathBlockEl.style.display = 'none';
        }
    }

    // ── 因子说明 ──
    if (descBlockEl) {
        var desc = (description || '').trim();
        if (desc) {
            if (descRenderedEl) {
                try {
                    descRenderedEl.innerHTML = (typeof marked !== 'undefined')
                        ? marked.parse(desc)
                        : desc;
                } catch (e) {
                    descRenderedEl.textContent = desc;
                }
            }
            descBlockEl.style.display = '';
        } else {
            descBlockEl.style.display = 'none';
        }
    }

    // ── 触发 MathJax typeset ──
    if (mathBlockEl && mathBlockEl.style.display !== 'none') {
        var attempts = 0;
        var typeset = function() {
            attempts += 1;
            if (window.MathJax && window.MathJax.typesetPromise) {
                if (window.MathJax.typesetClear) {
                    MathJax.typesetClear([mathBlockEl]);
                }
                MathJax.typesetPromise([mathBlockEl])
                    .then(function() { fitMathJaxToContainer(mathBlockEl); })
                    .catch(function() {});
            } else if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
                // MathJax 已配置但尚未完成初始化（async 加载期间）
                window.MathJax.startup.promise.then(function() {
                    if (window.MathJax.typesetClear) {
                        MathJax.typesetClear([mathBlockEl]);
                    }
                    MathJax.typesetPromise([mathBlockEl])
                        .then(function() { fitMathJaxToContainer(mathBlockEl); })
                        .catch(function() {});
                });
            } else if (attempts < 20) {
                setTimeout(typeset, 100);
            }
        };
        typeset();
    }
};

window.fitMathJaxToContainer = function(mathBlockEl) {
    if (!mathBlockEl) return;
    if (window.ResizeObserver && !mathBlockEl.__mathResizeObserver) {
        mathBlockEl.__mathResizeObserver = new ResizeObserver(function() {
            if (mathBlockEl.__mathFitRaf) return;
            mathBlockEl.__mathFitRaf = requestAnimationFrame(function() {
                mathBlockEl.__mathFitRaf = 0;
                window.fitMathJaxToContainer(mathBlockEl);
            });
        });
        mathBlockEl.__mathResizeObserver.observe(mathBlockEl);
    }
    var math = mathBlockEl.querySelector('mjx-container');
    if (!math) return;

    var style = window.getComputedStyle(mathBlockEl);
    var padX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
    var padY = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
    var availableWidth = Math.max(40, mathBlockEl.clientWidth - padX);

    math.style.transform = '';
    math.style.transformOrigin = 'center center';
    math.style.display = 'inline-block';

    var width = math.scrollWidth || math.getBoundingClientRect().width;
    var height = math.scrollHeight || math.getBoundingClientRect().height;
    if (!width || !height) return;

    // 默认不缩放；仅当公式超出容器宽度时再按比例缩小。
    var targetWidth = availableWidth * 0.94;
    var scale = width > targetWidth ? (targetWidth / width) : 1;
    if (!Number.isFinite(scale) || scale <= 0) scale = 1;
    math.style.transform = 'scale(' + scale + ')';

    // 根据缩放后真实高度设置容器高度，并居中显示。
    var scaledHeight = height * scale;
    var boxHeight = Math.ceil(Math.max(scaledHeight + padY + 14, 56));
    mathBlockEl.style.overflow = 'hidden';
    mathBlockEl.style.display = 'flex';
    mathBlockEl.style.alignItems = 'center';
    mathBlockEl.style.justifyContent = 'center';
    mathBlockEl.style.textAlign = 'center';
    mathBlockEl.style.height = boxHeight + 'px';
    mathBlockEl.style.minHeight = boxHeight + 'px';
};
