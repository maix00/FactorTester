// type-filter.js — embedded candidate-type filter for the shared picker.
// A funnel button next to the search box opens this single/multi type
// chooser; it only narrows which candidates are shown, never the selection.
(() => {
  "use strict";

  let typeSequence = 0;

  function create(context, spec, onChanged) {
    const panel = document.createElement("div");
    panel.className = "ft-multi-select-type-panel";
    panel.hidden = true;
    const entries = Array.isArray(spec?.items) ? spec.items : [];
    const multi = spec?.multi !== false;
    const typeOf = typeof spec?.typeOf === "function"
      ? spec.typeOf : item => String(item?.type || item?.kind || "").trim();
    const active = new Set();
    const list = document.createElement("div");
    list.className = "ft-multi-select-type-options";
    const apply = value => {
      if (multi) {
        if (active.has(value)) active.delete(value); else active.add(value);
      } else {
        active.clear();
        if (value) active.add(value);
      }
      onChanged?.();
    };
    const refresh = () => {
      list.replaceChildren();
      const options = multi ? entries : [{value: "", label: spec.allLabel || "全部"}, ...entries];
      const groupName = `ft-type-filter-${++typeSequence}`;
      for (const entry of options) {
        const label = document.createElement("label");
        label.className = "ft-multi-select-option";
        label.setAttribute("aria-label", entry.label);
        const input = document.createElement("input");
        input.type = multi ? "checkbox" : "radio";
        input.name = groupName;
        input.checked = entry.value !== "" && active.has(entry.value);
        input.addEventListener("change", () => { apply(entry.value); });
        const text = document.createElement("span");
        text.textContent = entry.label;
        label.append(input, text);
        list.append(label);
      }
    };
    refresh();
    panel.append(list);
    return {
      panel,
      toggle: () => { panel.hidden = !panel.hidden; },
      visible: item => {
        if (!active.size) return true;
        return active.has(typeOf(item));
      },
      refresh,
    };
  }

  window.FTMultiSelectTypeFilter = Object.freeze({create});
})();
