// Browser plugin not available. Run with the existing Playwright runtime.
// Isolated real components + production styles; no account data or server writes.
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch(engine === chromium ? {channel: 'chrome'} : {});
    for (const width of [1200, 390]) {
      const page = await browser.newPage({viewport: {width, height: 800}});
      const errors = []; page.on('pageerror', error => errors.push(error.message));
      await page.setContent('<title>Source editor QA</title><main style="padding:16px"></main>');
      for (const file of ['app.css', 'workbench.css', 'strategy-library.css']) {
        await page.addStyleTag({path: path.resolve('server/manager/web/styles', file)});
      }
      await page.addStyleTag({path: path.resolve('static/vendor/highlight/github.min.css')});
      await page.addScriptTag({path: path.resolve('static/vendor/highlight/highlight.min.js')});
      await page.addScriptTag({path: path.resolve('server/manager/web/core/shared-ui.js')});
      await page.addScriptTag({path: path.resolve('server/manager/web/core/icons.js')});
      for (const parent of ['factor-detail-source-editor', 'backtest-group-form', 'object-overlay-card', 'strategy-editor-factor-source-editor']) {
        for (const zoom of [1, 1.25]) {
          await page.evaluate(({parent, zoom}) => {
            const main = document.querySelector('main'); main.className = parent;
            main.style.zoom = zoom;
            const value = Array.from({length: 90}, (_, i) => `row_${i} = "中文 参数 $F ${'long '.repeat(25)}"`).join('\n')+'\n';
            window.editor = FTUI.codeEditor(value, {language: 'python', ariaLabel: 'Python 源码'});
            window.uploads = 0; window.checks = 0;
            const context = {t: s => s};
            main.replaceChildren(FTUI.sourcePanel(context, editor.element, {actions: [
              FTUI.iconButton(context, 'arrow.up.circle', '上传源码', () => uploads++),
              FTUI.iconButton(context, 'checkmark.circle', '校验源码', () => checks++),
            ]}));
            editor.textarea.style.height = '380px';
          }, {parent, zoom});
          const metrics = await page.evaluate(() => {
            const nodes = ['textarea', 'pre', 'code'].map(s => editor.element.querySelector(s));
            return nodes.map(n => {const c = getComputedStyle(n); return [c.fontFamily, c.fontSize, c.lineHeight, c.letterSpacing]});
          });
          assert.deepEqual(metrics[0], metrics[1]); assert.deepEqual(metrics[0], metrics[2]);
          await page.evaluate(() => {editor.textarea.scrollTop = 700; editor.textarea.scrollLeft = 60; editor.textarea.dispatchEvent(new Event('scroll'));});
          const target = await page.evaluate(() => {
            const node = editor.element.querySelector('code'); const text = node.textContent;
            const offset = text.split('\n').slice(0, 40).join('\n').length + 1;
            const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT); let n, pos = 0;
            while ((n = walker.nextNode())) {if (pos+n.length > offset) break; pos += n.length;}
            const range = document.createRange(); range.setStart(n, offset-pos); range.setEnd(n, offset-pos+1);
            const r = range.getBoundingClientRect(), box = editor.textarea.getBoundingClientRect();
            return {x:box.left+40, y:r.top+r.height/2};
          });
          await page.mouse.click(target.x, target.y);
          const clickedLine = await page.evaluate(() => editor.value().slice(0, editor.textarea.selectionStart).split('\n').length - 1);
          assert.equal(clickedLine, 40, `${engine.name()} ${parent} ${width}/${zoom} clicked wrong line`);
          await page.keyboard.down('Shift'); await page.keyboard.press('ArrowDown'); await page.keyboard.up('Shift');
          assert(await page.evaluate(() => editor.textarea.selectionEnd > editor.textarea.selectionStart));
          assert(await page.evaluate(() => Math.abs(editor.element.querySelector('pre').scrollTop-editor.textarea.scrollTop)<1));
          await page.getByRole('button', {name:'上传源码'}).click(); await page.getByRole('button', {name:'校验源码'}).click();
          assert.deepEqual(await page.evaluate(() => [uploads,checks]), [1,1]);
          const header = await page.locator('.source-panel-heading').boundingBox();
          const button = await page.getByRole('button', {name:'校验源码'}).boundingBox();
          assert(button.y >= header.y && button.y+button.height <= header.y+header.height+1);
          await page.evaluate(() => editor.setValue('class OA(FactorFamily):\n    # 参数\n    value = "$F"\n\n'));
          assert.equal(await page.locator('pre code').textContent(), 'class OA(FactorFamily):\n    # 参数\n    value = "$F"\n\n\n');
          await page.locator('textarea').fill('new_value = 2\n');
          assert.equal(await page.locator('pre code').textContent(), 'new_value = 2\n\n');
        }
      }
      await page.evaluate(() => editor.setValue('class OA(FactorFamily):\n    """开盘价因子。"""\n\n    @staticmethod\n    def factor_expr():\n        F = FactorFreqParam\n        return OPEN.shift(F)\n\n    description = "Adjusted open"\n'));
      assert(await page.evaluate(() => {
        const viewer = FTUI.sourceView({t:s=>s}, editor.value()); document.querySelector('main').append(viewer);
        const matches = getComputedStyle(viewer.querySelector('code')).font === getComputedStyle(editor.textarea).font;
        viewer.remove(); return matches;
      }));
      await page.screenshot({path:`/tmp/ft391-${engine.name()}-${width}.png`});
      assert.deepEqual(errors, []); console.log('PASS', engine.name(), width, '4 parents; 100/125%; click, selection, scroll, resize, actions, restore');
      await page.close();
    }
    await browser.close();
  }
})().catch(error => {console.error(error); process.exit(1)});
