(() => {
  const cache = new Map();
  async function load(context, path) {
    if (!cache.has(path)) cache.set(path, context.api(path).catch(error => {
      cache.delete(path);
      throw error;
    }));
    return cache.get(path);
  }
  window.FTDocsSource = Object.freeze({
    index: context => load(context, "/api/docs/index"),
    page: (context, slug) => load(context, `/api/docs/pages/${encodeURIComponent(slug)}`),
  });
})();
