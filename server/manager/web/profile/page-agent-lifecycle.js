(() => {
  function create(options = {}) {
    const profiles = new Map();

    function entry(profileID) {
      const key = String(profileID || "").trim();
      if (!key) throw new Error("page Agent requires a profile id");
      if (!profiles.has(key)) {
        profiles.set(key, {profileID: key, owners: new Set(), startPromise: null});
      }
      return profiles.get(key);
    }

    async function open(profileID, tabID) {
      const item = entry(profileID);
      const owner = String(tabID || "").trim();
      if (!owner) throw new Error("page Agent requires a tab id");
      item.owners.add(owner);
      if (!item.startPromise) {
        item.startPromise = Promise.resolve(options.start?.(item.profileID));
      }
      try { await item.startPromise; }
      catch (error) {
        item.owners.delete(owner);
        if (!item.owners.size) profiles.delete(item.profileID);
        throw error;
      }
      return {profileID: item.profileID, tabID: owner};
    }

    function hide() {
      // Visibility is deliberately independent from runtime ownership.
    }

    async function evict(tabID) {
      const owner = String(tabID || "").trim();
      const stops = [];
      profiles.forEach((item, profileID) => {
        if (!item.owners.delete(owner) || item.owners.size) return;
        profiles.delete(profileID);
        stops.push(Promise.resolve(item.startPromise).catch(() => {}).then(
          () => options.stop?.(profileID),
        ));
      });
      await Promise.all(stops);
    }

    function owners(profileID) {
      return [...(profiles.get(String(profileID || ""))?.owners || [])];
    }

    return Object.freeze({evict, hide, open, owners});
  }

  window.FTPageAgentLifecycle = Object.freeze({create});
})();
