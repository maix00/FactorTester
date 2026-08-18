(() => {
  function field(manifest, key) {
    const defaults = manifest?.defaults || {};
    if (defaults[key]) return defaults[key];
    return (manifest?.run_fields || []).find(item => item?.key === key) || null;
  }

  function textFor(context, value, fallback = "", options = {}) {
    const raw = value && typeof value === "object"
      ? value.text || value.description || value.desc || value.body
      : value;
    const text = String(raw || "").trim();
    if (text) return context?.t?.(text, text) || text;
    const fallbackText = String(fallback || "").trim();
    if (!fallbackText) return "";
    return options.translateFallback
      ? context?.t?.(fallbackText, fallbackText) || fallbackText
      : fallbackText;
  }

  function forField(manifest, key, context) {
    const keys = Array.isArray(key) ? key : [key];
    const definition = keys.map(candidate => field(manifest, candidate))
      .find(Boolean);
    if (!definition) return "";
    const helpText = textFor(context, definition.help_text);
    const overlay = definition?.info_overlay;
    if (!overlay || typeof overlay !== "object") return helpText;
    if (!helpText && !overlay.content && typeof overlay.render !== "function") {
      return "";
    }
    return {
      ...overlay,
      mode: "overlay",
      title: textFor(context, overlay.title, definition.label || keys[0], {
        translateFallback: true,
      }),
      text: textFor(context, overlay.text || overlay.desc, helpText),
    };
  }

  window.FTTestFieldHelp = Object.freeze({field, forField, textFor});
})();
