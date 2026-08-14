(() => {
  const loaded = new Map();
  const groupLoads = new Map();
  let manifestPromise = null;
  let manifestValue = null;
  let revision = "";

  function assetURL(relative) {
    const query = revision ? `?v=${encodeURIComponent(revision)}` : "";
    return `/research-static/${relative}${query}`;
  }

  async function manifest() {
    if (!manifestPromise) {
      revision = document.querySelector(
        'meta[name="ft-client-assets-revision"]',
      )?.content || "";
      manifestPromise = fetch(assetURL("module-manifest.json"), {
        credentials: "same-origin",
        cache: "no-store",
      }).then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      }).then(value => { manifestValue = value; return value; });
    }
    return manifestPromise;
  }

  function loadScript(relative) {
    if (loaded.has(relative)) return loaded.get(relative);
    const promise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = assetURL(relative);
      script.async = false;
      script.dataset.ftLazyModule = relative;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error(`无法加载模块 ${relative}`));
      document.head.append(script);
    }).catch(error => {
      loaded.delete(relative);
      throw error;
    });
    loaded.set(relative, promise);
    return promise;
  }

  function preloadScripts(relatives) {
    const links = [];
    for (const relative of relatives) {
      if (loaded.has(relative)) continue;
      const link = document.createElement("link");
      link.rel = "preload";
      link.as = "script";
      link.href = assetURL(relative);
      link.dataset.ftLazyPreload = relative;
      document.head.append(link);
      links.push(link);
    }
    return () => links.forEach(link => link.remove());
  }

  async function loadGroup(name, value, stack = new Set()) {
    if (!name) return;
    if (stack.has(name)) {
      throw new Error(`模块依赖形成循环: ${[...stack, name].join(" → ")}`);
    }
    const groupKey = `group:${name}`;
    if (loaded.has(groupKey)) return loaded.get(groupKey);
    if (groupLoads.has(name)) return groupLoads.get(name);
    const nextStack = new Set(stack).add(name);
    const promise = (async () => {
      const dependencies = value.group_dependencies?.[name] || [];
      for (const dependency of dependencies) {
        await loadGroup(dependency, value, nextStack);
      }
      const external = value.group_external_scripts?.[name] || [];
      for (const relative of external) await loadScript(relative);
      const scripts = value.groups?.[name] || [];
      // Dynamic script tags with async=false still fetch in sequence in some
      // WebKit versions.  Preload the whole group first, then execute the
      // original manifest order so global-IIFE dependencies remain unchanged
      // while high-latency connections pay one round of network latency.
      const removePreloads = preloadScripts(scripts);
      try {
        for (const relative of scripts) await loadScript(relative);
      } finally {
        removePreloads();
      }
    })();
    groupLoads.set(name, promise);
    try {
      await promise;
      loaded.set(groupKey, promise);
      return promise;
    } catch (error) {
      groupLoads.delete(name);
      throw error;
    }
  }

  async function loadGroups(names) {
    const value = await manifest();
    for (const name of names || []) await loadGroup(String(name), value);
  }

  function controlDescriptor(template) {
    return manifestValue?.control_groups?.[String(template || "")] || null;
  }

  async function ensureRoute(kind) {
    const value = await manifest();
    await loadGroups(value.route_groups?.[kind] || []);
  }

  // The initial shell contains core and app groups.  Mark those groups as
  // loaded after the synchronous script list has executed so lazy routes do
  // not append them again.
  for (const name of ["core", "app"]) loaded.set(`group:${name}`, Promise.resolve());

  window.FTStaticLoader = Object.freeze({ensureRoute, loadGroups, controlDescriptor});
})();
