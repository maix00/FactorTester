(() => {
  function finite(value) {
    if (value == null || value === "" || typeof value === "boolean") return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  }

  function timestamp(value) {
    const numeric = finite(value);
    if (numeric != null) return numeric;
    const parsed = Date.parse(String(value || ""));
    return Number.isFinite(parsed) ? parsed : null;
  }

  function equityGroups(summary = {}) {
    return (Array.isArray(summary?.groups) ? summary.groups : []).flatMap((item, index) => {
      const timestamps = Array.isArray(item?.timestamps) ? item.timestamps : [];
      const values = Array.isArray(item?.total_equity) ? item.total_equity : [];
      const hasPoint = timestamps.slice(0, values.length).some((value, pointIndex) => (
        timestamp(value) != null && finite(values[pointIndex]) != null
      ));
      if (!hasPoint) return [];
      const id = String(item?.strategy_id || item?.group_id || item?.key || index);
      return [{
        id,
        label: String(
          item?.display_name || item?.name || item?.group_name
          || item?.strategy_id || item?.group_id || item?.key || `策略 ${index + 1}`,
        ),
        currency: String(item?.currency || summary?.base_currency || "CNY").toUpperCase(),
        timestamps,
        values,
      }];
    });
  }

  function buildTimeline(groups) {
    const values = new Set();
    groups.forEach(group => {
      (group.timestamps || []).forEach(value => {
        const parsed = timestamp(value);
        if (parsed != null) values.add(parsed);
      });
    });
    return [...values].sort((left, right) => left - right);
  }

  function buildSeries(groups, timeline) {
    return groups.map(group => {
      const valuesByTimestamp = new Map();
      const pointCount = Math.min(group.timestamps.length, group.values.length);
      for (let index = 0; index < pointCount; index += 1) {
        const pointTimestamp = timestamp(group.timestamps[index]);
        const value = finite(group.values[index]);
        if (pointTimestamp != null && value != null) {
          // Multiple engine events may share one visible millisecond. Keep the
          // latest state at that timestamp, matching the legacy chart.
          valuesByTimestamp.set(pointTimestamp, value);
        }
      }
      return {
        id: group.id,
        name: group.label,
        type: "line",
        data: timeline.map(value => [
          value, valuesByTimestamp.has(value) ? valuesByTimestamp.get(value) : null,
        ]),
        connectNulls: true,
        showInLegend: true,
        visible: true,
        tooltip: {valueDecimals: 2},
      };
    });
  }

  function nearestTimelineMs(timeline, value) {
    if (!timeline.length || finite(value) == null) return null;
    let nearest = timeline[0];
    let distance = Math.abs(nearest - Number(value));
    for (let index = 1; index < timeline.length; index += 1) {
      const nextDistance = Math.abs(timeline[index] - Number(value));
      if (nextDistance < distance) {
        nearest = timeline[index];
        distance = nextDistance;
      }
    }
    return nearest;
  }

  function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
    }[character]));
  }

  function money(value, currency) {
    if (window.MoneyDisplay?.formatMajor) {
      return window.MoneyDisplay.formatMajor(value, {currency, decimals: 2});
    }
    return `${Number(value).toLocaleString(undefined, {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    })} ${currency}`;
  }

  function themeColor(property, fallback) {
    if (typeof document === "undefined" || !window.getComputedStyle) return fallback;
    const value = window.getComputedStyle(document.documentElement)
      .getPropertyValue(property).trim();
    return value || fallback;
  }

  function optionsFor(summary, context, displayOptions = {}) {
    const groups = equityGroups(summary);
    const timeline = buildTimeline(groups);
    const series = buildSeries(groups, timeline);
    const configuredCapital = finite(summary?.initial_capital);
    const observedCapital = series.flatMap(item => item.data)
      .find(point => point[1] != null)?.[1];
    const initialCapital = (configuredCapital && configuredCapital !== 0)
      ? configuredCapital : ((observedCapital && observedCapital !== 0) ? observedCapital : 1);
    const baseCurrency = String(
      summary?.base_currency || groups.find(item => item.currency)?.currency || "CNY",
    ).toUpperCase();
    const splitMs = finite(displayOptions.splitMs);
    const endMs = finite(displayOptions.endMs);
    const showOutOfSample = displayOptions.showOutOfSample === true;
    const onSnapshot = typeof displayOptions.onSnapshot === "function"
      ? displayOptions.onSnapshot : null;
    const isIntraday = timeline.length >= 2 && timeline[1] - timeline[0] < 86_400_000;
    const t = value => context?.t ? context.t(value) : value;
    const theme = {
      text: themeColor("--text", "#1d1d1f"),
      muted: themeColor("--muted", "#74747a"),
      line: themeColor("--line", "#d9d9de"),
      panel: themeColor("--panel", "#ffffff"),
    };
    const chart = {
      backgroundColor: "transparent",
      panning: {enabled: true, type: "x"},
      zooming: {type: "x"},
    };
    const seriesOptions = {
      animation: false, boostThreshold: 1000, connectNulls: true, turboThreshold: 0,
    };

    // Keep the legacy snapshot hook as an optional timestamp callback. The
    // current result view intentionally does not provide it yet.
    if (onSnapshot) {
      chart.events = {
        click(event) {
          let axisValue = finite(event?.xAxis?.[0]?.value);
          if (axisValue == null && finite(event?.chartX) != null && this.xAxis?.length) {
            axisValue = this.xAxis[0].toValue(Number(event.chartX) - this.plotLeft, true);
          }
          const nearest = nearestTimelineMs(timeline, axisValue);
          if (nearest != null) onSnapshot(nearest);
        },
      };
      seriesOptions.cursor = "pointer";
      seriesOptions.point = {events: {click() { onSnapshot(this.x); }}};
    }

    return {
      chart,
      title: {
        text: t("策略净值曲线"), align: "left",
        style: {color: theme.text, fontSize: "14px"},
      },
      credits: {enabled: false},
      accessibility: {enabled: false},
      legend: {
        enabled: true, align: "center", verticalAlign: "bottom", layout: "horizontal",
        itemStyle: {color: theme.muted, fontSize: "11px"},
        itemHoverStyle: {color: theme.text},
      },
      rangeSelector: {enabled: false},
      navigator: {
        enabled: true,
        handles: {backgroundColor: theme.panel, borderColor: theme.muted},
        xAxis: {
          lineColor: theme.line, tickColor: theme.line,
          labels: {style: {color: theme.muted}},
        },
      },
      scrollbar: {
        enabled: true,
        barBackgroundColor: theme.muted, barBorderColor: theme.muted,
        buttonBackgroundColor: theme.panel, buttonBorderColor: theme.line,
        rifleColor: theme.panel, trackBackgroundColor: theme.panel,
        trackBorderColor: theme.line,
      },
      xAxis: {
        type: "datetime", ordinal: true,
        lineColor: theme.line, tickColor: theme.line,
        labels: {style: {color: theme.muted}},
        max: !showOutOfSample && splitMs != null ? splitMs : null,
        plotBands: showOutOfSample && splitMs != null ? [{
          from: splitMs,
          to: endMs ?? Number.MAX_SAFE_INTEGER,
          color: "rgba(217, 119, 6, 0.12)",
          label: {
            text: t("样本外"),
            style: {color: "#d97706", fontWeight: "600"},
          },
        }] : [],
        dateTimeLabelFormats: isIntraday
          ? {day: "%m-%d", week: "%m-%d", month: "%Y-%m"}
          : {day: "%Y-%m-%d", week: "%Y-%m-%d", month: "%Y-%m"},
      },
      yAxis: [{
        title: {text: `${t("总权益")} (${baseCurrency})`, style: {color: theme.text}},
        opposite: false,
        gridLineColor: theme.line,
        labels: {
          style: {color: theme.muted},
          formatter() { return `${(this.value / 10_000).toFixed(0)}万`; },
        },
      }, {
        title: {text: t("累计收益率 (%)"), style: {color: theme.text}},
        opposite: true,
        linkedTo: 0,
        labels: {
          style: {color: theme.muted},
          formatter() {
            return `${((this.value / initialCapital - 1) * 100).toFixed(2)}%`;
          },
        },
      }],
      plotOptions: {series: seriesOptions},
      tooltip: {
        shared: true,
        useHTML: true,
        backgroundColor: theme.panel,
        borderColor: theme.line,
        style: {color: theme.text},
        formatter() {
          const date = window.Highcharts?.dateFormat
            ? window.Highcharts.dateFormat("%Y-%m-%d %H:%M", this.x)
            : new Date(this.x).toLocaleString();
          let result = `<b>${escapeHTML(date)}</b>`;
          (this.points || []).forEach(point => {
            if (point.y == null) return;
            const percent = ((point.y / initialCapital - 1) * 100).toFixed(2);
            result += `<br/>${escapeHTML(point.series.name)}: ${escapeHTML(
              money(point.y, baseCurrency),
            )} &nbsp;(${percent}%)`;
          });
          return result;
        },
      },
      series,
    };
  }

  function mount(context, target, summary, displayOptions = {}) {
    if (!window.Highcharts?.stockChart) {
      throw new Error(context.t("Highcharts 组件未加载"));
    }
    if (!equityGroups(summary).length) throw new Error(context.t("暂无策略净值曲线"));
    target._ftChart?.destroy?.();
    target.replaceChildren();
    target.classList.add("interactive-artifact-chart", "backtest-group-equity-chart");
    const canvas = document.createElement("div");
    canvas.className = "interactive-artifact-chart-canvas";
    canvas.setAttribute("aria-label", context.t("策略净值曲线"));
    target.append(canvas);
    target._ftChart = window.Highcharts.stockChart(
      canvas, optionsFor(summary, context, displayOptions),
    );
    return target._ftChart;
  }

  window.FTBacktestGroupEquityChart = Object.freeze({
    buildSeries, buildTimeline, equityGroups, mount, nearestTimelineMs, optionsFor,
  });
})();
