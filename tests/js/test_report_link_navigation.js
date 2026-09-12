// Focused browser regression: web links, object tabs and local resources.
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium, webkit} = require('playwright');

(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch(engine === chromium ? {channel: 'chrome'} : {});
    try {
      const context = await browser.newContext();
      await context.route('**/*', route => route.fulfill({contentType: 'text/html',
        body: route.request().url().includes('article.test')
          ? '<main>External article body</main>' : '<main id="report"></main>'}));
      const page = await context.newPage();
      await page.goto('https://factortester.test/report');
      await page.evaluate(() => {
        window.FTIcons = {node: () => document.createElement('i'), reference: () => ''};
        window.calls = [];
        window.webkit = {messageHandlers: {researchReference: {
          postMessage: value => calls.push(['bridge', value.href]),
        }}};
      });
      for (const file of ['rich-text', 'report-entry']) {
        await page.addScriptTag({path: path.resolve(`server/manager/web/report/${file}.js`)});
      }
      await page.addScriptTag({path: path.resolve('server/manager/web/app/tab-view-cache.js')});
      await page.evaluate(() => {
        window.cacheState = {activeTabID: 'report', tabSessions: new Map(),
          tabs: [{id: 'report', path: '/report'}]};
        window.cache = FTTabViewCache.create({state: cacheState,
          content: document.querySelector('#report')});
      });
      for (const nativeReference of [false, true]) {
        await page.evaluate(nativeReference => {
          const root = document.querySelector('#report');
          root.replaceChildren();
          const options = {nativeReference, captureScrollPosition: cache.captureScrollPosition,
            openReference: target => calls.push(['object', target]),
            openLocalResource: target => calls.push(['resource', target])};
          FTRichText.appendLink(root, 'Article', 'https://article.test/story', options);
          FTRichText.appendLink(root, 'Factor', 'factortester://factor/example', options);
          FTRichText.appendLink(root, 'Attachment', 'factortester-local://uploads/picture.png', options);
        }, nativeReference);
        // A trackpad/mouse press runs pointerdown before click. The real tab
        // cache must not detach the pressed anchor or empty the report here.
        const link = page.getByRole('link', {name: 'Article', exact: true});
        const box = await link.boundingBox();
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await page.mouse.down();
        assert.equal(await page.locator('#report a').count(), 3,
          'pointerdown must leave the report and pressed link connected');
        const popupPromise = page.waitForEvent('popup');
        await page.mouse.up();
        const popup = await popupPromise;
        await popup.waitForLoadState();
        assert.equal(popup.url(), 'https://article.test/story');
        assert.equal(await popup.locator('main').textContent(), 'External article body');
        assert.equal(page.url(), 'https://factortester.test/report');
        assert.deepEqual(await page.evaluate(() => calls), []);
        await popup.close();
        await page.getByRole('link', {name: 'Factor', exact: true}).click();
        await page.getByRole('link', {name: 'Attachment', exact: true}).click();
        assert.deepEqual(await page.evaluate(() => calls.splice(0)), [
          ['object', 'factortester://factor/example'],
          nativeReference ? ['object', 'factortester://file/uploads%2Fpicture.png']
            : ['resource', 'uploads/picture.png'],
        ]);
      }
      // Direct dispatch must not send HTTP URLs to the object bridge/router.
      assert.deepEqual(await page.evaluate(() => {
        window.open = (...args) => { calls.push(['external', ...args]); };
        FTReportEntry.openReference('https://article.test/direct', {
          state: {}, t: x => x, navigate: () => calls.push(['route']),
          showNotice: () => calls.push(['notice']),
        });
        return calls;
      }), [['external', 'https://article.test/direct', '_blank', 'noopener,noreferrer']]);
      assert.equal(await page.evaluate(() => {
        cache.saveActiveTabSession();
        return document.querySelector('#report').childNodes.length;
      }), 0, 'an actual tab switch must still park the report');
      console.log(`${engine.name()}: external article, internal reference and attachment routing passed`);
    } finally { await browser.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
