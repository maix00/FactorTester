// page-mode.js — object-page editing-mode presentation for the shared header.
//
// Object detail pages carry an authoring mode (view / edit / create) in the
// route (query ?mode= or the reserved "new" id).  View mode keeps the normal
// quiet header; edit and create modes tint the header background and show a
// small mode badge ("编辑中"/"新建") so the user always sees which object
// surface is writable.  Mode is derived from the active tab's path so tab
// switches, live restores and same-tab mode replacements all re-apply it
// without page code having to announce anything.
(() => {
  const BADGE_KEYS = {edit: "编辑中", create: "新建"};
  const MODE_QUERY = /[?&]mode=(view|edit|create)(?:&|$)/;

  function modeForPath(path) {
    const value = String(path || "").split("#", 1)[0];
    const match = MODE_QUERY.exec(value);
    if (match) return match[1];
    const pathname = value.split(/[?#]/, 1)[0];
    if (/(?:^|\/)(new)$/.test(pathname)) return "create";
    return "view";
  }

  function apply(mode, translate = null) {
    const normalized = ["edit", "create"].includes(mode) ? mode : "";
    if (normalized) document.documentElement.dataset.pageMode = normalized;
    else delete document.documentElement.dataset.pageMode;
    const badge = document.getElementById("page-mode-badge");
    if (!badge) return;
    const key = BADGE_KEYS[normalized];
    if (!key) {
      badge.hidden = true;
      badge.textContent = "";
      return;
    }
    badge.hidden = false;
    // The catalog keys are localized (zh-Hans / en) by the caller's t().
    badge.textContent = typeof translate === "function" ? translate(key) : key;
  }

  function applyFromPath(path, translate = null) {
    apply(modeForPath(path), translate);
  }

  // Same-tab authoring: the edit/create/view URL of the current object must
  // keep this tab's pathname (detail tab ids derive from the pathname), so it
  // is derived from the current location by replacing only the mode query —
  // never from the object's alias/ref, which can differ from the path segment
  // the tab was opened with (e.g. a frozen factor:v2:… view URL).
  function hrefForMode(mode, pathnameOverride = "") {
    let url;
    try {
      url = new URL(window.location?.href || "", "http://local");
    } catch (_) {
      return "";
    }
    if (pathnameOverride) {
      try {
        url.pathname = pathnameOverride;
      } catch (_) { /* keep the current pathname */ }
    }
    if (["view", "edit", "create"].includes(mode)) {
      url.searchParams.set("mode", mode);
    } else {
      url.searchParams.delete("mode");
    }
    return url.pathname + url.search;
  }

  window.FTPageMode = Object.freeze({
    apply, applyFromPath, modeForPath, hrefForMode,
  });
})();
