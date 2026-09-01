(() => {
  function translate(context, key, fallback = key) {
    return typeof context?.t === "function" ? context.t(key, fallback) : fallback;
  }

  function resultItems(value) {
    if (Array.isArray(value)) return value;
    return Array.isArray(value?.items) ? value.items : [];
  }

  function create({
    context, options, controlDisabled, search, loadStatus,
    setItems, refresh,
  }) {
    const loadItems = options.loadItems;
    let loading = false;
    let errorText = "";
    let loadedQuery = null;
    let resultCount = null;
    let requestID = 0;
    let timer = null;

    function render() {
      loadStatus.hidden = !loading && !errorText
        && !(loadedQuery !== null && resultCount === 0);
      loadStatus.textContent = loading
        ? (options.loadingText || translate(context, "正在读取候选…"))
        : errorText
        ? errorText
        : translate(context, "没有匹配的候选");
      loadStatus.classList.toggle?.("is-error", Boolean(errorText));
    }

    async function load(query = search.value) {
      if (controlDisabled) return;
      const normalizedQuery = String(query || "").trim();
      if (loadedQuery === normalizedQuery && !errorText) return;
      const currentRequestID = ++requestID;
      loading = true;
      errorText = "";
      loadedQuery = null;
      resultCount = null;
      refresh();
      try {
        const nextItems = resultItems(await loadItems(normalizedQuery));
        if (currentRequestID !== requestID) return;
        loadedQuery = normalizedQuery;
        resultCount = nextItems.length;
        setItems(nextItems, true);
      } catch (loadError) {
        if (currentRequestID !== requestID) return;
        loadedQuery = normalizedQuery;
        resultCount = null;
        errorText = loadError?.message || translate(context, "候选读取失败");
      } finally {
        if (currentRequestID === requestID) {
          loading = false;
          refresh();
        }
      }
    }

    function schedule(delay = 220) {
      if (timer !== null) clearTimeout(timer);
      requestID += 1;
      loading = false;
      errorText = "";
      loadedQuery = null;
      resultCount = null;
      refresh();
      const query = search.value;
      timer = setTimeout(() => {
        timer = null;
        void load(query);
      }, Math.max(0, Number(delay) || 0));
    }

    return Object.freeze({load, render, schedule});
  }

  window.FTMultiSelectRemote = Object.freeze({create});
})();
