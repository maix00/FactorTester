(() => {
  const scopes = ["mine", "subordinates", "shared", "all"];

  function path(ref, suffix = "") {
    return `/api/strategy-library/strategies/${encodeURIComponent(String(ref || ""))}${suffix}`;
  }

  function request(context, url, options) {
    return context.api(url, options);
  }

  async function list(context, options = {}) {
    const params = new URLSearchParams({
      scope: scopes.includes(options.scope) ? options.scope : "mine",
      page: String(Math.max(1, Number(options.page) || 1)),
      limit: String(Math.min(100, Math.max(1, Number(options.limit) || 20))),
    });
    if (String(options.query || "").trim()) params.set("query", String(options.query).trim());
    return request(context, `/api/strategy-library/strategies?${params}`);
  }

  async function search(context, query = "") {
    const value = await list(context, {
      scope: "all", page: 1, limit: 40, query,
    });
    return Array.isArray(value?.items) ? value.items : [];
  }

  function withSource(url, includeSource) {
    if (includeSource === undefined) return url;
    return `${url}?include_source=${includeSource ? "1" : "0"}`;
  }

  function get(context, ref, options = {}) {
    return request(context, withSource(path(ref), options.includeSource));
  }

  function getRevision(context, ref, revisionRef, options = {}) {
    return request(
      context,
      withSource(path(ref, `/revisions/${encodeURIComponent(revisionRef)}`), options.includeSource),
    );
  }

  function create(context, payload) {
    return request(context, "/api/strategy-library/strategies", {
      method: "POST", body: JSON.stringify(payload),
    });
  }

  function update(context, ref, payload) {
    return request(context, path(ref), {
      method: "PATCH", body: JSON.stringify(payload),
    });
  }

  function remove(context, ref) {
    return request(context, path(ref), {method: "DELETE"});
  }

  function shares(context, ref) {
    return request(context, path(ref, "/shares"));
  }

  function grant(context, ref, principalRef) {
    return request(context, path(ref, "/shares"), {
      method: "POST", body: JSON.stringify({principal_ref: principalRef}),
    });
  }

  function revoke(context, ref, principalRef) {
    return request(context, path(ref, `/shares/${encodeURIComponent(principalRef)}`), {
      method: "DELETE",
    });
  }

  window.FTStrategyLibraryRuntime = Object.freeze({
    create, get, getRevision, grant, list, remove, revoke, search, shares, update,
  });
})();
