(() => {
  const loaded = new Map();
  const loadedStyles = new Map();
  const groupLoads = new Map();
  let manifestPromise = null;
  let manifestValue = null;
  let revision = "";
  // Resolved from the manifest: a container that does not serve group bundles
  // keeps loading the declared files one by one.
  let bundlesEnabled = true;
  let groupSetBundlesEnabled = false;
  const BUNDLE_PREFIX = "__group__";
  const GROUP_SET_PREFIX = "__groups__";

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
      }).then(value => {
        manifestValue = value;
        bundlesEnabled = value?.group_bundles !== false;
        groupSetBundlesEnabled = value?.group_set_bundles === true;
        return value;
      });
    }
    return manifestPromise;
  }

  function loadScript(relative) {
    if (loaded.has(relative)) return loaded.get(relative);
    const promise = (async () => {
      let lastError;
      // A freshly activated container can briefly close an existing browser's
      // first static request.  Retry within this user action so feature
      // overlays do not require a second click to finish loading their group.
      const retryDelays = [0, 100, 250, 500, 1000];
      for (let attempt = 0; attempt < retryDelays.length; attempt += 1) {
        if (retryDelays[attempt]) {
          await new Promise(resolve => setTimeout(resolve, retryDelays[attempt]));
        }
        try {
          await new Promise((resolve, reject) => {
            const script = document.createElement("script");
            const base = assetURL(relative);
            script.src = attempt
              ? `${base}${base.includes("?") ? "&" : "?"}retry=${attempt}`
              : base;
            script.async = false;
            script.dataset.ftLazyModule = relative;
            script.onload = () => resolve();
            script.onerror = () => {
              script.remove();
              reject(new Error(`无法加载模块 ${relative}`));
            };
            document.head.append(script);
          });
          return;
        } catch (error) {
          lastError = error;
        }
      }
      throw lastError;
    })().catch(error => {
      loaded.delete(relative);
      throw error;
    });
    loaded.set(relative, promise);
    return promise;
  }

  function loadStyle(relative) {
    if (loadedStyles.has(relative)) return loadedStyles.get(relative);
    const promise = new Promise((resolve, reject) => {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = assetURL(relative);
      link.dataset.ftLazyStyle = relative;
      link.onload = () => resolve();
      link.onerror = () => {
        link.remove();
        reject(new Error(`无法加载样式 ${relative}`));
      };
      document.head.append(link);
    }).catch(error => {
      loadedStyles.delete(relative);
      throw error;
    });
    loadedStyles.set(relative, promise);
    return promise;
  }

  function loadGroupStyles(name, value) {
    const styles = value.group_styles?.[name] || [];
    return Promise.all(styles.map(loadStyle));
  }

  function orderedGroups(names, value) {
    const groups = value.groups || {};
    const result = [];
    const visited = new Set();
    const visiting = new Set();
    function visit(rawName) {
      const name = String(rawName || "").trim();
      if (!name) return;
      if (visited.has(name)) return;
      if (visiting.has(name)) {
        throw new Error(`模块依赖形成循环: ${[...visiting, name].join(" → ")}`);
      }
      if (!Object.prototype.hasOwnProperty.call(groups, name)) {
        throw new Error(`模块组未声明: ${name}`);
      }
      visiting.add(name);
      for (const dependency of value.group_dependencies?.[name] || []) {
        visit(dependency);
      }
      visiting.delete(name);
      visited.add(name);
      result.push(name);
    }
    for (const name of names || []) visit(name);
    return result;
  }

  async function loadScripts(name, value) {
    const scripts = value.groups?.[name] || [];
    if (!scripts.length) return;
    if (bundlesEnabled) {
      try {
        // One request for the whole group instead of one per module.
        await loadScript(`${BUNDLE_PREFIX}/${name}`);
        return;
      } catch (error) {
        // A container that predates group bundles still serves the declared
        // files, so a route is never blocked by a missing bundle.
        bundlesEnabled = false;
      }
    }
    // Keep fetching and evaluation on one ordered script path. WebKit can
    // lose the dynamic script's load event when an identical preload link
    // wins the fetch race, leaving the group Promise pending forever even
    // though the server returned both assets successfully.
    for (const relative of scripts) await loadScript(relative);
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
    const stylesPromise = loadGroupStyles(name, value);
    const promise = (async () => {
      const dependencies = value.group_dependencies?.[name] || [];
      for (const dependency of dependencies) {
        await loadGroup(dependency, value, nextStack);
      }
      await stylesPromise;
      const external = value.group_external_scripts?.[name] || [];
      for (const relative of external) await loadScript(relative);
      await loadScripts(name, value);
    })();
    groupLoads.set(name, promise);
    try {
      await promise;
      loaded.set(groupKey, promise);
      return promise;
    } catch (error) {
      throw error;
    } finally {
      if (groupLoads.get(name) === promise) groupLoads.delete(name);
    }
  }

  async function loadGroupsLegacy(names, value) {
    for (const name of names || []) await loadGroup(String(name), value);
  }

  async function loadGroups(names) {
    const value = await manifest();
    const order = orderedGroups(names, value);
    if (!order.length) return;
    const stylesPromise = Promise.all(order.map(name => loadGroupStyles(name, value)));

    const pendingGroups = order
      .map(name => groupLoads.get(name))
      .filter(Boolean);
    if (pendingGroups.length) {
      await Promise.all(pendingGroups);
      await stylesPromise;
      return loadGroups(names);
    }

    // A combined first-party bundle can succeed while one of its vendor
    // scripts fails. Keep that route retryable by settling missing vendors
    // even after the first-party groups have been marked as loaded.
    const externalScripts = [...new Set(order.flatMap(name =>
      value.group_external_scripts?.[name] || []
    ))].filter(relative => !loaded.has(relative));
    const missing = order.filter(name => !loaded.has(`group:${name}`));
    if (!missing.length) {
      await stylesPromise;
      await Promise.all(externalScripts.map(loadScript));
      return;
    }

    if (!groupSetBundlesEnabled || !bundlesEnabled) {
      await stylesPromise;
      return loadGroupsLegacy(names, value);
    }

    const bundleGroups = missing.filter(name => (value.groups?.[name] || []).length);
    const emptyGroups = missing.filter(name => !bundleGroups.includes(name));
    for (const name of emptyGroups) loaded.set(`group:${name}`, Promise.resolve());

    const externalLoads = externalScripts.map(loadScript);
    const bundleLoad = bundleGroups.length
      ? loadScript(`${GROUP_SET_PREFIX}/${bundleGroups.join(",")}`)
      : Promise.resolve();
    const operation = (async () => {
      const scriptResults = await Promise.allSettled([...externalLoads, bundleLoad]);
      const bundleResult = scriptResults[scriptResults.length - 1];
      const firstRejected = scriptResults.find(result => result.status === "rejected");
      if (bundleGroups.length && bundleResult.status === "rejected") {
        for (const name of missing) {
          if (groupLoads.get(name) === operation) groupLoads.delete(name);
        }
        await stylesPromise;
        groupSetBundlesEnabled = false;
        return loadGroupsLegacy(names, value);
      }
      for (const name of bundleGroups) loaded.set(`group:${name}`, bundleLoad);
      for (const name of emptyGroups) loaded.set(`group:${name}`, Promise.resolve());
      if (firstRejected) throw firstRejected.reason;
      await stylesPromise;
    })();
    for (const name of missing) groupLoads.set(name, operation);
    try {
      await operation;
    } finally {
      for (const name of missing) {
        if (groupLoads.get(name) === operation) groupLoads.delete(name);
      }
    }
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
