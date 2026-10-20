(() => {
  function replaceVisibleSeries(chart, nextOptions, minimum, maximum,
    {reusePresentation = false} = {}) {
    const orderAxis = nextOptions?.yAxis?.find(axis => axis.id === "asset-order-axis");
    if (orderAxis) chart.get?.("asset-order-axis")?.update?.(orderAxis, false);
    if (Number.isFinite(nextOptions?.chart?.height)
        && nextOptions.chart.height !== chart.chartHeight) {
      chart.setSize?.(null, nextOptions.chart.height, false);
    }
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
      if (!reusePresentation) current.update(presentation, false);
      current.setData(data || [], false, false, false);
    });
    remaining.forEach(series => series.remove(false));
    // Tooltip formatters close over the bars in their own range. Replacing only
    // series leaves the formatter reading the previous range's OHLCV/OI rows.
    if (nextOptions?.tooltip) chart.tooltip?.update?.(nextOptions.tooltip);
    chart._ftCompleteRange = nextOptions?._ftCompleteRange || null;
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
    const overviewData = options.navigator?.series?.data || options.series?.[0]?.data;
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
      const coverage = chart._ftCompleteRange;
      if (coverage && Number(event.min) >= coverage[0]
          && Number(event.max) <= coverage[1]) {
        clearTimeout(chart._ftRangeLoadTimer);
        chart._ftRangeLoadGeneration = (chart._ftRangeLoadGeneration || 0) + 1;
        return;
      }
      clearTimeout(chart._ftRangeLoadTimer);
      const generation = (chart._ftRangeLoadGeneration || 0) + 1;
      chart._ftRangeLoadGeneration = generation;
      chart._ftRangeLoadTimer = setTimeout(async () => {
        if (displayOptions.showRangeLoading !== false) {
          chart.showLoading?.(displayOptions.loadingText || "Loading…");
        }
        try {
          const minimum = Number(event.min);
          const maximum = Number(event.max);
          const span = Math.max(0, maximum - minimum);
          const overscanRatio = Math.max(
            0, Number(displayOptions.rangeOverscanRatio ?? 0.25),
          );
          const proportionalPadding = span * overscanRatio;
          const beforePadding = Math.max(
            proportionalPadding,
            Math.max(0, Number(displayOptions.rangeOverscanBeforeMs) || 0),
          );
          const afterPadding = Math.max(
            proportionalPadding,
            Math.max(0, Number(displayOptions.rangeOverscanAfterMs) || 0),
          );
          const baseMaximum = Math.max(
            200, Math.ceil(Number(chart.plotWidth || 600) * 1.5),
          );
          const requestedRatio = span > 0
            ? (span + beforePadding + afterPadding) / span
            : 1 + overscanRatio * 2;
          const payload = await displayOptions.loadRange(
            minimum - beforePadding, maximum + afterPadding, {
              maxPoints: Math.min(5000, Math.ceil(baseMaximum * requestedRatio)),
              visibleMinimum: minimum,
              visibleMaximum: maximum,
            },
          );
          if (!payload || chart._ftRangeLoadGeneration !== generation) return;
          replaceVisibleSeries(
            chart, displayOptions.rangeOptions(payload),
            minimum, maximum,
            {reusePresentation: displayOptions.reuseSeriesPresentation === true},
          );
        } catch (error) {
          if (error?.name !== "AbortError") displayOptions.onRangeError?.(error);
        } finally {
          if (chart._ftRangeLoadGeneration === generation
              && displayOptions.showRangeLoading !== false) chart.hideLoading?.();
        }
      }, Math.max(0, Number(displayOptions.rangeDebounceMs) || 120));
    }};
    return options;
  }

  window.FTHighchartsRangeLoader = Object.freeze({attach, replaceVisibleSeries});
})();
