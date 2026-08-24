(() => {
  function replaceVisibleSeries(chart, nextOptions, minimum, maximum) {
    const definitions = Array.isArray(nextOptions?.series) ? nextOptions.series : [];
    const visible = chart.series.filter(series => !series.options?.isInternal);
    const remaining = new Set(visible);
    definitions.forEach((definition, index) => {
      const identity = String(definition.id || definition.name || index);
      const current = visible.find((series, seriesIndex) => (
        remaining.has(series)
        && String(series.options?.id || series.name || seriesIndex) === identity
      ));
      if (!current) { chart.addSeries(definition, false); return; }
      remaining.delete(current);
      const {data, ...presentation} = definition;
      current.update(presentation, false);
      current.setData(data || [], false, false, false);
    });
    remaining.forEach(series => series.remove(false));
    chart.xAxis[0]?.setExtremes(
      Number.isFinite(minimum) ? minimum : undefined,
      Number.isFinite(maximum) ? maximum : undefined,
      false, false, {trigger: "ft-data-refresh"},
    );
    chart.redraw(false);
  }

  function attach(options, displayOptions = {}) {
    if (typeof displayOptions.loadRange !== "function"
        || typeof displayOptions.rangeOptions !== "function") return options;
    options.rangeSelector = {
      ...(options.rangeSelector || {}), allButtonsEnabled: true,
    };
    const overviewData = options.series?.[0]?.data;
    options.navigator = {
      ...(options.navigator || {}), adaptToUpdatedData: false,
      ...(Array.isArray(overviewData) ? {series: {
        ...(options.navigator?.series || {}), data: overviewData,
      }} : {}),
    };
    options.xAxis = options.xAxis || {};
    const previous = options.xAxis.events?.afterSetExtremes;
    options.xAxis.events = {...(options.xAxis.events || {}), afterSetExtremes(event) {
      previous?.call(this, event);
      if (event?.trigger === "ft-data-refresh"
          || !Number.isFinite(Number(event?.min))
          || !Number.isFinite(Number(event?.max))) return;
      const chart = this.chart;
      clearTimeout(chart._ftRangeLoadTimer);
      const generation = (chart._ftRangeLoadGeneration || 0) + 1;
      chart._ftRangeLoadGeneration = generation;
      chart._ftRangeLoadTimer = setTimeout(async () => {
        chart.showLoading?.(displayOptions.loadingText || "Loading…");
        try {
          const payload = await displayOptions.loadRange(
            Number(event.min), Number(event.max), {
              maxPoints: Math.max(200, Math.ceil(Number(chart.plotWidth || 600) * 1.5)),
            },
          );
          if (!payload || chart._ftRangeLoadGeneration !== generation) return;
          replaceVisibleSeries(
            chart, displayOptions.rangeOptions(payload),
            Number(event.min), Number(event.max),
          );
        } catch (error) {
          if (error?.name !== "AbortError") displayOptions.onRangeError?.(error);
        } finally {
          if (chart._ftRangeLoadGeneration === generation) chart.hideLoading?.();
        }
      }, Math.max(0, Number(displayOptions.rangeDebounceMs) || 120));
    }};
    return options;
  }

  window.FTHighchartsRangeLoader = Object.freeze({attach, replaceVisibleSeries});
})();
