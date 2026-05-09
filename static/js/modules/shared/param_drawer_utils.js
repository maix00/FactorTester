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
    var math = mathBlockEl.querySelector('mjx-container');
    if (!math) return;
    math.style.transform = '';
    math.style.transformOrigin = 'center top';
    math.style.display = 'inline-block';
    mathBlockEl.style.overflow = 'hidden';
    var available = Math.max(80, mathBlockEl.clientWidth - 8);
    var width = math.scrollWidth || math.getBoundingClientRect().width;
    var height = math.scrollHeight || math.getBoundingClientRect().height;
    var scale = width > available ? available / width : 1;
    math.style.transform = 'scale(' + scale + ')';
    mathBlockEl.style.minHeight = scale < 1 ? (height * scale + 8) + 'px' : '';
};
