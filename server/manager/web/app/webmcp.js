(() => {
  const MAX_TEXT = 12000;
  const MAX_CONTROLS = 160;
  const MAX_FIELDS_PER_CALL = 32;

  const surfaces = Object.freeze([
    {
      id: "home", path: "/", title: "FactorTester home", access: "public",
      cli: ["list", "doctor", "protocol"],
      description: "Discover servers and open FactorTester feature areas.",
    },
    {
      id: "ic_test", path: "/ic-test", title: "IC test workbench", access: "public",
      cli: ["factor-plan", "workspace", "run", "research", "trial-plan"],
      description: "Configure factors, products, horizons and submit IC tests.",
    },
    {
      id: "backtest", path: "/backtest", title: "Backtest workbench", access: "public",
      cli: ["factor-plan", "workspace", "run", "strategy", "margin-budget"],
      description: "Configure strategies and submit factor backtests.",
    },
    {
      id: "jobs", path: "/jobs?section=tasks", title: "Test jobs", access: "public",
      cli: ["job"],
      description: "List jobs, watch progress, inspect inputs, results and artifacts.",
    },
    {
      id: "factor_library", path: "/factors", title: "Factor library", access: "public",
      cli: ["factor-plan", "external-factor", "factor-library"],
      description: "Browse, create and edit factor families, factors and factor sets.",
    },
    {
      id: "product_catalog", path: "/products", title: "Product catalog", access: "public",
      cli: ["products"],
      description: "Browse products, contracts, prices and data sources.",
    },
    {
      id: "product_groups", path: "/products/groups", title: "Product groups", access: "public",
      cli: ["products"],
      description: "Browse and manage saved product groups.",
    },
    {
      id: "product_categories", path: "/products/categories", title: "Product categories", access: "public",
      cli: ["products"],
      description: "Browse and manage product classification trees.",
    },
    {
      id: "research", path: "/research?section=reports", title: "Research reports", access: "public",
      cli: ["research"],
      description: "Inspect research reports, evidence and agent workflow outputs.",
    },
    {
      id: "research_graph", path: "/research?section=graph", title: "Research graph", access: "authenticated",
      cli: ["research"],
      description: "Inspect and advance the research decision graph.",
    },
    {
      id: "profiles", path: "/research?section=profiles", title: "Research profiles", access: "authenticated",
      cli: ["research", "agents"],
      description: "Manage research identities, agents, skills and conversations.",
    },
    {
      id: "test_templates", path: "/test-templates", title: "Test templates", access: "authenticated",
      cli: ["describe", "edit", "workspace"],
      description: "Manage reusable test configuration templates.",
    },
    {
      id: "account_settings", path: "/settings/account", title: "Account settings", access: "public",
      cli: ["configure", "login", "logout", "client"],
      description: "Manage the current account, language and client preferences.",
    },
    {
      id: "manager_accounts", path: "/manager?section=accounts", title: "User hierarchy", access: "admin",
      cli: [], web_only: ["organizations", "levels", "subordinates", "user_roles"],
      description: "Manage organizations, levels, users, parents and subordinates.",
    },
    {
      id: "manager_services", path: "/manager?section=services", title: "Server services", access: "super_admin",
      cli: [], web_only: ["service_controls", "global_job_queue"],
      description: "Inspect and control authorized Manager services.",
    },
    {
      id: "manager_devices", path: "/manager?section=devices", title: "Devices", access: "super_admin",
      cli: [], web_only: ["device_authorization", "visitor_allowlist"],
      description: "Manage authorized devices and visitor access.",
    },
    {
      id: "technical_docs", path: "/docs", title: "Technical documentation", access: "public",
      cli: ["protocol"],
      description: "Read FactorTester technical and protocol documentation.",
    },
  ]);

  const surfaceByID = new Map(surfaces.map(item => [item.id, item]));

  function clipped(value, limit = MAX_TEXT) {
    const text = String(value ?? "").replace(/\s+/g, " ").trim();
    return text.length > limit ? `${text.slice(0, limit)}…` : text;
  }

  function visible(element) {
    if (!element || element.disabled || element.hidden) return false;
    if (element.getAttribute?.("aria-hidden") === "true") return false;
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      if (node.hidden || node.getAttribute?.("aria-hidden") === "true") return false;
      const style = node.style || {};
      if (style.display === "none" || style.visibility === "hidden") return false;
    }
    return true;
  }

  function labelFor(element) {
    const labelledBy = element.getAttribute?.("aria-labelledby");
    const labelled = labelledBy && document.getElementById(labelledBy)?.textContent;
    const wrapping = element.closest?.("label")?.textContent;
    const explicit = element.id
      ? document.querySelector?.(`label[for="${window.CSS?.escape ? window.CSS.escape(element.id) : element.id}"]`)?.textContent
      : "";
    return clipped(
      element.getAttribute?.("aria-label") || labelled || explicit || wrapping
      || element.getAttribute?.("placeholder") || element.name || element.textContent,
      240,
    );
  }

  function typeFor(element) {
    if (element.matches?.("select")) return element.multiple ? "multi-select" : "select";
    if (element.matches?.("textarea")) return "textarea";
    if (element.matches?.("[contenteditable=true]")) return "rich-text";
    return String(element.type || element.getAttribute?.("role") || element.tagName || "control").toLowerCase();
  }

  function waitForPaint(signal) {
    if (signal?.aborted) return Promise.reject(signal.reason || new DOMException("Aborted", "AbortError"));
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        signal?.removeEventListener?.("abort", abort);
        resolve();
      };
      const abort = () => {
        if (settled) return;
        settled = true;
        reject(signal.reason || new DOMException("Aborted", "AbortError"));
      };
      signal?.addEventListener?.("abort", abort, {once: true});
      const raf = window.requestAnimationFrame || (callback => setTimeout(callback, 0));
      raf(() => raf(finish));
      setTimeout(finish, 350);
    });
  }

  function createRegistry(root) {
    let fields = new Map();
    let actions = new Map();

    function interactiveControls() {
      const selector = "input, select, textarea, [contenteditable=true], button, [role=button], a[href]";
      const owners = [
        root,
        ...[...(document.querySelectorAll?.("dialog[open], [role=dialog][aria-modal=true]") || [])]
          .filter(owner => !root.contains?.(owner)),
      ];
      return [...new Set(owners.flatMap(owner => [...owner.querySelectorAll(selector)]))];
    }

    function inspect(includeText = true) {
      fields = new Map();
      actions = new Map();
      const fieldRows = [];
      const actionRows = [];
      const controls = interactiveControls().filter(visible).slice(0, MAX_CONTROLS);
      controls.forEach(element => {
        const isField = element.matches("input, select, textarea, [contenteditable=true]")
          && !["button", "submit", "reset", "hidden"].includes(String(element.type || "").toLowerCase());
        if (isField) {
          const id = `field-${fieldRows.length + 1}`;
          fields.set(id, element);
          const sensitive = String(element.type || "").toLowerCase() === "password";
          const row = {
            id, label: labelFor(element), type: typeFor(element),
            name: clipped(element.name || "", 120), required: Boolean(element.required),
            disabled: Boolean(element.disabled), sensitive,
          };
          if (!sensitive) {
            row.value = element.type === "checkbox" || element.type === "radio"
              ? Boolean(element.checked) : clipped(element.value ?? element.textContent ?? "", 1000);
          }
          if (element.matches("select")) {
            row.options = [...element.options].slice(0, 50).map(option => ({
              value: clipped(option.value, 240), label: clipped(option.textContent, 240),
              selected: Boolean(option.selected), disabled: Boolean(option.disabled),
            }));
          }
          fieldRows.push(row);
          return;
        }
        const id = `action-${actionRows.length + 1}`;
        actions.set(id, element);
        actionRows.push({
          id, label: labelFor(element), type: typeFor(element),
          disabled: Boolean(element.disabled),
          href: element.matches("a[href]") ? clipped(element.getAttribute("href"), 500) : undefined,
        });
      });
      return {
        path: `${location.pathname}${location.search}`,
        title: clipped(document.querySelector("#page-title")?.textContent || document.title, 240),
        fields: fieldRows,
        actions: actionRows,
        ...(includeText ? {text: clipped(root.innerText || root.textContent || "")} : {}),
        truncated: controls.length >= MAX_CONTROLS,
      };
    }

    function setValue(element, value) {
      if (!visible(element)) throw new Error("field is no longer visible; inspect the surface again");
      if (element.disabled) throw new Error("field is disabled");
      const type = String(element.type || "").toLowerCase();
      if (type === "checkbox" || type === "radio") {
        element.checked = Boolean(value);
      } else if (element.matches("select[multiple]")) {
        const selected = new Set(Array.isArray(value) ? value.map(String) : [String(value)]);
        [...element.options].forEach(option => { option.selected = selected.has(option.value); });
      } else if (element.matches("select")) {
        element.value = String(value ?? "");
        if (element.value !== String(value ?? "")) throw new Error(`unknown option: ${value}`);
      } else if (element.matches("[contenteditable=true]")) {
        element.textContent = String(value ?? "").slice(0, 8192);
      } else {
        element.value = String(value ?? "").slice(0, 8192);
      }
      element.dispatchEvent(new Event("input", {bubbles: true}));
      element.dispatchEvent(new Event("change", {bubbles: true}));
    }

    return {
      inspect,
      fill(values) {
        const entries = Object.entries(values || {});
        if (entries.length > MAX_FIELDS_PER_CALL) throw new Error("too many fields in one call");
        const changed = [];
        entries.forEach(([id, value]) => {
          const element = fields.get(id);
          if (!element) throw new Error(`unknown field id: ${id}; inspect the surface again`);
          setValue(element, value);
          changed.push({id, label: labelFor(element)});
        });
        return changed;
      },
      activate(id) {
        const element = actions.get(id);
        if (!element) throw new Error(`unknown action id: ${id}; inspect the surface again`);
        if (!visible(element)) throw new Error("action is no longer visible; inspect the surface again");
        if (element.matches("a[href]")) {
          const target = new URL(element.href, location.href);
          if (target.origin !== location.origin) throw new Error("external links cannot be activated through WebMCP");
        }
        element.click();
        return {id, label: labelFor(element)};
      },
    };
  }

  function bind({navigate, root, session}) {
    const context = document.modelContext;
    if (!context?.registerTool || !root) return {supported: false, tools: []};
    const registry = createRegistry(root);
    const toolNames = [];
    const register = tool => {
      context.registerTool(tool);
      toolNames.push(tool.name);
    };

    register({
      name: "factortester_capabilities",
      title: "FactorTester capabilities",
      description: "List FactorTester Web surfaces, their matching CLI command families, Web-only operations and access requirements.",
      inputSchema: {
        type: "object", additionalProperties: false,
        properties: {query: {type: "string", maxLength: 120}},
      },
      annotations: {readOnlyHint: true},
      execute: async ({query = ""} = {}) => {
        const needle = String(query).trim().toLowerCase();
        const items = surfaces.filter(item => !needle || JSON.stringify(item).toLowerCase().includes(needle));
        return {authenticated: Boolean(session?.()), role: session?.()?.role || "visitor", surfaces: items};
      },
    });
    register({
      name: "factortester_open_surface",
      title: "Open FactorTester surface",
      description: "Open a known FactorTester Web feature in the visible application. Use capabilities first to choose a surface.",
      inputSchema: {
        type: "object", additionalProperties: false, required: ["surface"],
        properties: {surface: {type: "string", enum: surfaces.map(item => item.id)}},
      },
      execute: async ({surface}, options = {}) => {
        const target = surfaceByID.get(String(surface));
        if (!target) throw new Error(`unknown surface: ${surface}`);
        navigate(target.path);
        await waitForPaint(options.signal);
        return {surface: target, view: registry.inspect(false)};
      },
    });
    register({
      name: "factortester_inspect_surface",
      title: "Inspect FactorTester surface",
      description: "Read the visible FactorTester page and return bounded field/action identifiers for subsequent UI operations. Password values are never returned.",
      inputSchema: {
        type: "object", additionalProperties: false,
        properties: {include_text: {type: "boolean", default: true}},
      },
      annotations: {readOnlyHint: true, untrustedContentHint: true},
      execute: async ({include_text = true} = {}) => registry.inspect(include_text),
    });
    register({
      name: "factortester_fill_form",
      title: "Fill FactorTester form",
      description: "Fill visible fields using identifiers from factortester_inspect_surface. This updates the same form shown to the user and does not submit it.",
      inputSchema: {
        type: "object", additionalProperties: false, required: ["fields"],
        properties: {
          fields: {
            type: "object", maxProperties: MAX_FIELDS_PER_CALL,
            additionalProperties: {type: ["string", "number", "boolean", "array", "null"]},
          },
        },
      },
      execute: async ({fields}) => ({changed: registry.fill(fields), view: registry.inspect(false)}),
    });
    register({
      name: "factortester_activate",
      title: "Activate FactorTester action",
      description: "Click one visible action from factortester_inspect_surface. This can submit tests or change server data, so confirmed must be true.",
      inputSchema: {
        type: "object", additionalProperties: false, required: ["action", "confirmed"],
        properties: {
          action: {type: "string", pattern: "^action-[1-9][0-9]*$", maxLength: 32},
          confirmed: {type: "boolean", const: true},
        },
      },
      execute: async ({action, confirmed}, options = {}) => {
        if (confirmed !== true) throw new Error("confirmed must be true before activating an action");
        const activated = registry.activate(action);
        await waitForPaint(options.signal);
        return {activated, view: registry.inspect(false)};
      },
    });
    return {supported: true, tools: toolNames};
  }

  window.FTWebMCP = Object.freeze({bind, surfaces});
})();
