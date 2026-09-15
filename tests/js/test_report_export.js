// The report download icon offers .md/.pdf, and every channel the reader
// already addresses (server tree, client copy, publication) exports through
// the manager.  Embedded in the Swift client the request goes to the native
// export instead, which owns the PDF renderer and the local tree.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.hidden = false;
    this._text = '';
    const classes = new Set();
    this.classList = {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      contains: name => classes.has(name),
    };
  }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; }
  remove() {}
  setAttribute(k, v) { this.attributes[k] = v; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(k, f) { this.listeners[k] = f; }
  removeEventListener(k, f) { if (this.listeners[k] === f) delete this.listeners[k]; }
  get textContent() {
    return this._text + this.children.map(c => c.textContent).join('');
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  click() { this.listeners.click?.({ stopPropagation() {} }); }
}

const documentShim = {
  body: new Element('body'),
  createElement: tag => new Element(tag),
  addEventListener() {},
  removeEventListener() {},
};

const downloads = [];
const fetched = [];
const notices = [];
let bridgePayloads = [];
let bridge = null;

global.window = global;
global.Node = Element;
global.document = documentShim;
global.FTIcons = { node: () => new Element('svg') };
global.setTimeout = (fn) => { fn(); return 0; };
global.URL = {
  createObjectURL: blob => { downloads.push(blob); return 'blob:report'; },
  revokeObjectURL() {},
};
global.Blob = class Blob { constructor(parts) { this.parts = parts; } };
global.fetch = async (url) => {
  fetched.push(url);
  return {
    ok: true,
    blob: async () => new global.Blob(['markdown']),
    json: async () => ({}),
  };
};
Object.defineProperty(global, 'webkit', {
  get: () => bridge,
  configurable: true,
});

vm.runInThisContext(
  fs.readFileSync('server/manager/web/core/shared-ui.js', 'utf8'),
);
vm.runInThisContext(
  fs.readFileSync('server/manager/web/report/export-action.js', 'utf8'),
);

const context = {
  t: value => value,
  showNotice: (message, error) => notices.push([message, Boolean(error)]),
  button: (symbol, action, label) => {
    const element = new Element('button');
    element.listeners.click = action;
    element.setAttribute('aria-label', label);
    return element;
  },
};

const find = (root, predicate) => [
  root,
  ...root.children.flatMap(child => find(child, predicate)),
].filter(predicate);
const choiceNamed = (root, label) =>
  find(root, e => e.tag === 'button' && e.attributes['aria-label'] === label)[0]
  || find(root, e => e.tag === 'button' && e.textContent === label)[0];

(async () => {
  // 1) The download icon reveals both formats.
  const menu = window.FTReportExport.menu(context, {publication_id: 'publication-one'});
  assert.equal(menu.className, 'report-export-menu');
  const trigger = find(menu, e => e.tag === 'button')[0];
  assert.equal(trigger.attributes['aria-label'], '导出报告');
  const choices = find(menu, e => e.className === 'report-export-choices')[0];
  assert.equal(choices.hidden, true);
  assert.deepEqual(
    choices.children.map(item => item.textContent),
    ['导出 Markdown', '导出 PDF'],
  );
  trigger.click();
  assert.equal(choices.hidden, false);

  // 2) A published report (a bare publication id) exports from the manager.
  await window.FTReportExport.run(context, {
    publication_id: 'nEP71a7rs-HdhCkl1QTS60r3', title: '固收基金久期研究',
  }, 'md');
  assert.deepEqual(fetched, [
    '/api/public-research/nEP71a7rs-HdhCkl1QTS60r3/export?format=md',
  ]);
  assert.equal(downloads.length, 1);
  assert.equal(notices.length, 0);

  // 3) A server tree carries its owner so a reader is authorized.
  fetched.length = 0;
  await window.FTReportExport.run(context, {
    publication_id: 'server:profile-one:report-one:main',
    owner_ref: 'GTHT@owner@1',
    title: '研究/报告:一',
  }, 'md');
  assert.deepEqual(fetched, [
    '/api/server-research/profile-one%3Areport-one%3Amain'
    + '/export?format=md&target_ref=GTHT%40owner%401',
  ]);

  // 4) The client's own copy goes to the client channel, no target_ref needed.
  fetched.length = 0;
  await window.FTReportExport.run(context, {
    publication_id: 'local:report-1:main', owner_ref: 'GTHT@owner@1',
  }, 'md');
  assert.deepEqual(fetched, [
    '/api/client/research/report-1%3Amain/export?format=md',
  ]);

  // 5) A publication whose key looks like a tree reference stays a publication.
  fetched.length = 0;
  await window.FTReportExport.run(context, {
    publication_id: 'report:v1:OW3AVzDRiOZFk11OXY8I56HG',
    source_kind: 'publication',
  }, 'md');
  assert.deepEqual(fetched, [
    '/api/public-research/report%3Av1%3AOW3AVzDRiOZFk11OXY8I56HG/export?format=md',
  ]);

  // 6) Embedded in Swift: hand the request to the native export instead.
  fetched.length = 0;
  bridge = {
    messageHandlers: {
      researchReportExport: {
        postMessage: payload => bridgePayloads.push(payload),
      },
    },
  };
  await window.FTReportExport.run(context, {
    publication_id: 'server:profile-one:report-one:main',
    profile_ref: 'profile-one',
    work_package_id: 'report-one',
    branch_id: 'main',
    owner_ref: 'GTHT@owner@1',
    title: '研究/报告:一',
  }, 'md');
  assert.deepEqual(bridgePayloads, [{
    publication_id: 'server:profile-one:report-one:main',
    profile_ref: 'profile-one',
    work_package_id: 'report-one',
    branch_id: 'main',
    owner_ref: 'GTHT@owner@1',
    format: 'markdown',
    title: '研究/报告:一',
  }]);
  assert.deepEqual(fetched, []);

  // 7) The menu routes its choices through the same run().
  const embedded = window.FTReportExport.menu(context, {
    publication_id: 'server:profile-one:report-one:main',
    profile_ref: 'profile-one',
  });
  choiceNamed(embedded, '导出 PDF').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(bridgePayloads.length, 2);
  assert.equal(bridgePayloads[1].format, 'pdf');

  // 8) Without a usable address the reader is told, not silently ignored.
  bridge = null;
  await window.FTReportExport.run(context, { title: '孤儿' }, 'md');
  assert.equal(notices.length, 1);
  assert.equal(notices[0][1], true);

  console.log('REPORT EXPORT: md/pdf, three channels, bridge PASSED');
})();

