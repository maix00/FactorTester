(() => {
  const loaded = new Map();
  const groupLoads = new Map();
  let manifestPromise = null;
  let manifestValue = null;
  let revision = "";
  // Resolved from the manifest: a container that does not serve group bundles
  // keeps loading the declared files one by one.
  let bundlesEnabled = true;
  const BUNDLE_PREFIX = "__group__";

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
    const promise = (async () => {
      const dependencies = value.group_dependencies?.[name] || [];
      for (const dependency of dependencies) {
        await loadGroup(dependency, value, nextStack);
      }
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
