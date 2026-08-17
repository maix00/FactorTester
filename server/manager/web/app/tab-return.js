(() => {
  const PREFIX = "ft-tab-return:";

  function withSource(path, context, result = {}) {
    const [pathname, rawQuery = ""] = String(path || "").split("?", 2);
    const query = new URLSearchParams(rawQuery);
    if (context?.tabID) query.set("return_tab", context.tabID);
    if (result.kind) query.set("return_kind", result.kind);
    if (result.ref) query.set("return_ref", result.ref);
    const encoded = query.toString();
    return encoded ? `${pathname}?${encoded}` : pathname;
  }

  function markerKey(tabID) {
    return `${PREFIX}${encodeURIComponent(String(tabID || ""))}`;
  }

  function mark(tabID, value = {}) {
    if (!tabID) return;
    sessionStorage.setItem(markerKey(tabID), JSON.stringify({
      ...value, at: Date.now(),
    }));
  }

  function consume(tabID) {
    if (!tabID) return null;
    const key = markerKey(tabID);
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    sessionStorage.removeItem(key);
    try { return JSON.parse(raw); } catch (_) { return null; }
  }

  function returnToSource(context, result = {}) {
    const query = new URLSearchParams(location.search);
    const sourceTab = query.get("return_tab") || "";
    if (!sourceTab || !context?.activateTab) return false;
    mark(sourceTab, result);
    const editorTab = context.tabID;
    context.closeTab?.(editorTab);
    context.activateTab(sourceTab, {forceRender: true});
    return true;
  }

  window.FTTabReturn = Object.freeze({consume, mark, returnToSource, withSource});
})();
