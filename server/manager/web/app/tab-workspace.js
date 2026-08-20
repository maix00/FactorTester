(() => {
  const schemaVersion = 1;

  function safePart(value) {
    return encodeURIComponent(String(value || "anonymous"));
  }

  function normalizedTab(tab) {
    if (!tab || !String(tab.id || "") || !String(tab.path || "")) return null;
    return {
      id: String(tab.id),
      path: String(tab.path),
      title: String(tab.title || ""),
      icon: String(tab.icon || ""),
      closable: Boolean(tab.closable),
    };
  }

  function create(options = {}) {
    const storage = options.storage || localStorage;
    const managerKey = String(options.managerKey || location.origin || "manager");
    const principalKey = String(options.principalKey || "anonymous");
    const storageKey = () => (
      `ft-tab-workspace:v${schemaVersion}:${safePart(managerKey)}:${safePart(principalKey)}`
    );

    function remove() {
      try { storage.removeItem(storageKey()); } catch (_) {}
    }

    function restore() {
      let value;
      try {
        const raw = storage.getItem(storageKey());
        if (!raw) return null;
        value = JSON.parse(raw);
      } catch (_) {
        remove();
        return null;
      }
      if (value?.schemaVersion !== schemaVersion || !Array.isArray(value.tabs)) {
        remove();
        return null;
      }
      const tabs = value.tabs.map(normalizedTab).filter(Boolean);
      const activeTabID = String(value.activeTabID || "home");
      return {tabs, activeTabID};
    }

    function save(value = {}) {
      const tabs = (Array.isArray(value.tabs) ? value.tabs : [])
        .map(normalizedTab).filter(Boolean);
      const activeTabID = tabs.some(tab => tab.id === value.activeTabID)
        ? String(value.activeTabID) : "home";
      const payload = {
        schemaVersion,
        updatedAt: Date.now(),
        tabs,
        activeTabID,
      };
      try { storage.setItem(storageKey(), JSON.stringify(payload)); } catch (_) {}
      return payload;
    }

    return Object.freeze({remove, restore, save, storageKey});
  }

  function principalKey(session) {
    const username = String(session?.username || "").trim();
    if (username) return `account:${username}`;
    return session?.visitor ? "visitor" : "anonymous";
  }

  window.FTTabWorkspace = Object.freeze({create, principalKey, schemaVersion});
})();
