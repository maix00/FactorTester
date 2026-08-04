(() => {
  const state = {locale: "zh-Hans", strings: {}};

  function browserLocale() {
    return String(navigator.language || "zh-Hans").toLowerCase().startsWith("en")
      ? "en" : "zh-Hans";
  }

  function resolvedLocale(value) {
    if (value === "en" || value === "zh-Hans") return value;
    return browserLocale();
  }

  async function load(preference = "system") {
    const locale = resolvedLocale(preference);
    const response = await fetch(`/api/localizations/${encodeURIComponent(locale)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const value = await response.json();
    state.locale = value.locale || locale;
    state.strings = value.strings || {};
    document.documentElement.lang = state.locale;
    return state.locale;
  }

  function t(key, fallback = key) {
    return state.strings[key] || fallback;
  }

  function format(key, ...values) {
    let index = 0;
    return t(key).replace(/%@|%lld|%ld|%d/g, () => String(values[index++] ?? ""));
  }

  window.FTI18n = {browserLocale, format, load, resolvedLocale, t};
})();
