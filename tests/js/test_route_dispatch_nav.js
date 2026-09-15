// The feature-entry highlight follows the route for every feature-entry page,
// including the public test workbench; standalone pages keep no highlight.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const calls = [];
const handlers = {
  jobs: () => calls.push(['jobs-page']),
  icTest: () => calls.push(['ic-test-page']),
  backtest: () => calls.push(['backtest-page']),
  docs: () => calls.push(['docs-page']),
  factors: () => calls.push(['factors-page']),
};

function pageContext() {
  return {
    activeNav: route => calls.push(['nav', route]),
    setHeading: title => calls.push(['heading', title]),
  };
}

global.window = global;
vm.runInThisContext(
  fs.readFileSync('server/manager/web/app/route-dispatch.js', 'utf8'),
);

const dispatch = window.FTAppRouteDispatch.create({
  content: null,
  t: value => value,
  context: () => pageContext(),
  jobsContext: () => pageContext(),
  requireLogin: () => false,
  handlers,
});

(async () => {
  // The 测试台 entry is highlighted like any other feature-entry page, and the
  // feed stays public: no login is required to render it.
  calls.length = 0;
  await dispatch.render({kind: 'jobs', section: 'types'}, 1);
  assert.deepEqual(calls, [
    ['nav', 'jobs'], ['heading', '测试台'], ['jobs-page'],
  ]);

  // The 测试任务 section is the same feature entry.
  calls.length = 0;
  await dispatch.render({kind: 'jobs', section: 'tasks'}, 2);
  assert.deepEqual(calls[0], ['nav', 'jobs']);

  // Standalone test configuration pages deliberately carry no highlight.
  calls.length = 0;
  await dispatch.render({kind: 'ic-test'}, 3);
  assert.deepEqual(calls[0], ['nav', '']);
  calls.length = 0;
  await dispatch.render({kind: 'backtest'}, 4);
  assert.deepEqual(calls[0], ['nav', '']);

  // The technical documentation page keeps its own choice (no sidebar entry).
  calls.length = 0;
  await dispatch.render({kind: 'docs', slug: 'index'}, 5);
  assert.deepEqual(calls[0], ['nav', '']);

  // A regular feature-entry page is unchanged.
  calls.length = 0;
  await dispatch.render({kind: 'factors'}, 6);
  assert.deepEqual(calls[0], ['nav', 'factors']);

  // A guarded route still yields to the login guard, but it highlights its
  // feature entry first — exactly the ordering the test workbench relies on.
  const guarded = window.FTAppRouteDispatch.create({
    content: null,
    t: value => value,
    context: () => pageContext(),
    jobsContext: () => pageContext(),
    requireLogin: () => true,
    handlers: {...handlers, strategyLibrary: () => calls.push(['strategy-page'])},
  });
  calls.length = 0;
  await guarded.render({kind: 'strategy-library', scope: 'mine'}, 7);
  assert.deepEqual(calls, [['nav', 'strategies'], ['heading', '策略库']]);
  // An allowVisitor route renders even when login is required.
  calls.length = 0;
  await guarded.render({kind: 'factors'}, 8);
  assert.deepEqual(calls, [
    ['nav', 'factors'], ['heading', '因子库'], ['factors-page'],
  ]);

  console.log('ROUTE DISPATCH NAV: feature entries highlighted, standalone pages clear PASSED');
})();
