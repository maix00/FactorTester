(() => {
  function unwrap(value) {
    let current = value;
    for (let index = 0; index < 3; index += 1) {
      const nested = current?.result || current?.payload;
      if (!nested || typeof nested !== "object" || Array.isArray(nested)) break;
      current = nested;
    }
    return current && typeof current === "object" ? current : {};
  }

  function build(value) {
    const payload = unwrap(value);
    const series = (Array.isArray(payload.series) ? payload.series : [])
      .filter(item => item && Array.isArray(item.dates) && Array.isArray(item.values));
    return {
      payload,
      factor: payload.factor || {},
      series,
      products: Array.isArray(payload.products) ? payload.products : [],
      meta: payload.meta || {},
    };
  }

  function identity(item) {
    return String(item?.product || item?.name || item?.code || "");
  }

  function label(item) {
    const name = identity(item);
    const desc = String(item?.desc || "");
    return desc && desc !== name ? `${name} · ${desc}` : name;
  }

  function points(item, minimum, maximum) {
    const dates = Array.isArray(item?.dates) ? item.dates : [];
    const values = Array.isArray(item?.values) ? item.values : [];
    return values.flatMap((value, index) => {
      const time = window.FTPriceChart?.timestampOf(dates[index]);
      const number = Number(value);
      const inRange = (!Number.isFinite(Number(minimum)) || time >= Number(minimum))
        && (!Number.isFinite(Number(maximum)) || time <= Number(maximum));
      return Number.isFinite(time) && Number.isFinite(number) && inRange
        ? [[time, number]] : [];
    });
  }

  function settings(configuration) {
    const root = configuration?.configuration?.payload || configuration?.payload
      || configuration || {};
    const analysis = root.analyses?.factor_evaluation
      || root.factor_evaluation || root.analysis || root;
    return {...analysis, ...(analysis.execution?.settings || {})};
  }

  function priceRequest(configuration, product, fallbackFrequency = "DAY1") {
    const values = settings(configuration);
    return {
      product_name: product,
      freq: values.frequency || fallbackFrequency || "DAY1",
      adjusted: String(values.price_type || "adjusted") === "adjusted",
      start_date: values.start_date || undefined,
      end_date: values.end_date || undefined,
    };
  }

  window.FTFactorSeriesModel = Object.freeze({build, identity, label, points, priceRequest});
})();
