(() => {
  function create(options) {
    const {
      state, embeddedPresentation, t, renderRoute,
      modulePath, isPinnedPath, titleForPath, tabIcon,
      content, title, eyebrow, toolbar, notice, beforeTabChange,
      liveViewLimit,
      onTabClosed,
      onTabEvicted,
      pageAgentLifecycle,
    } = options;
    let workspace = null;
    let checkpointTimer = null;
    let draggingTabID = "";
    const viewCache = window.FTTabViewCache.create({
      state, content, title, eyebrow, toolbar, notice,
      persistSession: (tabID, value) => workspace?.saveSession?.(tabID, value),
      restoreSession: tabID => workspace?.restoreSession?.(tabID),
      removeSession: tabID => workspace?.removeSession?.(tabID),
      liveViewLimit,
      onTabEvicted,
    });

    function checkpointWorkspace() {
      workspace?.save?.({tabs: state.tabs, activeTabID: state.activeTabID});
    }

    function checkpointActiveSession() {
      if (checkpointTimer) {
        clearTimeout(checkpointTimer);
        checkpointTimer = null;
      }
      viewCache.checkpointActiveSession();
      checkpointWorkspace();
    }

    function scheduleActiveSessionCheckpoint() {
      if (checkpointTimer) clearTimeout(checkpointTimer);
      checkpointTimer = setTimeout(checkpointActiveSession, 250);
    }

    function setWorkspace(value) {
      workspace = value || null;
    }

    function tabPathname(tab) {
      return String(tab?.path || "").split(/[?#]/, 1)[0];
    }

    function isResearchDetailTab(tab) {
      return String(tab?.id || "").startsWith("research-detail:")
        || /^\/researches\/.+/.test(tabPathname(tab));
    }

    function researchDetailIDForTab(tab) {
      const pathMatch = /^\/researches\/(.+)$/.exec(tabPathname(tab));
      if (pathMatch) {
        try { return decodeURIComponent(pathMatch[1]); } catch (_) { return pathMatch[1]; }
      }
      const idMatch = /^research-detail:(.+)$/.exec(String(tab?.id || ""));
      if (!idMatch) return "";
      try { return decodeURIComponent(idMatch[1]); } catch (_) { return idMatch[1]; }
    }

    function researchIDForTab(tab) {
      // A Research detail tab is a folder and must derive its own identity
      // from its route/id. Never trust persisted parent metadata here: stale
      // parentResearchID values must not turn one Research into another.
      if (isResearchDetailTab(tab)) return researchDetailIDForTab(tab);
      const stored = String(tab?.parentResearchID || "").trim();
      if (stored) return stored;
      return "";
    }

    function isResearchChildTab(tab, detailIDs = null) {
      const parentID = String(tab?.parentTabID || "").trim();
      if (!parentID || tab?.parentFolder !== "research") return false;
      return !detailIDs || detailIDs.has(parentID);
    }

    function isResearchSidebarTab(tab) {
      if (!tab?.closable) return false;
      if (tab?.parentFolder === "research") return true;
      return isResearchDetailTab(tab);
    }

    function researchFolderHost() {
      // Open Research instances are user tabs, not children of the pinned
      // Research feature entry.  Render their folders in the common opened
      // tab rail so the feature navigation keeps its ordinary static shape.
      return document.querySelector("#opened-tabs");
    }

    function applyTabMetadata(tab, options) {
      ["parentFolder", "parentTabID", "parentResearchID"].forEach(key => {
        if (Object.prototype.hasOwnProperty.call(options, key)) {
          const value = String(options[key] || "").trim();
          if (value) tab[key] = value;
          else delete tab[key];
        }
      });
    }

    function isDraggableTab(tab) {
      // Pinned feature entries are not closable and therefore never reach
      // this path. Research detail tabs are folders; allowing them to be
      // dragged would make it possible to create Research-under-Research.
      return Boolean(tab?.closable) && !isResearchDetailTab(tab);
    }

    function dragTabID(event) {
      return draggingTabID || event.dataTransfer?.getData("text/plain") || "";
    }

    function clearDropMarkers() {
      const nodes = document.querySelectorAll?.(
        ".drop-target, .drop-before, .drop-after",
      ) || [];
      nodes.forEach(node => node.classList.remove("drop-target", "drop-before", "drop-after"));
    }

    function focusMovedTab(tabID) {
      const row = [...(document.querySelectorAll?.(
        ".opened-tab, .nav-folder-row",
      ) || [])].find(item => item.dataset.tabID === tabID
        || item.dataset.dragTabID === tabID);
      row?.querySelector?.(".tab-main")?.focus?.();
    }

    function flashMovedTab(tabID) {
      const row = [...(document.querySelectorAll?.(
        ".opened-tab, .nav-folder-row",
      ) || [])].find(item => item.dataset.tabID === tabID
        || item.dataset.dragTabID === tabID);
      if (!row) return;
      row.classList.remove("tab-moved");
      // Force a new animation when the same tab is moved twice in quick
      // succession.  The read is intentionally local to the moved row.
      void row.offsetWidth;
      row.classList.add("tab-moved");
      setTimeout(() => row.classList.remove("tab-moved"), 700);
    }

    function renderMovedTab(tabID) {
      renderOpenedTabs();
      flashMovedTab(tabID);
      focusMovedTab(tabID);
    }

    function dropBefore(event, target) {
      if (typeof event.before === "boolean") return event.before;
      const rect = target.getBoundingClientRect?.();
      if (!rect || !Number.isFinite(rect.top) || !Number.isFinite(rect.height)) return true;
      return event.clientY < rect.top + rect.height / 2;
    }

    function researchParentTabID(tab) {
      if (tab?.parentFolder !== "research") return "";
      const parentID = String(tab.parentTabID || "").trim();
      if (!parentID) return "";
      const parent = state.tabs.find(item => item.id === parentID);
      return parent && isResearchDetailTab(parent) ? parentID : "";
    }

    function tabButton(tab, nested = false) {
      const button = document.createElement("button");
      button.className = `tab-main${nested ? " nav-grandchild" : ""}`;
      button.type = "button";
      button.innerHTML = '<span class="symbol"></span><span class="tab-label"></span>';
      button.querySelector(".symbol").append(FTIcons.node(tab.icon || tabIcon(tab.path)));
      button.querySelector(".tab-label").textContent = tab.title;
      button.title = document.body.classList.contains("sidebar-collapsed") ? "" : tab.title;
      button.setAttribute("aria-label", tab.title);
      button.addEventListener("click", () => activateTab(tab.id));
      return button;
    }

    function tabCloseButton(tab) {
      const close = document.createElement("button");
      close.className = "tab-close";
      close.type = "button";
      close.textContent = "×";
      close.title = t("关闭");
      close.addEventListener("click", event => {
        event.stopPropagation();
        closeTab(tab.id);
      });
      return close;
    }

    function tabDragSource(row, tab) {
      if (!isDraggableTab(tab)) return;
      row.classList.add("draggable-tab");
      row.dataset.dragTabID = tab.id;
      const source = row;
      source.draggable = true;
      source.addEventListener("dragstart", event => {
        draggingTabID = tab.id;
        event.dataTransfer?.setData?.("text/plain", tab.id);
        if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
        row.classList.add("dragging");
        if (event.dataTransfer?.setDragImage && document.body?.append) {
          const preview = document.createElement("div");
          preview.className = "tab-drag-preview";
          preview.textContent = tab.title;
          document.body.append(preview);
          // Keep the preview alive for the native drag operation. Removing it
          // on the next task is racy in WebKit and makes the drag image blank.
          source.__ftDragPreview = preview;
          event.dataTransfer.setDragImage(preview, 12, 12);
        }
      });
      source.addEventListener("dragend", () => {
        draggingTabID = "";
        row.classList.remove("dragging");
        source.__ftDragPreview?.remove?.();
        source.__ftDragPreview = null;
        clearDropMarkers();
      });
    }

    function tabRow(tab, {nested = false} = {}) {
      const row = document.createElement("div");
      row.className = `opened-tab${nested ? " opened-tab-nested" : ""}${tab.id === state.activeTabID ? " active" : ""}`;
      row.dataset.tabID = tab.id;
      row.append(tabButton(tab, nested), tabCloseButton(tab));
      tabDragSource(row, tab);
      if (isResearchDetailTab(tab)) acceptTabDrop(row, tab.id);
      else acceptTabRowDrop(row, tab);
      return row;
    }

    function assignTabParent(tab, parentTabID = "") {
      if (!isDraggableTab(tab)) return false;
      const parent = state.tabs.find(item => item.id === parentTabID);
      if (parentTabID && (!parent || !isResearchDetailTab(parent))) return false;
      if (parentTabID === tab.id) return false;
      if (parentTabID) {
        const researchID = researchIDForTab(parent);
        if (!researchID) return false;
        tab.parentFolder = "research";
        tab.parentTabID = parentTabID;
        tab.parentResearchID = researchID;
      } else {
        delete tab.parentFolder;
        delete tab.parentTabID;
        delete tab.parentResearchID;
      }
      return true;
    }

    function insertTabRelative(source, target, before) {
      const sourceIndex = state.tabs.indexOf(source);
      if (sourceIndex < 0) return false;
      state.tabs.splice(sourceIndex, 1);
      const targetIndex = state.tabs.indexOf(target);
      if (targetIndex < 0) {
        state.tabs.splice(sourceIndex, 0, source);
        return false;
      }
      state.tabs.splice(targetIndex + (before ? 0 : 1), 0, source);
      return true;
    }

    function moveTabToOpened(tabID) {
      const tab = state.tabs.find(item => item.id === tabID);
      if (!assignTabParent(tab, "")) return false;
      const siblings = state.tabs.filter(item => (
        isDraggableTab(item) && !item.parentFolder && item.id !== tabID
      ));
      const last = siblings.at(-1);
      if (last) insertTabRelative(tab, last, false);
      checkpointWorkspace();
      renderMovedTab(tabID);
      return true;
    }

    function moveTabIntoResearch(tabID, parentTabID) {
      const tab = state.tabs.find(item => item.id === tabID);
      if (!assignTabParent(tab, parentTabID)) return false;
      const siblings = state.tabs.filter(item => (
        isDraggableTab(item) && item.parentTabID === parentTabID && item.id !== tabID
      ));
      const last = siblings.at(-1);
      if (last) insertTabRelative(tab, last, false);
      checkpointWorkspace();
      renderMovedTab(tabID);
      return true;
    }

    function moveTabRelative(tabID, targetTabID, before) {
      const tab = state.tabs.find(item => item.id === tabID);
      const target = state.tabs.find(item => item.id === targetTabID);
      if (!isDraggableTab(tab) || !target?.closable || tab === target) return false;
      if (isResearchDetailTab(target)) return moveTabIntoResearch(tabID, target.id);
      if (!assignTabParent(tab, researchParentTabID(target))) return false;
      if (!insertTabRelative(tab, target, before)) return false;
      checkpointWorkspace();
      renderMovedTab(tabID);
      return true;
    }

    function moveTabToResearchFolder(tabID, parentTabID = "") {
      return parentTabID ? moveTabIntoResearch(tabID, parentTabID) : moveTabToOpened(tabID);
    }

    function acceptTabRowDrop(target, targetTab) {
      if (target.__ftTabRowDropBound) return;
      target.__ftTabRowDropBound = true;
      target.addEventListener("dragover", event => {
        const sourceID = dragTabID(event);
        const source = state.tabs.find(item => item.id === sourceID);
        if (!isDraggableTab(source) || source.id === targetTab.id) {
          event.stopPropagation();
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        clearDropMarkers();
        if (isResearchDetailTab(targetTab)) {
          // A Research detail tab is a folder. Dropping on its header mounts
          // the source below it; before/after would falsely suggest that the
          // Research itself can be reordered or nested.
          target.classList.add("drop-target");
        } else {
          target.classList.add(dropBefore(event, target) ? "drop-before" : "drop-after");
        }
        if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      });
      target.addEventListener("dragleave", () => {
        target.classList.remove("drop-target", "drop-before", "drop-after");
      });
      target.addEventListener("drop", event => {
        event.preventDefault();
        event.stopPropagation();
        const sourceID = dragTabID(event);
        const source = state.tabs.find(item => item.id === sourceID);
        const before = isResearchDetailTab(targetTab)
          ? false : dropBefore(event, target);
        clearDropMarkers();
        if (!isDraggableTab(source) || source.id === targetTab.id) return;
        moveTabRelative(sourceID, targetTab.id, before);
      });
    }

    function acceptTabDrop(target, parentTabID = "") {
      target.__ftDropParentTabID = String(parentTabID || "");
      if (target.__ftTabDropBound) return;
      target.__ftTabDropBound = true;
      target.addEventListener("dragover", event => {
        const tabID = dragTabID(event);
        const tab = state.tabs.find(item => item.id === tabID);
        if (!isDraggableTab(tab)) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        clearDropMarkers();
        target.classList.add("drop-target");
      });
      target.addEventListener("dragleave", () => target.classList.remove("drop-target"));
      target.addEventListener("drop", event => {
        event.preventDefault();
        event.stopPropagation();
        target.classList.remove("drop-target");
        moveTabToResearchFolder(dragTabID(event), target.__ftDropParentTabID || "");
      });
    }

    function renderResearchSidebarTabs() {
      const host = researchFolderHost();
      if (!host) return false;
      // The opened-tab rail is the unmount target.  The drop handler
      // stops propagation so a child Research folder can still receive a
      // drop without being immediately detached by this parent listener.
      acceptTabDrop(host, "");
      const detailTabs = state.tabs.filter(tab => tab.closable && isResearchDetailTab(tab));
      const detailIDs = new Set(detailTabs.map(tab => tab.id));
      const childrenByParent = new Map();
      const direct = [];
      let repairedOrphan = false;
      state.tabs.filter(tab => tab.closable && !isResearchDetailTab(tab)).forEach(tab => {
        if (isResearchChildTab(tab, detailIDs)) {
          const rows = childrenByParent.get(tab.parentTabID) || [];
          rows.push(tab);
          childrenByParent.set(tab.parentTabID, rows);
          return;
        }
        if (tab.parentFolder === "research") {
          // An orphaned child is still a valid independent tab.  Detach only
          // the stale parent pointer so it cannot disappear from the rail.
          delete tab.parentTabID;
          delete tab.parentResearchID;
          repairedOrphan = true;
          direct.push(tab);
        }
      });
      detailTabs.forEach(tab => {
        const children = childrenByParent.get(tab.id) || [];
        if (!children.length) {
          const row = tabRow(tab);
          acceptTabDrop(row, tab.id);
          host.append(row);
          return;
        }
        const wrapper = document.createElement("div");
        wrapper.className = "nav-folder nav-research-detail-folder";
        wrapper.dataset.navFolder = `research-tab:${tab.id}`;
        const header = document.createElement("div");
        header.className = "nav-folder-row";
        const expanded = localStorage.getItem(
          `ft-nav-folder-research-tab-${encodeURIComponent(tab.id)}-collapsed`,
        ) !== "1";
        const disclosure = document.createElement("button");
        disclosure.type = "button";
        disclosure.className = "nav-folder-toggle";
        disclosure.textContent = expanded ? "▾" : "▸";
        disclosure.setAttribute("aria-expanded", expanded ? "true" : "false");
        disclosure.title = t(expanded ? "收起" : "展开");
        const button = tabButton(tab);
        button.classList.add("nav-folder-tab");
        const close = tabCloseButton(tab);
        header.append(button, disclosure, close);
        acceptTabDrop(header, tab.id);
        const childHost = document.createElement("div");
        childHost.className = "nav-folder-children nav-research-tab-children";
        childHost.hidden = !expanded;
        children.forEach(child => childHost.append(tabRow(child, {nested: true})));
        disclosure.addEventListener("click", event => {
          event.stopPropagation();
          const next = childHost.hidden;
          childHost.hidden = !next;
          disclosure.textContent = next ? "▾" : "▸";
          disclosure.setAttribute("aria-expanded", next ? "true" : "false");
          disclosure.title = t(next ? "收起" : "展开");
          localStorage.setItem(
            `ft-nav-folder-research-tab-${encodeURIComponent(tab.id)}-collapsed`,
            next ? "0" : "1",
          );
        });
        acceptTabDrop(wrapper, tab.id);
        wrapper.append(header, childHost);
        host.append(wrapper);
      });
      direct.forEach(tab => host.append(tabRow(tab)));
      if (repairedOrphan) checkpointWorkspace();
      return true;
    }

    function renderOpenedTabs() {
      const host = document.querySelector("#opened-tabs");
      const caption = document.querySelector("#opened-caption");
      if (!host || !caption) return;
      host.replaceChildren();
      const hasResearchHost = Boolean(researchFolderHost());
      const opened = state.tabs.filter(tab => (
        tab.closable && (!hasResearchHost || !isResearchSidebarTab(tab))
      ));
      caption.hidden = !state.tabs.some(tab => tab.closable);
      for (const tab of opened) {
        host.append(tabRow(tab));
      }
      // Dropping on the empty area of the opened-tab rail removes a tab from
      // a Research folder. Dropping on a specific row is handled by the row
      // reorder target above, so it can also place the tab precisely.
      acceptTabDrop(host, "");
      renderResearchSidebarTabs();
    }

    function activateTab(tabID, options = {}) {
      const tab = state.tabs.find(item => item.id === tabID);
      if (!tab) return;
      viewCache.saveActiveTabSession();
      if (options.discardView) viewCache.discardView(tabID);
      if (tabID !== state.activeTabID || options.forceRender) {
        (options.beforeTabChange || beforeTabChange)?.();
      }
      state.activeTabID = tabID;
      history.pushState({}, "", tab.path);
      renderOpenedTabs();
      checkpointWorkspace();
      if (!options.forceRender) {
        const restored = viewCache.restoreView(tabID);
        if (restored === "live") return;
        if (restored === "cold") {
          renderRoute();
          return;
        }
      }
      renderRoute();
    }

    function closeTab(tabID) {
      const index = state.tabs.findIndex(tab => tab.id === tabID);
      if (index < 0) return;
      if (state.activeTabID === tabID) {
        viewCache.saveActiveTabSession();
        // Saving parks live DOM and overlays.  A closing tab must then dispose
        // that parked view before its session is removed; otherwise detached
        // live content can remain authoritative after the fallback route.
        viewCache.discardView(tabID);
      } else viewCache.discardView(tabID);
      const closingTab = state.tabs[index];
      const closingSession = state.tabSessions.get(tabID) || null;
      // A research tab is only a sidebar folder; its children are independent
      // tabs.  Detach them when the folder closes so no report or analysis
      // becomes inaccessible or remains hidden behind a dead parent pointer.
      state.tabs.forEach(tab => {
        if (tab.parentTabID !== tabID) return;
        tab.parentFolder = "research";
        delete tab.parentTabID;
        delete tab.parentResearchID;
      });
      state.tabs.splice(index, 1); state.tabSessions.delete(tabID);
      workspace?.removeSession?.(tabID);
      Promise.resolve(onTabClosed?.(closingTab, closingSession)).catch(() => {});
      if (state.activeTabID !== tabID) {
        renderOpenedTabs();
        checkpointWorkspace();
        return;
      }
      beforeTabChange?.();
      // Pinned feature tabs stay in state.tabs but are not user-opened tabs.
      // When the last closable tab is closed, always return to the home tab
      // instead of accidentally selecting a pinned feature tab near it.
      const closableTabs = state.tabs.filter(tab => tab.closable);
      const previousClosable = state.tabs.slice(0, index)
        .filter(tab => tab.closable).at(-1);
      const nextClosable = state.tabs.slice(index)
        .find(tab => tab.closable);
      const fallback = closableTabs.length
        ? previousClosable || nextClosable || closableTabs[0]
        : state.tabs.find(tab => tab.id === "home") || state.tabs[0];
      state.activeTabID = fallback?.id || "home";
      history.pushState({}, "", fallback?.path || "/");
      renderOpenedTabs();
      checkpointWorkspace();
      // Closing the active tab is a navigation boundary, not an ordinary
      // cache switch.  Always run the fallback route once so URL, active tab,
      // route token and rendered content advance atomically.
      renderRoute();
    }

    function openModule(module) {
      const path = modulePath(module);
      const rootID = String(module?.id || "").split(".")[0];
      const root = rootID && rootID !== module.id
        ? state.modules.find(item => item.id === rootID)
        : null;
      if (root) {
        // Registered child entries are views of their pinned feature folder,
        // not extra sidebar tabs.  Keep the root tab as the single owner of
        // the route while allowing the child to choose its section.
        return openTab(path, {
          id: root.id,
          title: t(root.title_key || root.title),
          icon: FTIcons.module(root),
          closable: false,
        });
      }
      if (module.tab_behavior === "new") {
        return openTab(path, {forceNew: true, title: t(module.title_key || module.title)});
      }
      return openTab(path, {
        id: module.id, title: t(module.title_key || module.title), closable: false,
      });
    }

    function openTab(path, options = {}) {
      if (!options.forceNew && options.id) {
        const existingByID = state.tabs.find(tab => tab.id === options.id);
        if (existingByID) {
          const pathChanged = existingByID.path !== path;
          existingByID.path = path;
          if (options.title) existingByID.title = options.title;
          if (options.icon) existingByID.icon = options.icon;
          applyTabMetadata(existingByID, options);
          activateTab(existingByID.id, {
            forceRender: pathChanged,
            discardView: pathChanged,
            beforeTabChange: options.beforeTabChange,
          });
          state.pendingScrollCapture = null;
          return;
        }
      }
      if (!options.forceNew) {
        const existing = state.tabs.find(tab => tab.path === path);
        if (existing) {
          applyTabMetadata(existing, options);
          activateTab(existing.id, {beforeTabChange: options.beforeTabChange});
          state.pendingScrollCapture = null;
          return;
        }
      }
      const pinned = options.closable === false || (isPinnedPath(path) && !options.forceNew);
      const id = options.id || `${path}:${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
      const tab = {
        id, path, title: options.title || titleForPath(path),
        icon: options.icon || tabIcon(path), closable: !pinned,
      };
      applyTabMetadata(tab, options);
      state.tabs.push(tab);
      activateTab(id, {forceRender: true, beforeTabChange: options.beforeTabChange});
      state.pendingScrollCapture = null;
    }

    function productDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/products\/(group|product|contract|continuous-contract)\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[2];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `product-detail:${match[1]}:${target}`;
    }

    function factorDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/factors\/(family|factor|set)\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[2];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `factor-detail:${match[1]}:${target}`;
    }

    function profileDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/profiles\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      let profileKey = "local";
      try {
        profileKey = new URL(path, location.origin).searchParams.get("profile_key") || "local";
      } catch (_) {}
      return `profile-detail:${target}:${profileKey}`;
    }

    function productCategoryDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/products\/categories\/(.+)$/.exec(pathname);
      if (!match || match[1] === "new") return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `product-category-detail:${target}`;
    }

    function productSourceFamilyDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/products\/sources\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `product-source-family-detail:${target}`;
    }

    function jobDetailTabID(path) {
      let route;
      try { route = new URL(String(path || ""), "http://factortester.invalid"); }
      catch (_) { return ""; }
      const parts = route.pathname.split("/").filter(Boolean);
      if (parts[0] !== "jobs" || parts.length < 2) return "";
      // Configuration and input pages are separate detail routes. They must
      // not share the base task tab, otherwise restoring the task tab can
      // bring back the test workbench DOM instead of the requested page.
      if ((parts.length === 3 && parts[2] === "configuration")
          || (parts.length >= 4 && parts[2] === "inputs")
          || parts.length >= 4) return "";
      const port = parts.length === 2 ? "0" : parts[1];
      const target = parts.length === 2 ? parts[1] : parts.slice(2).join("/");
      let jobID = target;
      try { jobID = decodeURIComponent(target); } catch (_) {}
      const serverID = route.searchParams.get("server_id") || "";
      return `job-detail:${port}:${encodeURIComponent(serverID)}:${encodeURIComponent(jobID)}`;
    }

    function runSpecTabID(path) {
      let route;
      try { route = new URL(String(path || ""), "http://factortester.invalid"); }
      catch (_) { return ""; }
      if (route.pathname !== "/reference") return "";
      const kind = String(route.searchParams.get("kind") || "")
        .trim().toLowerCase().replaceAll("_", "-");
      if (kind !== "run-spec") return "";
      const target = String(route.searchParams.get("target") || "");
      if (!target) return "";
      const match = /^(?:runspec|run-spec|run_spec):sha256:(.+)$/i.exec(target);
      return `reference-detail:run-spec:${match ? `sha256:${match[1].toLowerCase()}` : target}`;
    }

    function researchReportTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/research\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `research-report:${encodeURIComponent(target)}`;
    }

    function strategyDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/strategies\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `strategy-detail:${encodeURIComponent(target === "new" ? "create" : target)}`;
    }

    function researchIDFromReportPath(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      if (!/^\/research\//.test(pathname)) return "";
      try {
        const origin = location.origin || "http://factortester.invalid";
        return String(new URL(path, origin).searchParams.get("research_id") || "").trim();
      } catch (_) {
        return "";
      }
    }

    function researchDetailTabID(path) {
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const match = /^\/researches\/(.+)$/.exec(pathname);
      if (!match) return "";
      let target = match[1];
      try { target = decodeURIComponent(target); } catch (_) {}
      return `research-detail:${encodeURIComponent(target)}`;
    }

    function detailTabIDForPath(path) {
      return researchDetailTabID(path)
        || researchReportTabID(path)
        || strategyDetailTabID(path)
        || jobDetailTabID(path)
        || productSourceFamilyDetailTabID(path)
        || productCategoryDetailTabID(path)
        || productDetailTabID(path) || factorDetailTabID(path)
        || profileDetailTabID(path) || runSpecTabID(path);
    }

    function navigate(path, navigationOptions = {}) {
      // A missing task URL must not create a new tab.  In particular, an
      // empty href otherwise leaves the browser pathname unchanged while
      // creating a new tab, so the new tab renders the current test
      // workbench again instead of an independent task page.
      path = String(path || "").trim();
      if (!path) return;
      const pathname = String(path || "").split(/[?#]/, 1)[0];
      const options = navigationOptions && typeof navigationOptions === "object"
        ? {...navigationOptions} : {};
      const detailTabID = detailTabIDForPath(path);
      const reportResearchID = detailTabID && researchReportTabID(path)
        ? researchIDFromReportPath(path) : "";
      if (reportResearchID && !options.parentTabID) {
        const parentPath = `/researches/${encodeURIComponent(reportResearchID)}`;
        const parentID = researchDetailTabID(parentPath);
        const parent = state.tabs.find(tab => tab.id === parentID);
        if (!parent) {
          openTab(parentPath, {
            id: parentID,
            title: options.researchTitle || t("研究"),
            closable: true,
            parentFolder: "research",
            parentResearchID: reportResearchID,
          });
        }
        options.parentFolder = "research";
        options.parentTabID = parentID;
        options.parentResearchID = reportResearchID;
      }
      // An overlay owns the source tab.  Any internal navigation initiated
      // from it gets a dedicated tab, including normally pinned feature routes.
      // Stable detail tabs remain deduplicated even when opened from an
      // overlay; ordinary destinations still get an independent tab.
      if (viewCache.activeTabHasOverlay() && !detailTabID) {
        return openTab(path, {
          ...options, forceNew: true, title: options.title || titleForPath(path),
        });
      }
      if (pathname === "/jobs") {
        return openTab(path, {id: "jobs", title: t("测试台"), closable: false});
      }
      if (pathname === "/settings" || pathname.startsWith("/settings/")) {
        return openTab(path, {id: "settings", title: t("设置"), closable: false});
      }
      if (pathname === "/docs" || pathname.startsWith("/docs/")) {
        return openTab(path, {id: "docs", title: t("技术文档"), closable: true});
      }
      if (["/products", "/products/sources", "/products/categories", "/products/groups"]
        .includes(pathname)) {
        return openTab(path, {id: "products", title: t("产品库"), closable: false});
      }
      if (["/factors", "/factors/families", "/factors/sets"].includes(pathname)) {
        return openTab(path, {id: "factors", title: t("因子库"), closable: false});
      }
      if (pathname === "/strategies") {
        return openTab(path, {id: "strategies", title: t("策略库"), closable: false});
      }
      const nativeDetail = Boolean(detailTabID);
      const nativeReference = pathname === "/reference";
      const testConfiguration = pathname === "/ic-test" || pathname === "/backtest";
      if (embeddedPresentation
        && (path.startsWith("/research/") || path.startsWith("/jobs/")
            || path.startsWith("/factor-series") || nativeDetail || nativeReference)
        && !testConfiguration
        && window.webkit?.messageHandlers?.researchNavigation) {
        window.webkit.messageHandlers.researchNavigation.postMessage({path});
        return;
      }
      const tabOptions = {
        ...options,
        id: detailTabID || options.id,
        // Omit the option for ordinary routes. Passing false marks a tab as
        // pinned and hides it from the opened-tab rail, which broke test
        // configuration tabs even though forceNew created distinct entries.
        closable: nativeDetail ? true : undefined,
        forceNew: testConfiguration || path.startsWith("/factor-series")
          || path.startsWith("/docs")
          || path.startsWith("/sqlite-web") || path.startsWith("/manager"),
      };
      if (nativeDetail) tabOptions.closable = true;
      return openTab(path, tabOptions);
    }

    function updateActiveTab(fields) {
      const tab = state.tabs.find(item => item.id === state.activeTabID);
      if (tab) {
        Object.assign(tab, fields); renderOpenedTabs(); checkpointWorkspace();
      }
    }

    function discardViews() {
      // Authentication and language changes alter both page data and the
      // module list.  Cached DOM from the previous session must not be
      // restored after that boundary.
      const tabIDs = new Set([
        "home",
        ...state.tabs.map(tab => tab.id),
        ...state.tabSessions.keys(),
      ]);
      tabIDs.forEach(tabID => viewCache.discardView(tabID));
    }

    function normalizeResearchTabHierarchy() {
      const details = new Set(
        state.tabs.filter(tab => tab.closable && isResearchDetailTab(tab))
          .map(tab => tab.id),
      );
      state.tabs.forEach(tab => {
        if (!tab.closable) {
          delete tab.parentFolder;
          delete tab.parentTabID;
          delete tab.parentResearchID;
          return;
        }
        if (isResearchDetailTab(tab)) {
          // Researches are always direct children of the Research folder;
          // never restore a persisted research-under-research relationship.
          tab.parentFolder = "research";
          delete tab.parentTabID;
          tab.parentResearchID = researchIDForTab(tab);
          return;
        }
        if (tab.parentFolder !== "research") {
          delete tab.parentFolder;
          delete tab.parentTabID;
          delete tab.parentResearchID;
          return;
        }
        if (tab.parentTabID && details.has(tab.parentTabID)) {
          const parent = state.tabs.find(item => item.id === tab.parentTabID);
          tab.parentResearchID = researchIDForTab(parent);
          if (!tab.parentResearchID) {
            delete tab.parentTabID;
            delete tab.parentResearchID;
          }
          return;
        }
        // A tab with an invalid/missing parent remains mounted directly under
        // Research instead of disappearing from the sidebar.
        delete tab.parentTabID;
        delete tab.parentResearchID;
      });
    }

    function initializeTabs(snapshot = null) {
      const defaults = state.modules
        .filter(item => item.pinned && item.id !== "settings")
        .map(item => ({
          id: item.id, path: modulePath(item), title: t(item.title_key || item.title),
          icon: FTIcons.module(item), closable: false,
        }));
      defaults.push({
        id: "settings", path: "/settings", title: t("设置"),
        icon: FTIcons.module("settings"), closable: false,
      });
      const restored = Array.isArray(snapshot?.tabs) ? snapshot.tabs : [];
      const restoredByID = new Map(restored.map(tab => [tab.id, tab]));
      state.tabs = defaults.map(tab => {
        const saved = restoredByID.get(tab.id);
        return saved ? {...tab, path: saved.path || tab.path} : tab;
      });
      const fixedIDs = new Set(state.tabs.map(tab => tab.id));
      restored.filter(tab => tab.closable && !fixedIDs.has(tab.id))
        .forEach(tab => state.tabs.push({...tab, closable: true}));
      normalizeResearchTabHierarchy();
      state.tabs.forEach(tab => viewCache.hydrateSession(tab.id));
      state.activeTabID = state.tabs.some(tab => tab.id === snapshot?.activeTabID)
        ? snapshot.activeTabID : "home";
      renderOpenedTabs();
      checkpointWorkspace();
      return Boolean(snapshot);
    }

    function currentTabContext() {
      return {
        tabID: state.activeTabID,
        tabSession: viewCache.tabSession(state.activeTabID),
        pageState: viewCache.pageState(state.activeTabID),
        pageAgentLifecycle,
      };
    }

    return {
      ...viewCache,
      renderOpenedTabs, activateTab, closeTab, openModule, openTab, navigate,
      updateActiveTab, discardViews, initializeTabs, currentTabContext,
      detailTabIDForPath, researchDetailTabID, checkpointWorkspace, setWorkspace,
      checkpointActiveSession, scheduleActiveSessionCheckpoint,
    };
  }

  window.FTTabs = Object.freeze({create});
})();
