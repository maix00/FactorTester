(() => {
  const registrations = new Map();

  function register(name, renderer) {
    if (!name || typeof renderer !== "function") throw new TypeError("invalid applicability editor");
    registrations.set(name, renderer);
  }

  function create(context, state, schema, initial) {
    const root = document.createElement("section");
    root.className = "research-evidence-applicability";
    const nav = document.createElement("nav");
    nav.className = "research-section-tabs";
    const panel = document.createElement("div");
    panel.className = "research-evidence-applicability-fields";
    const controls = new Map();
    const renderSection = sectionID => {
      state.applicabilityTab = sectionID;
      panel.replaceChildren();
      for (const field of schema.fields || []) {
        if (field.exposed === false || field.section !== sectionID) continue;
        const registered = registrations.get(field.registration);
        const entry = registered?.({context, field, value: initial[field.name]});
        if (entry?.element && typeof entry.read === "function") {
          controls.set(field.name, {field, read: entry.read});
          panel.append(entry.element);
          continue;
        }
        const fallback = fallbackField(context, field, initial[field.name]);
        controls.set(field.name, {field, read: fallback.read});
        panel.append(fallback.element);
      }
    };
    for (const section of schema.sections || []) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = context.t(section.label_zh || section.id);
      button.className = `research-section-tab${state.applicabilityTab === section.id ? " active" : ""}`;
      button.addEventListener("click", () => {
        [...nav.children].forEach(item => item.classList.toggle("active", item === button));
        renderSection(section.id);
      });
      nav.append(button);
    }
    renderSection(state.applicabilityTab || schema.sections?.[0]?.id);
    root.append(nav, panel);
    return {root, read: () => {
      const result = structuredClone(initial || {});
      for (const [name, entry] of controls) {
        const value = entry.read();
        if (isEmpty(value)) delete result[name]; else result[name] = value;
      }
      return result;
    }};
  }

  function fallbackField(context, field, initial) {
    const row = document.createElement("label");
    row.className = "research-evidence-applicability-field";
    const title = document.createElement("span");
    title.textContent = context.t(field.label_zh || field.name);
    if (field.type === "time_window") {
      const control = document.createElement("div");
      const start = document.createElement("input");
      const end = document.createElement("input");
      start.type = end.type = "text";
      start.placeholder = context.t("开始（可留空）");
      end.placeholder = context.t("结束（可留空）");
      start.value = initial?.start || "";
      end.value = initial?.end || "";
      control.append(start, end);
      row.append(title, control);
      return {element: row, read: () => ({
        ...(start.value.trim() ? {start: start.value.trim()} : {}),
        ...(end.value.trim() ? {end: end.value.trim()} : {}),
      })};
    }
    const control = document.createElement("textarea");
    control.rows = field.type === "object_array" ? 7 : 3;
    control.value = field.type === "object_array"
      ? JSON.stringify(initial || [], null, 2)
      : field.type === "string_array" ? (initial || []).join("\n") : (initial || "");
    row.append(title, control);
    return {element: row, read: () => {
      if (field.type === "object_array") return JSON.parse(control.value || "[]");
      if (field.type === "string_array") {
        return control.value.split("\n").map(item => item.trim()).filter(Boolean);
      }
      return control.value.trim();
    }};
  }

  function isEmpty(value) {
    if (value == null || value === "") return true;
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === "object") return Object.keys(value).length === 0;
    return false;
  }

  window.FTEvidenceApplicabilityEditor = Object.freeze({create, register});
})();
