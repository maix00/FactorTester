const { assert, resetGroupTest, load } = require('./group_test_harness');

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function main() {
  const GT = resetGroupTest();
  load('core/group-settings.js');
  load('results/snapshot.js');

  const overlay = document.registerElement('group-snapshot-drawer');
  document.registerElement('snapshot_title');
  document.registerElement('snapshot_body');
  document.registerElement('snapshot_flow_stats');
  document.registerElement('snapshot-prev-btn');
  document.registerElement('snapshot-next-btn');
  document.registerElement('snapshot_matrix_toggle');

  GT.groupSettings.cache.setLastGrossData([{ submission_id: 'sub-loading' }]);

  let requestBody = null;
  global.fetch = (url, options) => {
    requestBody = JSON.parse(options.body);
    return new Promise(() => {});
  };

  GT.results.snapshot.fetchGroupSnapshot(1710000000000);

  assert.ok(overlay.classList.contains('open'));
  assert.match(document.getElementById('snapshot_title').innerHTML, /加载中/);
  assert.match(document.getElementById('snapshot_body').innerHTML, /正在加载持仓快照/);
  await flushPromises();
  assert.deepStrictEqual(requestBody, {
    submission_id: 'sub-loading',
    timestamp_ms: 1710000000000,
  });

  global.fetch = () => {
    throw new Error('The string did not match the expected pattern.');
  };
  GT.results.snapshot.fetchGroupSnapshot(1710000000001);
  await flushPromises();

  assert.ok(overlay.classList.contains('open'));
  assert.match(document.getElementById('snapshot_title').innerHTML, /错误/);
  assert.match(document.getElementById('snapshot_body').innerHTML, /The string did not match the expected pattern/);

  console.log('PASS: group snapshot drawer opens while loading');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
