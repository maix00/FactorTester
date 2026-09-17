// A report's Job result special section must render the Job's own 运行过程
// (progress) and 运行结果 (the per-Job-kind result viewer) by reusing the Job
// detail implementation — not a second renderer, and not only the mounted
// artifacts.  Everything below is stubbed: no network, no real Job.
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
  get firstElementChild() { return this.children.find(child => child instanceof Element); }
  get textContent() {
    return this.text + this.children.map(child => child.textContent).join('');
  }
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

const created = [];
global.document = {
  createElement: tagName => { const node = new Element(tagName); created.push(node); return node; },
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

// --- stubs of the shared Job implementations ------------------------------
const calls = {groups: [], loadDetail: [], group: [], loadGroup: [], domain: [], generic: [], progress: [], declarations: [], stopProgress: 0};
let detailFails = false;
let viewerGroup = 'job-detail-factor-series';

global.FTRichText = {
  inline: text => new TextNode(text),
  blocks: text => new TextNode(text),
  appendLink: (fragment, label) => fragment.append(new TextNode(label)),
};
global.FTIcons = {
  node: (symbol, className) => {
    const icon = new Element('i');
    icon.className = className || '';
    icon.dataset.symbol = String(symbol);
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
  loadGroups: async names => { calls.groups.push([...names]); },
};
global.FTJobs = {
  loadDetail: async (context, port, jobID, serverID) => {
    calls.loadDetail.push({port, jobID, serverID});
    if (detailFails) throw new Error('任务不存在');
    return {
      payload: {result_summary: {}},
      taskDetail: {
        artifacts: [
          {name: 'factor_series_data', state: 'active', role: 'output'},
          {name: 'ig_grid', state: 'active', role: 'input'},
        ],
        input_artifacts: [{name: 'ig_grid'}],
        output_declarations: ['factor_series'],
        results: {summary: {}},
      },
      job: {kind: 'factor_evaluation', status: 'succeeded'},
      executionQuery: '?port=8001',
      artifactQuery: '',
    };
  },
};
global.FTJobArtifacts = {
  effectiveDeclarations: (declarations, outputArtifacts) => {
    calls.declarations.push({declarations: [...declarations], names: outputArtifacts.map(item => item.name)});
    return declarations;
  },
};
global.FTJobProgress = {
  stopProgress: () => { calls.stopProgress += 1; },
  progressView: (context, status) => {
    calls.progress.push(status);
    const root = new Element('section');
    root.className = 'job-progress job-section';
    const heading = new Element('h2');
    heading.textContent = '任务进度';
    root.append(heading);
    return {root, progressState: {terminal: true}};
  },
  // A finished Job must not open a live stream from the report.
  watchProgress: () => { throw new Error('terminal jobs must not be watched'); },
};
global.FTJobResultViewers = {
  group: (job, artifacts, results) => {
    calls.group.push({kind: job.kind, names: artifacts.map(item => item.name)});
    return viewerGroup;
  },
  loadGroup: async () => { calls.loadGroup.push(viewerGroup); },
  domainSections: (context, options) => {
    calls.domain.push(options);
    const root = new Element('section');
    root.className = 'job-section factor-series-results';
    root.append(new TextNode('因子序列结果'));
    return root;
  },
  genericSection: (context, options) => {
    calls.generic.push(options);
    const root = new Element('section');
    root.className = 'job-section generic-job-results';
    root.append(new TextNode('结果'));
    return root;
  },
};

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
  for (let tick = 0; tick < 40; tick += 1) await Promise.resolve();
};

const JOB_ID = 'a1b2c3d4e5f60718293a4b5c6d7e8f90';
const jobResultID = `job-${JOB_ID}-result`;

(function checkDetection() {
  const detect = window.FTReportJobResult.isJobResultSection;
  assert.equal(detect({
    component_id: jobResultID, kind: 'special', display_kind: 'test_result',
  }), true, 'a job-<32 hex>-result special section is recognized');
  assert.equal(window.FTReportJobResult.jobResultID({
    component_id: jobResultID, kind: 'special', display_kind: 'test_result',
  }), JOB_ID, 'the job id is read between the job- prefix and -result suffix');
  assert.equal(detect({
    component_id: 'job-abc-result', kind: 'special', display_kind: 'test_result',
  }), false, 'a truncated job id is not a Job result section');
  assert.equal(detect({
    component_id: jobResultID, kind: 'special', display_kind: 'evidence_fragment',
  }), false, 'another special section kind is untouched');
  assert.equal(detect({
    component_id: jobResultID, kind: 'entry', display_kind: 'test_result',
  }), false, 'a non-special component is untouched');
  console.log('PASS: Job result section detection');
})();

(async () => {
  const context = {
    t: key => key,
    lazyRendering: false,
    renderGeneration: 0,
    referenceMeta: {
      [`job:${JOB_ID}`]: {
        kind: 'job', target_ref: `job:${JOB_ID}`,
        data: {port: 8001, server_id: 'srv-1'},
      },
    },
    disclosureState: {[jobResultID]: true},
  };
  const jobSection = {
    component_id: jobResultID, kind: 'special', display_kind: 'test_result',
    parent_id: 'chapter-1', title: '测试结果 · job',
    body: '测试任务已结束，状态为 succeeded',
    content: null,
  };

  // 1. The report subsection renders the reused run surface in place of the
  //    artifact-only body.
  const view = window.FTReportComponents.componentView(jobSection, [], context);
  await settle();

  assert(calls.groups.length >= 1, 'the Job detail module group is loaded on demand');
  assert.deepEqual(calls.groups[0], ['job-detail-core'],
    'the report reuses the Job detail implementation through its published lazy group');
  assert.deepEqual(calls.loadDetail, [{port: 8001, jobID: JOB_ID, serverID: 'srv-1'}],
    'the Job is read through the existing detail loader with the report binding port/server');
  assert.deepEqual(calls.progress, ['succeeded'], 'the existing progress view is rendered');
  assert(view.textContent.includes('任务进度'),
    `the rendered DOM shows 运行过程 (任务进度): ${view.textContent}`);
  assert(view.textContent.includes('因子序列结果'),
    `the rendered DOM shows the per-kind result view: ${view.textContent}`);
  assert.deepEqual(calls.loadGroup, ['job-detail-factor-series'],
    'the per-kind result viewer group is loaded before rendering');
  assert.equal(calls.domain.length, 1, 'the domain result sections render the result');
  const domain = calls.domain[0];
  assert.equal(domain.job.kind, 'factor_evaluation');
  assert.equal(domain.jobID, JOB_ID);
  assert.equal(domain.executionQuery, '?port=8001');
  assert.deepEqual(domain.activeArtifacts.map(item => item.name), ['factor_series_data'],
    'input artifacts are excluded exactly like the Job detail page does');
  assert.equal(domain.customAnalyses, null, 'a report owns no custom analyses');
  assert.equal(typeof domain.onGenerated, 'function');
  assert.equal(calls.generic.length, 0, 'the generic artifact preview is not used for a domain Job');
  const block = findByClass(view, 'report-job-result');
  assert(block, 'the report subsection mounts a job result block');
  assert.equal(block.dataset.reportJobID, JOB_ID);
  assert.equal(block.dataset.reportJobResult, 'ready');
  assert(view.textContent.includes('测试任务已结束，状态为 succeeded'),
    'the section prose is still rendered next to the reused run surface');
  console.log('PASS: Job result subsection renders 运行过程与结果 from the Job detail implementation');

  // 2. A Job without a domain viewer still renders the shared generic result
  //    surface (result tabs + declarations) instead of nothing.
  const genericComponent = {
    ...jobSection, component_id: `job-${'b'.repeat(32)}-result`,
  };
  viewerGroup = '';
  calls.domain.length = 0;
  const genericView = window.FTReportComponents.componentView(
    genericComponent, [], {...context, disclosureState: {[genericComponent.component_id]: true}},
  );
  await settle();
  assert.equal(calls.generic.length, 1, 'an unknown Job kind falls back to the shared generic section');
  assert.equal(calls.domain.length, 0);
  assert.deepEqual(calls.generic[0].declarations, ['factor_series']);
  assert.deepEqual(calls.declarations[0].names, ['factor_series_data'],
    'generic declarations are computed from the Job output artifacts');
  assert(genericView.textContent.includes('结果'));
  viewerGroup = 'job-detail-factor-series';
  console.log('PASS: unknown Job kinds still use the shared generic result section');

  // 3. Sections that are not a Job result stay on the ordinary report path.
  const plain = window.FTReportComponents.componentView({
    component_id: 'fragment-1', kind: 'special', display_kind: 'evidence_fragment',
    parent_id: 'chapter-1', title: '证据片段', body: '证据正文', content: null,
  }, [], {...context, disclosureState: {'fragment-1': true}});
  await settle();
  assert.equal(findByClass(plain, 'report-job-result'), null,
    'a non-result special section mounts no Job run surface');
  assert(plain.textContent.includes('证据正文'));
  console.log('PASS: other special sections are untouched');

  // 4. An unavailable Job states the failure instead of rendering empty.
  calls.loadDetail.length = 0;
  detailFails = true;
  const failing = {
    ...jobSection, component_id: `job-${'c'.repeat(32)}-result`,
  };
  const failingView = window.FTReportComponents.componentView(
    failing, [], {...context, disclosureState: {[failing.component_id]: true}},
  );
  await settle();
  detailFails = false;
  const failingBlock = findByClass(failingView, 'report-job-result');
  assert.equal(failingBlock.dataset.reportJobResult, 'error');
  assert(failingView.textContent.includes('结果查看器不可用'),
    `a failed load is stated explicitly: ${failingView.textContent}`);
  assert(failingView.textContent.includes('任务不存在'), 'the underlying error is shown');
  console.log('PASS: a failed Job read reports 结果查看器不可用 explicitly');

  console.log('test_report_job_result_section: ok');
})().catch(error => { console.error(error); process.exitCode = 1; });
