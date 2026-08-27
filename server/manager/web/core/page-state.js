(() => {
  const schemaVersion = 1;

  function clone(value) {
    if (value === undefined) return undefined;
    try { return JSON.parse(JSON.stringify(value)); }
    catch (_) { return null; }
  }

  function create(options = {}) {
    const durable = options.durable || {};
    const stored = durable.pageState?.schemaVersion === schemaVersion
      ? durable.pageState : {schemaVersion, sections: {}};
    durable.pageState = stored;
    const registrations = new Map();

    function register(id, adapter = {}) {
      const key = String(id || "").trim();
      if (!key) throw new Error("page state registration requires an id");
      const previous = registrations.get(key);
      if (typeof previous?.capture === "function") {
        stored.sections[key] = clone(previous.capture());
      }
      previous?.dispose?.();
      registrations.set(key, adapter);
      const prior = clone(stored.sections[key]);
      if (prior !== undefined && typeof adapter.restore === "function") {
        adapter.restore(prior);
      }
      return Object.freeze({
        capture,
        unregister: () => registrations.delete(key),
      });
    }

    function capture() {
      registrations.forEach((adapter, key) => {
        if (typeof adapter.capture !== "function") return;
        const value = clone(adapter.capture());
        if (value !== undefined) stored.sections[key] = value;
      });
      options.onChange?.(stored);
      return clone(stored);
    }

    function describe() {
      return {
        schema_version: schemaVersion,
        sections: [...registrations.entries()].flatMap(([id, adapter]) => {
          if (typeof adapter.describe !== "function") return [];
          const value = clone(adapter.describe());
          return value && typeof value === "object" ? [{id, ...value}] : [];
        }),
      };
    }

    function apply(id, action) {
      const adapter = registrations.get(String(id || ""));
      if (!adapter || typeof adapter.apply !== "function") return false;
      const applied = adapter.apply(clone(action));
      if (applied) capture();
      return Boolean(applied);
    }

    function saved(id) {
      return clone(stored.sections[String(id || "")]);
    }

    function dispose() {
      capture();
      registrations.forEach(adapter => adapter.dispose?.());
      registrations.clear();
    }

    return Object.freeze({apply, capture, describe, dispose, register, saved});
  }

  window.FTPageState = Object.freeze({create, schemaVersion});
})();
