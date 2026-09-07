const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
global.window = {FTPageAgentDrawer: {attach() {}}};
vm.runInThisContext(fs.readFileSync('server/manager/web/profile/page-assistance.js', 'utf8'));
(async () => {
  let active = 'a';
  let imports = 0;
  let document = {value: 'old'};
  let lifecycle;
  const session = {durable: {}};
  const stored = new Map();
  const acknowledgments = [];
  const context = {
    tabID: 'b', tabSession: session, isRouteCurrent: () => active === 'b',
    assistanceWorkspace: () => ({active_tab_id: active, tabs: [
      {tab_id: 'a', title: 'A', research_id: '', session: {durable: {}}},
      {tab_id: 'b', title: 'B', research_id: 'research-one', session},
    ]}),
    persistAssistanceTab: id => stored.set(id, structuredClone(session.durable)),
    pageState: {register: (_, value) => { lifecycle = value; }},
    api: async (path, options) => {
      if (options) acknowledgments.push(JSON.parse(options.body));
      return {page: {tab_id: 'b'}};
    },
  };
  const adapter = () => ({
    navigation: () => ({schema_version: 1, root_id: 'page', nodes: {page: {id: 'page', kind: 'page'}}}),
    schema: () => ({type: 'object'}), exportDocument: () => document,
    validate: value => { if (!value.value) throw new Error('invalid'); },
    importDocument: value => { imports++; document = value; },
  });
  window.FTPageAssistance.register(context, adapter(), {pageKind: 'test'});
  const workspace = await window.FTPageAssistance.workspace(context);
  assert.equal(workspace.tabs[1].assistance.document.value, 'old');
  const application = {tab_id: 'b', sequence: 4, expected_revision: 0,
    expires_at: Date.now() / 1000 + 300, document: {value: 'new'}};
  assert.deepEqual(await window.FTPageAssistance.stage(context, 'self', application), {deferred: true});
  assert.equal(imports, 0, 'background DOM must not be rewritten');
  assert.equal(stored.get('b').pendingAssistance.item.document.value, 'new');
  lifecycle.dispose(); // Cold eviction must not lose a queued document.
  session.durable = structuredClone(stored.get('b'));
  active = 'b';
  window.FTPageAssistance.register(context, adapter(), {pageKind: 'test'});
  await window.FTPageAssistance.resume(context);
  assert.equal(document.value, 'new');
  assert.equal(imports, 1);
  assert.equal(acknowledgments[0].success, true);
  assert.equal(session.durable.pendingAssistance, undefined);
  active = 'a';
  await assert.rejects(window.FTPageAssistance.stage(context, 'self', {...application, sequence: 5}), /版本冲突/);
  await assert.rejects(window.FTPageAssistance.stage(context, 'self', {...application, tab_id: 'closed'}), /已关闭/);
  console.log('PASS: workspace drafts survive background/cold restore and preserve target revisions');
})().catch(error => { console.error(error); process.exitCode = 1; });
