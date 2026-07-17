const { assert, resetGroupTest, load } = require('./group_test_harness');

async function main() {
  resetGroupTest();
  global.SingleFactorResearch = {
    workspace: () => null,
    renewLease: async () => null,
    submit: async () => ({
      jobs: [{
        job_id: 'job-reset',
        stream_url: '/api/jobs/job-reset/stream',
      }],
    }),
  };
  global.fetch = async () => {
    const chunks = [
      new TextEncoder().encode(
        'event: reset\n' +
        'data: {"reason":"daemon_unavailable","status":"submitted"}\n\n'
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
  const result = await global.GroupTest.core.runTest.postBatchGroupTest({});

  assert.equal(result.success, false);
  assert.equal(result.code, 'daemon_unavailable');
  assert(result.error.includes('7998'));
  console.log('PASS: group job stream reset diagnostics');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
