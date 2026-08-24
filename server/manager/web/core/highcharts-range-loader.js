(() => {
  function boundaryPoint(definition, timestamp) {
    const sample = (definition.data || []).find(item => item != null);
    if (Array.isArray(sample)) {
      return [timestamp, ...Array(Math.max(1, sample.length - 1)).fill(null)];
    }
    return {x: timestamp, y: null};
  }

  function preserveFullDomain(chart, definition) {
    const minimum = Number(chart._ftFullDataMin);
    const maximum = Number(chart._ftFullDataMax);
    if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return definition;
    const data = Array.isArray(definition.data) ? [...definition.data] : [];
    const timestamps = new Set(data.map(item => Number(
      Array.isArray(item) ? item[0] : item?.x,
    )).filter(Number.isFinite));
    if (!timestamps.has(minimum)) data.unshift(boundaryPoint(definition, minimum));
    if (!timestamps.has(maximum)) data.push(boundaryPoint(definition, maximum));
    return {...definition, data};
  }

  function replaceVisibleSeries(chart, nextOptions, minimum, maximum) {
    const narrowed = Number.isFinite(minimum) && Number.isFinite(maximum);
    const definitions = (Array.isArray(nextOptions?.series) ? nextOptions.series : [])
      .map(definition => narrowed ? preserveFullDomain(chart, definition) : definition);
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
    options.navigator = {
      ...(options.navigator || {}), adaptToUpdatedData: false,
    };
    options.chart = {...(options.chart || {}), zooming: {
      ...(options.chart?.zooming || {}), mouseWheel: {
        enabled: true, showResetButton: true,
        ...(options.chart?.zooming?.mouseWheel || {}),
      },
    }};
    options.xAxis = options.xAxis || {};
    const previous = options.xAxis.events?.afterSetExtremes;
    options.xAxis.events = {...(options.xAxis.events || {}), afterSetExtremes(event) {
      previous?.call(this, event);
      const resetToAll = event?.rangeSelectorButton?.type === "all";
      if (event?.trigger === "ft-data-refresh"
          || (!resetToAll && (!Number.isFinite(Number(event?.min))
            || !Number.isFinite(Number(event?.max))))) return;
      const chart = this.chart;
      const dataMinimum = Number(event?.dataMin ?? chart.xAxis?.[0]?.dataMin);
      const dataMaximum = Number(event?.dataMax ?? chart.xAxis?.[0]?.dataMax);
      if (!Number.isFinite(chart._ftFullDataMin) && Number.isFinite(dataMinimum)) {
        chart._ftFullDataMin = dataMinimum;
      }
      if (!Number.isFinite(chart._ftFullDataMax) && Number.isFinite(dataMaximum)) {
        chart._ftFullDataMax = dataMaximum;
      }
      clearTimeout(chart._ftRangeLoadTimer);
      const generation = (chart._ftRangeLoadGeneration || 0) + 1;
      chart._ftRangeLoadGeneration = generation;
      chart._ftRangeLoadTimer = setTimeout(async () => {
        chart.showLoading?.(displayOptions.loadingText || "Loading…");
        try {
          const payload = await displayOptions.loadRange(
            resetToAll ? undefined : Number(event.min),
            resetToAll ? undefined : Number(event.max), {
              maxPoints: Math.max(200, Math.ceil(Number(chart.plotWidth || 600) * 1.5)),
            },
          );
          if (!payload || chart._ftRangeLoadGeneration !== generation) return;
          replaceVisibleSeries(
            chart, displayOptions.rangeOptions(payload),
            resetToAll ? null : Number(event.min),
            resetToAll ? null : Number(event.max),
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
