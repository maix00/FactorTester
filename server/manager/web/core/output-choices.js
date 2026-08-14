(() => {
  function available(capabilities, analysis, phase = "before_run") {
    return (capabilities || []).filter(item => (
      item?.[phase] === true
      && (!Array.isArray(item.analyses) || item.analyses.includes(analysis))
    ));
  }

  function initialSelection(capabilities, analysis, saved, phase = "before_run") {
    const definitions = available(capabilities, analysis, phase);
    const allowed = new Set(definitions.map(item => item.name));
    const requested = Array.isArray(saved)
      ? saved : definitions.filter(item => item.default).map(item => item.name);
    return [...new Set(requested.filter(item => allowed.has(item)))];
  }

  function fieldValueSelector(context, definitions, selected, update) {
    const shell = document.createElement("div");
    shell.className = "shared-field-value-selector";
    shell.append(choices(context, definitions, selected, update));
    return shell;
  }

  function choices(context, definitions, selected, update) {
    const grid = document.createElement("div");
    grid.className = "output-choice-grid";
    const active = new Set(selected || []);
    definitions.forEach(definition => {
      const row = document.createElement("label");
      row.className = "output-choice";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = active.has(definition.name);
      const copy = document.createElement("span");
      const title = document.createElement("b");
      title.textContent = context.t(definition.label || definition.name);
      const detail = document.createElement("small");
      const formats = (definition.formats || []).map(value => String(value).toUpperCase());
      const sources = (definition.required_sources || []).map(value => (
        context.t(value.label || value.name)
      ));
      const sourceNote = sources.length
        ? `${context.t("需保留")}：${sources.join("、")}`
        : "";
      detail.textContent = [formats.join(" / "), sourceNote]
        .filter(Boolean)
        .join(" · ");
      copy.append(title, detail);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) active.add(definition.name);
        else active.delete(definition.name);
        update([...active]);
      });
      row.append(checkbox, copy);
      grid.append(row);
    });
    return grid;
  }

  window.FTOutputChoices = Object.freeze({
    available, choices, fieldValueSelector, initialSelection,
  });
})();
