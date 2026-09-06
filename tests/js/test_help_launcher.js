const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let loads = 0, opens = 0;
global.document = {createElement() { return {
  dataset: {}, isConnected: true, setAttribute() {},
  addEventListener(_name, callback) { this.activate = callback; },
  replaceWith(value) { this.replacement = value; },
}; }};
global.window = {FTStaticLoader: {async loadGroups(groups) {
  loads += 1;
  assert.deepEqual(groups, ['help-popover']);
  window.FTHelp = {registerLoader() {}, create() {return {click() {opens += 1;}, focus() {}};}};
}}};
vm.runInThisContext(fs.readFileSync('server/manager/web/core/help-launcher.js', 'utf8'));
(async () => {
  const one = window.FTHelp.create('first');
  const two = window.FTHelp.create('second');
  assert.equal(loads, 0, 'closed help does not load overlay runtime');
  await one.activate({preventDefault() {}, stopPropagation() {}});
  await two.activate({preventDefault() {}, stopPropagation() {}});
  assert.equal(loads, 1);
  assert.equal(opens, 2);
  console.log('ok');
})().catch(error => {console.error(error);process.exitCode = 1;});
