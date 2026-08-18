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

  function choiceItem(context, definition) {
    const formats = (definition.formats || [])
      .map(value => String(value).toUpperCase());
    const sources = (definition.required_sources || []).map(value => (
      context.t(value?.label || value?.name || value)
    ));
    const sourceNote = sources.length
      ? `${context.t("需保留")}：${sources.join("、")}`
      : "";
    return {
      value: definition.name,
      label: context.t(definition.label || definition.name),
      description: [formats.join(" / "), sourceNote].filter(Boolean).join(" · "),
    };
  }

  function fieldValueSelector(context, definitions, selected, update) {
    const filter = FTMultiSelectFilter.create(context, {
      className: "shared-field-value-selector",
      title: context.t("结果与生成物"),
      items: definitions.map(definition => choiceItem(context, definition)),
      selected: Array.isArray(selected) ? selected : [],
      multi: true,
      onChange: values => update([...values]),
    });
    return filter.element;
  }

  window.FTOutputChoices = Object.freeze({
    available, fieldValueSelector, initialSelection,
  });
})();
