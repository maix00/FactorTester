// The saved locale catalog and account preference are independent startup IO.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

global.window = global;
global.location = {search: ''};
global.document = {
  documentElement: {lang: ''},
  querySelectorAll: () => [],
  querySelector: () => ({textContent: ''}),
};

const events = [];
let finishLocale;
let finishPreferences;
const state = {session: {alias: 'Audit'}, tabs: []};
global.FTI18n = {
  storedPreference: () => 'en',
  choosePreference: (explicit, remote, cached) => explicit || remote || cached || 'system',
  resolvedLocale: preference => preference === 'system' ? 'en' : preference,
  rememberPreference: value => events.push(`saved:${value}`),
  load: preference => {
    events.push(`locale:${preference}`);
    if (preference === 'en' && !finishLocale) {
      return new Promise(resolve => {
        finishLocale = () => {
          document.documentElement.lang = 'en';
          resolve('en');
        };
      });
    }
    return Promise.resolve(FTI18n.resolvedLocale(preference));
  },
};

vm.runInThisContext(fs.readFileSync('server/manager/web/app/shell.js', 'utf8'));

const shell = FTAppShell.create({
  state,
  tabs: {renderOpenedTabs() {}},
  t: value => value,
  api: path => {
    assert.equal(path, '/api/client/preferences');
    events.push('preferences');
    return new Promise(resolve => { finishPreferences = () => resolve({preferences: {language: 'en'}}); });
  },
});

(async () => {
  let completed = false;
  const pending = shell.loadLanguage().then(() => { completed = true; });
  assert.deepEqual(events, ['locale:en', 'preferences']);
  finishLocale();
  await Promise.resolve();
  assert.equal(completed, false, 'shell waits for the authoritative preference');
  finishPreferences();
  await pending;
  assert.equal(completed, true);
  assert.equal(state.languagePreference, 'en');
  assert.equal(document.documentElement.lang, 'en');
  console.log('APP SHELL STARTUP: locale and preference load concurrently PASSED');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
