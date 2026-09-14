"""Restored Web shell sessions must reach the native CLI handoff."""
from pathlib import Path
import subprocess


def test_restore_notifies_native_only_after_confirmed_identity():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(["node", "-e", r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const events = [];
const context = {window: {webkit: {messageHandlers: {
  factorTesterAuthentication: {postMessage: message => events.push(message)}
}}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('server/manager/web/app/auth.js', 'utf8'), context);
const source = fs.readFileSync('server/manager/web/app/coordinator.js', 'utf8');
const restore = source.slice(source.indexOf('  async function restoreSession()'),
                            source.indexOf('  function t(key'));
context.FTAuth = context.window.FTAuth;
context.localStorage = context.sessionStorage = {removeItem() {}};
context.state = {};
context.savedToken = () => 'old-token';
vm.runInContext(restore, context);
(async () => {
  context.api = async () => ({username: 'principal'});
  await context.restoreSession();
  assert.equal(events.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(events[0])), {action: 'session-updated'});
  events.length = 0;
  let requests = 0;
  context.api = async () => { if (++requests === 1) throw Error('expired token'); return {username:'principal'}; };
  await context.restoreSession();
  assert.equal(events.length, 1);
  events.length = 0;
  context.api = async () => { throw Error('anonymous'); };
  await context.restoreSession();
  assert.equal(events.length, 0);
  context.api = async () => ({});
  await context.restoreSession();
  assert.equal(events.length, 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''], cwd=root, check=True, capture_output=True, text=True)
