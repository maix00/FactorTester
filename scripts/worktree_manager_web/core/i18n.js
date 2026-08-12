(() => {
  const state = {locale: "zh-Hans", strings: {}};
  const preferenceKey = "ft-language";

  function browserLocale() {
    return String(navigator.language || "zh-Hans").toLowerCase().startsWith("en")
      ? "en" : "zh-Hans";
  }

  function resolvedLocale(value) {
    if (value === "en" || value === "zh-Hans") return value;
    return browserLocale();
  }

  function choosePreference(explicit, remote, cached) {
    return explicit || remote || cached || "system";
  }

  function storedPreference() {
    try { return localStorage.getItem(preferenceKey) || ""; }
    catch (_) { return ""; }
  }

  function rememberPreference(value) {
    if (!value) return;
    try { localStorage.setItem(preferenceKey, value); }
    catch (_) {}
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

  window.FTI18n = {
    browserLocale, choosePreference, format, load, rememberPreference,
    resolvedLocale, storedPreference, t,
  };
})();
