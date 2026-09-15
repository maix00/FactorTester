// Platform LaTeX keeps Chinese labels in math mode; KaTeX then declares the
// input incompatible and (throwOnError:false) prints the raw source.  The
// shared sanitiser wraps CJK runs in \text{...} so the same input renders.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// --- minimal DOM so core/shared-ui.js can load -----------------------------
global.window = global;
global.document = {
  createElement: () => ({
    append() {}, replaceChildren() {}, setAttribute() {}, addEventListener() {},
    querySelector: () => null, querySelectorAll: () => [], classList: {add() {}, remove() {}},
    dataset: {}, style: {},
  }),
  createElementNS: () => ({classList: {add() {}}, setAttribute() {}}),
  querySelector: () => null,
  querySelectorAll: () => [],
};
vm.runInThisContext(
  fs.readFileSync('server/manager/web/core/shared-ui.js', 'utf8'),
  {filename: 'shared-ui.js'},
);
const {latexSafe} = window.FTUI;

// --- vendored KaTeX -------------------------------------------------------
const KATEX = 'apple/Resources/ThirdParty/KaTeX/katex.min.js';
const sandbox = {module: {exports: {}}, exports: {}, self: {}, window: {}, console};
sandbox.global = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(KATEX, 'utf8'), sandbox, {filename: KATEX});
const katex = sandbox.module.exports || sandbox.katex || sandbox.window.katex;
assert.ok(katex && typeof katex.renderToString === 'function', 'vendored katex loads');

function renderedText(source) {
  const html = katex.renderToString(source, {displayMode: true, throwOnError: false});
  // KaTeX embeds the input in <annotation>; that is not a rendering failure.
  return html
    .replace(/<annotation[\s\S]*?<\/annotation>/g, '')
    .replace(/<[^>]*>/g, '');
}

// A run already wrapped in \text{...} is not wrapped twice.
assert.equal(latexSafe('\\textcolor{red}{持续期}'), '\\textcolor{red}{\\text{持续期}}');
assert.equal(latexSafe('\\text{已有中文}'), '\\text{已有中文}');
assert.equal(latexSafe('\\textcolor{red}{P}_{t}'), '\\textcolor{red}{P}_{t}');

// Every real family template must render as a formula, not as raw source.
const families = JSON.parse(fs.readFileSync('/tmp/ft_families.json', 'utf8'));
const items = families.families || families.items || [];
let checked = 0;
let brokenBefore = 0;
for (const item of items) {
  const template = String(item.math_expr || '');
  if (!template.trim()) continue;
  checked += 1;
  if (/textcolor|operatorname/.test(renderedText(template))) brokenBefore += 1;
  const text = renderedText(latexSafe(template));
  assert.ok(
    !/\\?(textcolor|operatorname|frac|left)/.test(text),
    `raw LaTeX leaked for ${item.factor_family_alias}: ${text.slice(0, 60)}`,
  );
}
assert.ok(checked >= 80, `expected the real family set, saw ${checked}`);
assert.ok(brokenBefore > 0, 'the unfixed input is expected to fall back');

console.log(`MATH LATEX SAFE: ${checked} family templates render (${brokenBefore} fell back before) PASSED`);
