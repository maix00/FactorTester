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
        if (payload?.success === false) {
          throw new Error(payload.error || context.t("请求失败"));
        }
        return {payload: payload || {}, source};
      } catch (error) {
        errors.push(error);
      }
    }
    throw errors.at(-1) || new Error(context.t("行情数据暂不可用"));
  }

  function prices(context, request, preferred = "") {
    return firstAvailable(context, source => context.api(
      source === "local" ? "/api/client/product_prices" : "/api/market-data/prices",
      {method: "POST", body: JSON.stringify(request)},
    ), preferred);
  }

  function rangeRequest(request, minimum, maximum, maximumPoints) {
    const payload = {...(request || {})};
    const applyBound = (prefix, value) => {
      if (!Number.isFinite(Number(value))) return;
      const date = new Date(Number(value));
      const pad = item => String(item).padStart(2, "0");
      payload[`${prefix}_date`] = `${date.getFullYear()}-${pad(date.getMonth() + 1)}`
        + `-${pad(date.getDate())}`;
      payload[`${prefix}_time`] = `${pad(date.getHours())}:${pad(date.getMinutes())}`
        + `:${pad(date.getSeconds())}`;
    };
    applyBound("start", minimum);
    applyBound("end", maximum);
    payload.max_points = Math.max(100, Number(maximumPoints) || 1200);
    return payload;
  }

  function rangeContextMs(frequency) {
    const value = String(frequency || "").toUpperCase();
    return /^(MIN|HOUR)/.test(value) ? 7 * 24 * 60 * 60 * 1000 : 0;
  }

  function contracts(context, product, preferred = "") {
    return firstAvailable(context, source => context.api(
      `${source === "local" ? "/api/client/product_contracts" : "/api/product-library/contracts"}`
        + `?product=${encodeURIComponent(product)}`,
    ), preferred);
  }

  window.FTMarketData = Object.freeze({
    contracts, localAvailable, prices, rangeContextMs, rangeRequest, sourceOrder,
  });
})();
