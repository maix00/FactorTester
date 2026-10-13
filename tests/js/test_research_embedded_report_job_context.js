// The embedded Research report must pass the same Job panel capabilities as
// the standalone report.  This exercises the real renderForResearch path.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

global.window = global;
global.location = {origin: 'https://example.test'};

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentElement = null;
    this.className = '';
    this.classList = {add() {}};
    this.dataset = {};
    this.isConnected = true;
  }
  append(...items) {
    for (const item of items) {
      item.parentElement = this;
      this.children.push(item);
    }
  }
  prepend(item) { item.parentElement = this; this.children.unshift(item); }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  setAttribute() {}
  addEventListener() {}
  closest() { return null; }
  querySelector() { return null; }
  contains(item) { return this.children.includes(item); }
}
global.document = {createElement: tag => new Element(tag)};

let actualReportContext;
const pageApi = async path => {
  assert.equal(path, '/api/research/research-1/reports');
  return {reports: [{report_id: 'report-1', source_ref: 'publication-1',
    source_kind: 'publication', title: 'Research report'}]};
};
const pageButton = () => new Element('button');
const pageNotice = () => {};
const pageNavigate = () => {};
global.FTUI = {
  loading: () => new Element('p'),
  empty: () => new Element('p'),
  iconButton: () => new Element('button'),
  formatDate: () => 'today',
};
global.FTStaticLoader = {loadGroups: async groups => {
  assert.deepEqual(groups, ['report']);
}};
global.FTResearchReportSettings = {applyReading() {}};
global.FTReportSource = {create: (id, api) => {
  assert.equal(id, 'publication-1');
  assert.equal(api, pageApi);
  return {
    load: async () => ({title: 'Research report'}),
    watch: () => () => {},
    chapterLazy: false,
    componentLazy: false,
    loadComponent: () => {},
  };
}};
global.FTReportRenderer = {render: (report, mount, context) => {
  actualReportContext = context;
  return {update() {}};
}};

vm.runInThisContext(fs.readFileSync(
  'server/manager/web/research/reports.js', 'utf8',
), {filename: 'reports.js'});

(async () => {
  const page = {
    api: pageApi,
    session: {username: 'reader'},
    button: pageButton,
    showNotice: pageNotice,
    navigate: pageNavigate,
    t: value => value,
    tabSession: {},
    isRouteCurrent: () => true,
  };
  await FTResearchReports.renderForResearch(page, new Element('div'), 'research-1');
  assert(actualReportContext, 'the embedded report was rendered');
  for (const field of ['api', 'session', 'button', 'showNotice', 'navigate']) {
    assert.equal(actualReportContext[field], page[field],
      `embedded Job panel receives ${field} from its page`);
  }
  console.log('test_research_embedded_report_job_context: ok');
})().catch(error => { console.error(error); process.exitCode = 1; });
