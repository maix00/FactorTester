(() => {
  function create(options) {
    const {
      state, content, title, eyebrow, toolbar, notice,
      persistSession, restoreSession, removeSession,
    } = options;
    const liveViewLimit = Math.max(1, Number(options.liveViewLimit) || 3);
    const coldViewMemory = new Map();

    function moveChildren(element) {
      if (!element || typeof document.createDocumentFragment !== "function") return null;
      const fragment = document.createDocumentFragment();
      while (element.firstChild) fragment.append(element.firstChild);
      return fragment;
    }

    function restoreChildren(element, fragment) {
      if (!element || !fragment) return;
      element.replaceChildren(...fragment.childNodes);
    }

    function controlList(root) {
      return [...(root?.querySelectorAll?.(
        "input, textarea, select, details, [data-ft-scroll-state]",
      ) || [])];
    }

    function controlBaseKey(control) {
      const explicit = String(
        control?.dataset?.ftStateKey || control?.dataset?.fieldKey || "",
      ).trim();
      if (explicit) return `explicit:${explicit}`;
      if (control?.dataset?.ftScrollState !== undefined) {
        const scrollKey = String(control.dataset.ftScrollState || control.className || "container");
        return `scroll:${scrollKey}`;
      }
      const name = String(control?.name || "").trim();
      if (name) return `name:${name}`;
      const id = String(control?.id || "").trim();
      if (id) return `id:${id}`;
      return "";
    }

    function keyedControls(root) {
      const occurrences = new Map();
      return controlList(root).map((control, index) => {
        const base = controlBaseKey(control);
        if (!base) return {control, index, key: ""};
        const occurrence = occurrences.get(base) || 0;
        occurrences.set(base, occurrence + 1);
        return {control, index, key: `${base}#${occurrence}`};
      });
    }

    function captureControlState(root) {
      return keyedControls(root).map(({control, index, key}) => ({
        index,
        key,
        value: "value" in control ? control.value : undefined,
        checked: "checked" in control ? Boolean(control.checked) : undefined,
        selectedIndex: "selectedIndex" in control ? control.selectedIndex : undefined,
        open: control.tagName === "DETAILS" ? Boolean(control.open) : undefined,
        scrollTop: Number(control.scrollTop || 0),
      }));
    }

    function restoreControlState(root, values) {
      const keyed = keyedControls(root);
      const controls = keyed.map(item => item.control);
      const byKey = new Map(keyed.filter(item => item.key).map(item => [item.key, item.control]));
      (Array.isArray(values) ? values : []).forEach(item => {
        const control = (item.key && byKey.get(item.key)) || controls[item.index];
        if (!control) return;
        if (item.value !== undefined && "value" in control) control.value = item.value;
        if (item.checked !== undefined && "checked" in control) control.checked = item.checked;
        if (item.selectedIndex !== undefined && "selectedIndex" in control) {
          control.selectedIndex = item.selectedIndex;
        }
        if (item.open !== undefined && control.tagName === "DETAILS") control.open = item.open;
        if (item.scrollTop !== undefined) control.scrollTop = item.scrollTop;
      });
    }

    function coldStorageKey(tabID) {
      return `ft-tab-view:${encodeURIComponent(String(tabID))}`;
    }

    function writeColdView(tabID, value) {
      const key = coldStorageKey(tabID);
      coldViewMemory.set(key, value);
      try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
      return key;
    }

    function readColdView(key) {
      try {
        const raw = sessionStorage.getItem(key);
        if (raw) return JSON.parse(raw);
      } catch (_) {}
      return coldViewMemory.get(key) || null;
    }

    function deleteColdView(tabID) {
      const key = coldStorageKey(tabID);
      coldViewMemory.delete(key);
      try { sessionStorage.removeItem(key); } catch (_) {}
    }

    function dialogList() {
      return [...(document.querySelectorAll?.("dialog") || [])];
    }

    function tagDialog(dialog) {
      if (!dialog?.dataset) return;
      if (dialog.id === "login-dialog" || dialog.dataset.ftGlobal === "true") return;
      if (!dialog.dataset.ftTabID) dialog.dataset.ftTabID = state.activeTabID;
    }

    function observeDialogs() {
      if (!document.body || typeof MutationObserver !== "function") return;
      const observer = new MutationObserver(records => {
        records.forEach(record => record.addedNodes?.forEach(node => {
          if (node.nodeType !== 1) return;
          if (node.matches?.("dialog")) tagDialog(node);
          node.querySelectorAll?.("dialog").forEach(tagDialog);
        }));
      });
      observer.observe(document.body, {childList: true, subtree: true});
      dialogList().forEach(tagDialog);
    }

    function parkOverlays(tabID, session) {
      const overlays = dialogList().filter(dialog => (
        dialog.dataset?.ftTabID === tabID && Boolean(dialog.open)
      ));
      session.overlays = overlays.map(dialog => {
        const open = Boolean(dialog.open);
        if (open) dialog.removeAttribute("open");
        dialog.hidden = true;
        dialog.inert = true;
        dialog.setAttribute("aria-hidden", "true");
        return {dialog, open};
      });
    }

    function restoreOverlays(tabID, session) {
      const records = Array.isArray(session.overlays) ? session.overlays : [];
      session.overlays = records.filter(record => record.dialog?.isConnected !== false);
      session.overlays.forEach(record => {
        const dialog = record.dialog;
        if (!dialog) return;
        if (!record.open) return;
        dialog.hidden = false;
        dialog.inert = false;
        dialog.removeAttribute("aria-hidden");
        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "");
      });
      dialogList().filter(dialog => dialog.dataset?.ftTabID === tabID)
        .forEach(dialog => {
          if (!session.overlays.some(item => item.dialog === dialog)) tagDialog(dialog);
        });
    }

    function activeTabHasOverlay() {
      return dialogList().some(dialog => (
        dialog.dataset?.ftTabID === state.activeTabID
        && !dialog.hidden && Boolean(dialog.open)
      ));
    }

    function tabSession(tabID) {
      if (!state.tabSessions.has(tabID)) state.tabSessions.set(tabID, {});
      return state.tabSessions.get(tabID);
    }

    function isResearchReportTab(tabID) {
      if (String(tabID || "").startsWith("research-report:")) return true;
      const tab = state.tabs.find(item => item.id === tabID);
      const pathname = String(tab?.path || "").split(/[?#]/, 1)[0];
      return /^\/research\/.+$/.test(pathname);
    }

    function hasReportHeading(session) {
      const heading = session?.durable?.heading;
      return Boolean(heading && String(heading.title || "").trim()
        && String(heading.eyebrow || "").trim());
    }

    function invalidateLegacyReportView(tabID, session) {
      if (!isResearchReportTab(tabID) || hasReportHeading(session)) return false;
      if (!session.view && !session.view?.coldKey) return false;
      // Older report tabs persisted the DOM under a publication alias before
      // concrete reports owned their own tab. Re-render once so the report
      // entry can restore its durable reading state and write the localized
      // title/scope metadata to the concrete tab.
      session.view = null;
      session.viewReady = false;
      deleteColdView(tabID);
      return true;
    }

    function enforceLiveViewLimit(excludeTabID) {
      const live = state.tabs.map(tab => ({
        tabID: tab.id, session: tabSession(tab.id),
      })).filter(item => item.session.view?.content);
      while (live.length > liveViewLimit) {
        live.sort((left, right) => (
          (left.session.view.lastUsedAt || 0) - (right.session.view.lastUsedAt || 0)
        ));
        const candidateIndex = live.findIndex(item => item.tabID !== excludeTabID);
        const item = candidateIndex < 0 ? null : live.splice(candidateIndex, 1)[0];
        if (!item) return;
        coldifySession(item.tabID, item.session);
      }
    }

    function coldifySession(tabID, session) {
      const view = session.view;
      if (!view?.content || tabID === state.activeTabID) return;
      const snapshot = {
        title: view.title || "",
        eyebrow: view.eyebrow || "",
        notice: view.notice || null,
        navRoute: view.navRoute || "",
        scrollY: Number(session.scrollY || 0),
        contentControls: captureControlState(view.content),
        toolbarControls: captureControlState(view.toolbar),
      };
      const key = writeColdView(tabID, snapshot);
      session.view = {
        coldKey: key, pendingRestore: false, ready: true,
        lastUsedAt: view.lastUsedAt || Date.now(),
      };
    }

    function saveView(session) {
      if (!content) return;
      if (session.view?.coldKey && session.view.pendingRestore
          && session.viewReady === false) return;
      const view = session.view || {};
      if (view.rerenderOnRestore) {
        view.lastUsedAt = Date.now();
        session.view = view;
        return;
      }
      const rerenderNode = content.querySelector?.(
        "[data-ft-rerender-on-tab-restore]",
      );
      if (rerenderNode) {
        rerenderNode.__ftBeforeTabSave?.();
        content.replaceChildren();
        view.title = title?.textContent || "";
        view.eyebrow = eyebrow?.textContent || "";
        view.notice = notice ? {
          text: notice.textContent || "", color: notice.style?.color || "",
        } : null;
        view.navRoute = document.querySelector?.(".nav-button.active")?.dataset?.route || "";
        view.rerenderOnRestore = true;
        view.ready = false;
        view.lastUsedAt = Date.now();
        session.view = view;
        return;
      }
      // Pointerdown captures report scroll before click navigates.  A second
      // save sees an empty shell, so retain the already detached fragment.
      if (view.content?.childNodes?.length && !content.firstChild) {
        view.lastUsedAt = Date.now();
        session.view = view;
        return;
      }
      view.content = moveChildren(content);
      view.toolbar = moveChildren(toolbar);
      view.title = title?.textContent || "";
      view.eyebrow = eyebrow?.textContent || "";
      view.notice = notice ? {
        text: notice.textContent || "", color: notice.style?.color || "",
      } : null;
      view.navRoute = document.querySelector?.(".nav-button.active")?.dataset?.route || "";
      view.ready = session.viewReady !== false;
      view.lastUsedAt = Date.now();
      session.view = view;
      enforceLiveViewLimit(state.activeTabID);
    }

    function restoreView(tabID) {
      const session = tabSession(tabID);
      if (invalidateLegacyReportView(tabID, session)) return false;
      const view = session.view;
      if (view?.rerenderOnRestore) {
        // This flag is a one-shot invalidation, not a permanent session mode.
        // The route about to render becomes the next live view and must be
        // eligible for the same save/stop/reconcile cycle on a later switch.
        view.rerenderOnRestore = false;
        view.ready = false;
        return false;
      }
      if (view?.coldKey) {
        view.pendingRestore = true;
        return "cold";
      }
      if (!view?.ready || !view.content) return false;
      view.lastUsedAt = Date.now();
      restoreChildren(content, view.content);
      restoreChildren(toolbar, view.toolbar);
      if (title) title.textContent = view.title || "";
      if (eyebrow) eyebrow.textContent = view.eyebrow || "";
      if (notice && view.notice) {
        notice.textContent = view.notice.text;
        notice.style.color = view.notice.color;
      }
      restoreActiveNav(view.navRoute);
      restoreOverlays(tabID, session);
      state.pendingScrollCapture = null;
      window.requestAnimationFrame?.(() => window.scrollTo({
        top: Number.isFinite(session.scrollY) ? session.scrollY : 0,
        behavior: "auto",
      }));
      return "live";
    }

    function restoreActiveNav(route) {
      if (!route) return;
      document.querySelectorAll?.(".nav-button").forEach(item => {
        item.classList.toggle("active", item.dataset.route === route);
      });
    }

    function restoreColdView() {
      const session = tabSession(state.activeTabID);
      if (invalidateLegacyReportView(state.activeTabID, session)) return false;
      const view = session.view;
      if (!view?.coldKey || !view.pendingRestore) return false;
      const snapshot = readColdView(view.coldKey);
      if (!snapshot) {
        session.view = null;
        return false;
      }
      restoreControlState(content, snapshot.contentControls);
      restoreControlState(toolbar, snapshot.toolbarControls);
      if (title) title.textContent = snapshot.title || title.textContent;
      if (eyebrow) eyebrow.textContent = snapshot.eyebrow || eyebrow.textContent;
      if (notice && snapshot.notice) {
        notice.textContent = snapshot.notice.text || "";
        notice.style.color = snapshot.notice.color || "";
      }
      restoreActiveNav(snapshot.navRoute);
      deleteColdView(state.activeTabID);
      delete view.coldKey;
      view.pendingRestore = false;
      view.lastUsedAt = Date.now();
      restoreOverlays(state.activeTabID, session);
      window.requestAnimationFrame?.(() => window.scrollTo({
        top: Number.isFinite(snapshot.scrollY) ? snapshot.scrollY : 0,
        behavior: "auto",
      }));
      return true;
    }

    function discardView(tabID) {
      const session = tabSession(tabID);
      session.view = null;
      session.viewReady = false;
      session.overlays = [];
      deleteColdView(tabID);
    }

    function hydrateSession(tabID) {
      const saved = restoreSession?.(tabID);
      if (!saved || typeof saved !== "object") return false;
      const session = tabSession(tabID);
      session.path = String(saved.path || "");
      session.scrollY = Number(saved.scrollY || 0);
      session.durable = saved.durable && typeof saved.durable === "object"
        ? saved.durable : {};
      const key = writeColdView(tabID, saved);
      session.view = {
        coldKey: key, pendingRestore: false, ready: true,
        lastUsedAt: Number(saved.updatedAt || Date.now()),
      };
      return true;
    }

    function activeSessionSnapshot() {
      const reportMatch = /^\/research\/(.+)$/.exec(location.pathname);
      let publicationID = reportMatch?.[1] || null;
      if (publicationID) {
        try { publicationID = decodeURIComponent(publicationID); } catch (_) {}
      }
      const pending = state.pendingScrollCapture?.tabID === state.activeTabID
        ? state.pendingScrollCapture : null;
      const session = tabSession(state.activeTabID);
      return {
        scrollY: pending ? pending.scrollY : window.scrollY,
        path: location.pathname,
        publicationID,
        durable: session.durable || {},
        title: title?.textContent || "",
        eyebrow: eyebrow?.textContent || "",
        notice: notice ? {text: notice.textContent || "", color: notice.style?.color || ""} : null,
        navRoute: document.querySelector?.(".nav-button.active")?.dataset?.route || "",
        contentControls: captureControlState(content),
        toolbarControls: captureControlState(toolbar),
        updatedAt: Date.now(),
      };
    }

    function checkpointActiveSession() {
      const snapshot = activeSessionSnapshot();
      Object.assign(tabSession(state.activeTabID), {
        scrollY: snapshot.scrollY,
        path: snapshot.path,
        publicationID: snapshot.publicationID,
      });
      persistSession?.(state.activeTabID, snapshot);
      return snapshot;
    }

    function saveActiveTabSession() {
      const snapshot = checkpointActiveSession();
      const session = tabSession(state.activeTabID);
      saveView(session);
      parkOverlays(state.activeTabID, session);
    }

    function captureScrollPosition() {
      state.pendingScrollCapture = {tabID: state.activeTabID, scrollY: window.scrollY};
      saveActiveTabSession();
    }

    function markActiveViewLoading() {
      tabSession(state.activeTabID).viewReady = false;
    }

    function markActiveViewReady() {
      tabSession(state.activeTabID).viewReady = true;
      restoreColdView();
    }

    observeDialogs();
    return Object.freeze({
      tabSession, saveActiveTabSession, captureScrollPosition,
      checkpointActiveSession,
      markActiveViewLoading, markActiveViewReady, restoreView,
      restoreColdView, discardView, hydrateSession, activeTabHasOverlay,
    });
  }

  window.FTTabViewCache = Object.freeze({create});
})();
