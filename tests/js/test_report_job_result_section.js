// A report's Job result special section must show the **same** 运行过程与结果 panel
// the test configuration page shows after a run.  The page composes that panel in
// workbench/test-run-results.js (FTTestRunResults.render → FTTestRunProgress +
// the per-kind result view), so the report must call exactly that and own no
// progress/result rendering of its own.  Everything below is stubbed: no network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

global.window = global;

class TextNode {
  constructor(text) { this.text = String(text); }
  get textContent() { return this.text; }
  set textContent(value) { this.text = String(value); }
}

class ClassList {
  constructor() { this.tokens = new Set(); }
  add(...names) { names.forEach(name => { if (name) this.tokens.add(name); }); }
  remove(...names) { names.forEach(name => this.tokens.delete(name)); }
  contains(name) { return this.tokens.has(name); }
  toggle(name, force) {
    const next = force === undefined ? !this.tokens.has(name) : Boolean(force);
    if (next) this.tokens.add(name); else this.tokens.delete(name);
    return next;
  }
}

class Element {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentElement = null;
    this.dataset = {};
    this.attributes = {};
    this.style = {removeProperty() {}};
    this.classList = new ClassList();
    this.listeners = {};
    this.text = '';
    this.isConnected = true;
  }
  get className() { return [...this.classList.tokens].join(' '); }
  set className(value) {
    this.classList.tokens = new Set(String(value).split(/\s+/).filter(Boolean));
  }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.text = String(value); this.children = []; }
  append(...items) {
    items.filter(Boolean).forEach(item => {
      if (item instanceof Element) item.parentElement = this;
      this.children.push(item);
    });
  }
  replaceChildren(...items) { this.children = []; this.text = ''; this.append(...items); }
  insertBefore(item, reference) {
    const index = reference ? this.children.indexOf(reference) : -1;
    if (item instanceof Element) item.parentElement = this;
    if (index < 0) this.children.push(item);
    else this.children.splice(index, 0, item);
  }
  replaceWith(item) {
    const parent = this.parentElement;
    if (!parent) return;
    parent.insertBefore(item, this);
    parent.children = parent.children.filter(child => child !== this);
    this.parentElement = null;
    this.isConnected = false;
  }
  remove() { if (this.parentElement) this.replaceWith(new TextNode('')); this.isConnected = false; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  removeEventListener(name) { delete this.listeners[name]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  getBoundingClientRect() { return {top: 0, left: 0, right: 0, bottom: 0, height: 0}; }
  scrollIntoView() {}
}

global.document = {
  createElement: tagName => new Element(tagName),
  createDocumentFragment: () => new Element('#fragment'),
};

function findByClass(root, name) {
  if (!(root instanceof Element)) return null;
  if (root.classList.contains(name)) return root;
  for (const child of root.children) {
    const found = findByClass(child, name);
    if (found) return found;
  }
  return null;
}

// --- stubs of the shared implementations the test page uses ----------------
const calls = {groups: []};
let panelFails = false;

global.FTRichText = {
  inline: text => new TextNode(text),
  blocks: text => new TextNode(text),
  appendLink: (fragment, label) => fragment.append(new TextNode(label)),
};
global.FTIcons = {
  node: (symbol, className) => {
    const icon = new Element('i');
    icon.className = className || '';
    return icon;
  },
  section: (kind, displayKind) => displayKind || kind,
};
global.FTUI = {
  loading: text => new TextNode(`[loading] ${text}`),
  empty: (title, detail) => new TextNode(`[empty] ${title}${detail ? `: ${detail}` : ''}`),
};
global.FTReportLazyRuntime = {observe: () => null, reset() {}};
global.FTStaticLoader = {
  loadGroups: async names => {
    calls.groups.push([...names]);
    if (panelFails) throw new Error('测试运行面板不可用');
    // The panel module only exists after its lazy group loads, exactly as in the
    // browser: the report must not assume it is already present.
    global.FTTestRunResults = panelStub();
  },
};
// The report must ask for the test page's own lazy group.
global.FTTestTypeRegistry = {
  normalize: value => (String(value || '').includes('backtest') ? 'backtest' : ''),
};

// The test page's run panel: 任务进度 + the tabs and table of the backtest 概览.
function panelStub() {
  return {
  render: (context, state, item, rerender) => {
    if (panelFails) throw new Error('测试运行面板不可用');
    const root = new Element('div');
    root.className = 'test-run-inline-results';
    const progress = new Element('section');
    progress.className = 'job-progress';
    progress.append(new TextNode('任务进度'));
    const status = new Element('div');
    status.append(new TextNode('成功'));
    progress.append(status);
    const tabs = new Element('div');
    ['运行摘要', '概览', '策略统计'].forEach(label => {
      const tab = new Element('button');
      tab.append(new TextNode(label));
      tabs.append(tab);
    });
    const table = new Element('table');
    ['策略', '初始权益', '期末权益', '总收益率', '年化收益率', 'Sharpe ratio', '历史最大回撤']
      .forEach(label => {
        const cell = new Element('th');
        cell.append(new TextNode(label));
        table.append(cell);
      });
    root.append(progress, tabs, table);
    root.dataset.panelState = `${state.kind}|${state.jobID}|${state.port}|${state.serverID}`;
    root.dataset.itemPhase = String(item.phase);
    assert.equal(typeof rerender, 'function', 'the panel receives a rerender callback');
    return root;
  },
  };
}

// --- load the report renderer path under test -----------------------------
for (const file of ['lazy-runtime', 'job-result-section', 'component-view']) {
  vm.runInThisContext(
    fs.readFileSync(`server/manager/web/report/${file}.js`, 'utf8'),
    {filename: `${file}.js`},
  );
}

const settle = async () => {
  for (let tick = 0; tick < 40; tick += 1) await Promise.resolve();
  await new Promise(resolve => setTimeout(resolve, 0));
};

const JOB_ID = 'a1b2c3d4e5f60718293a4b5c6d7e8f90';
const jobResultID = `job-${JOB_ID}-result`;
const context = {
  t: key => key,
  lazyRendering: false,
  renderGeneration: 0,
  referenceMeta: {
    [`job:${JOB_ID}`]: {
      kind: 'job', target_ref: `job:${JOB_ID}`,
      data: {port: 8001, server_id: 'srv-1', kind: 'backtest'},
    },
  },
  disclosureState: {[jobResultID]: true},
};
const jobSection = {
  component_id: jobResultID, kind: 'special', display_kind: 'test_result',
  parent_id: 'chapter-1', title: '回测 运行结果', body: '测试任务已结束', content: null,
};

(async () => {
  // 0. Only a job-<32 hex>-result special section is a Job result section.
  const detect = window.FTReportJobResult.isJobResultSection;
  assert.equal(detect(jobSection), true);
  assert.equal(window.FTReportJobResult.jobResultID(jobSection), JOB_ID);
  assert.equal(detect({...jobSection, component_id: 'job-abc-result'}), false);
  assert.equal(detect({...jobSection, display_kind: 'evidence_fragment'}), false);
  assert.equal(detect({...jobSection, kind: 'entry'}), false);
  console.log('PASS: Job result section detection');

  // 1. The panel is the test page's own composition, with the Job identity the
  //    report binding carries.
  const view = window.FTReportComponents.componentView(jobSection, [], context);
  await settle();
  assert.deepEqual(calls.groups[0], ['workbench-run-results'],
    'the report loads the test page run panel group on demand');
  const block = findByClass(view, 'report-job-result');
  assert(block, 'the report subsection mounts the Job run panel block');
  assert.equal(block.dataset.reportJobResult, 'ready');
  const panel = findByClass(view, 'test-run-inline-results');
  assert(panel, 'the panel is the test page composition, not a report-only one');
  for (const label of ['任务进度', '成功', '运行摘要', '概览', '策略统计',
                       '初始权益', '期末权益', '总收益率', '年化收益率',
                       'Sharpe ratio', '历史最大回撤']) {
    assert(view.textContent.includes(label),
      `the embedded panel shows the test page label ${label}: ${view.textContent}`);
  }
  assert.equal(panel.dataset.panelState, `backtest|${JOB_ID}|8001|srv-1`,
    'the panel is driven by the report binding job kind/port/server');
  console.log('PASS: the report panel is the test configuration page panel');

  // 2. A section that is not a Job result stays on the ordinary report path.
  const plain = window.FTReportComponents.componentView({
    component_id: 'fragment-1', kind: 'special', display_kind: 'evidence_fragment',
    parent_id: 'chapter-1', title: '证据片段', body: '证据正文', content: null,
  }, [], {...context, disclosureState: {'fragment-1': true}});
  await settle();
  assert.equal(findByClass(plain, 'report-job-result'), null,
    'a non-result special section mounts no Job run panel');
  assert(plain.textContent.includes('证据正文'));
  console.log('PASS: other special sections are untouched');

  // 3. An unavailable panel states so explicitly instead of rendering empty.
  panelFails = true;
  calls.groups.length = 0;
  const failing = {...jobSection, component_id: `job-${'c'.repeat(32)}-result`};
  const failingView = window.FTReportComponents.componentView(
    failing, [], {...context, disclosureState: {[failing.component_id]: true}},
  );
  await settle();
  panelFails = false;
  const failingBlock = findByClass(failingView, 'report-job-result');
  assert.equal(failingBlock.dataset.reportJobResult, 'error');
  assert(failingView.textContent.includes('结果查看器不可用'),
    `a failed panel load is stated explicitly: ${failingView.textContent}`);
  console.log('PASS: an unavailable run panel is reported explicitly');

  console.log('test_report_job_result_section: ok');
})().catch(error => { console.error(error); process.exitCode = 1; });
