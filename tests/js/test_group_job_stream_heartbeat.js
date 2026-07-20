const { assert, resetGroupTest, load } = require('./group_test_harness');

async function main() {
  resetGroupTest();
  global.SingleFactorResearch = {
    workspace: () => null,
    renewLease: async () => null,
    submit: async () => ({
      jobs: [{
        job_id: 'job-heartbeat',
        stream_url: '/api/jobs/job-heartbeat/stream',
      }],
    }),
  };
  global.fetch = async () => {
    const chunks = [
      new TextEncoder().encode(
        'event: heartbeat\n' +
        'data: {"status":"running","latest_progress":{"seq":7,"event":"signal_progress","data":{"completed":2,"total":4,"percent":50}}}\n\n' +
        'id: 8\n' +
        'event: result\n' +
        'data: {"success":true}\n\n'
      ),
    ];
    return {
      ok: true,
      body: {
        getReader: () => ({
          read: async () => (
            chunks.length ? { done: false, value: chunks.shift() } : { done: true }
          ),
        }),
      },
    };
  };

  load('core/run-test.js');
  const events = [];
  const result = await global.GroupTest.core.runTest.postBatchGroupTest(
    {},
    (event, data) => events.push([event, data])
  );

  const projected = events.find(([event]) => event === 'signal_progress');
  assert(projected);
  assert.equal(projected[1].percent, 50);
  assert.equal(result.success, true);
  console.log('PASS: group job heartbeat projects retained progress');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
