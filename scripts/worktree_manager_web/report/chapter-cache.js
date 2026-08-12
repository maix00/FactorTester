(() => {
  function create(limit = 3) {
    const capacity = Math.max(1, Number(limit) || 1);
    const entries = new Map();

    function get(key) {
      const value = entries.get(key);
      if (value === undefined) return undefined;
      entries.delete(key);
      entries.set(key, value);
      return value;
    }

    function set(key, value) {
      entries.delete(key);
      entries.set(key, value);
      while (entries.size > capacity) entries.delete(entries.keys().next().value);
    }

    return Object.freeze({
      get,
      set,
      clear: () => entries.clear(),
      get size() { return entries.size; },
    });
  }

  window.FTReportChapterCache = Object.freeze({create});
})();
