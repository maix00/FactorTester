(() => {
  function localAvailable() {
    return window.FTAppRuntime?.hasLocalCatalog?.() === true;
  }

  function sourceOrder(preferred = "") {
    if (preferred === "server" || !localAvailable()) return ["server"];
    if (preferred === "local") return ["local", "server"];
    return ["local", "server"];
  }

  async function firstAvailable(context, operation, preferred = "") {
    const errors = [];
    for (const source of sourceOrder(preferred)) {
      try {
        const payload = await operation(source);
        if (payload?.success === false) throw new Error(payload.error || "request failed");
        return {payload: payload || {}, source};
      } catch (error) {
        errors.push(error);
      }
    }
    throw errors.at(-1) || new Error(context.t("行情数据暂不可用"));
  }

  function prices(context, request, preferred = "") {
    return firstAvailable(context, source => context.api(
      source === "local" ? "/api/client/product_prices" : "/api/catalog/prices",
      {method: "POST", body: JSON.stringify(request)},
    ), preferred);
  }

  function contracts(context, product, preferred = "") {
    return firstAvailable(context, source => context.api(
      `${source === "local" ? "/api/client/product_contracts" : "/api/catalog/contracts"}`
        + `?product=${encodeURIComponent(product)}`,
    ), preferred);
  }

  window.FTMarketData = Object.freeze({contracts, localAvailable, prices, sourceOrder});
})();
