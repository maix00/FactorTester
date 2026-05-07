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
                MathJax.typesetPromise([mathBlockEl]).catch(function() {});
            } else if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
                // MathJax 已配置但尚未完成初始化（async 加载期间）
                window.MathJax.startup.promise.then(function() {
                    MathJax.typesetPromise([mathBlockEl]).catch(function() {});
                });
            } else if (attempts < 20) {
                setTimeout(typeset, 100);
            }
        };
        typeset();
    }
};
