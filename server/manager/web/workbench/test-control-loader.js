(() => {
  // One deferred control group can be requested by many fields in the same
  // render pass.  Keep the promise by state and batch callbacks so a group
  // is parsed once and the workbench repaints once after it becomes ready.
  const loads = new WeakMap();

  function ensure(state, group, refresh) {
    if (!group) return Promise.resolve();
    let records = loads.get(state);
    if (!records) {
      records = new Map();
      loads.set(state, records);
    }
    let record = records.get(group);
    if (record?.status === "ready") {
      refresh?.();
      return Promise.resolve();
    }
    if (!record) {
      record = {status: "loading", refreshes: new Set(), promise: null};
      records.set(group, record);
      record.promise = FTTestLazyCode.loadGroup(group)
        .then(() => { record.status = "ready"; flush(record); })
        .catch(error => {
          record.status = "error";
          record.error = error.message || String(error);
          flush(record);
          throw error;
        });
    }
    if (refresh) record.refreshes.add(refresh);
    return record.promise;
  }

  function flush(record) {
    const refreshes = [...record.refreshes];
    record.refreshes.clear();
    queueMicrotask(() => refreshes.forEach(refresh => refresh()));
  }

  window.FTTestControlLoader = Object.freeze({ensure});
})();
