import {chartInteraction} from "./chart-interaction";
import {useEffect, useRef, useState} from "react";
import {createRoot, type Root} from "react-dom/client";
import {mergeBars} from "./range-data";
import {WickPrimitive} from "./wick-primitive";

type Bar = {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  openInterest: number | null;
};
type ChartRange = {from: number; to: number};
type RangeBand = {id: string; start: number; end: number; label?: string};
type ChartApi = {
  applyOptions: (options: Record<string, unknown>) => void;
  addSeries: (kind: unknown, options: Record<string, unknown>, paneIndex?: number) => SeriesApi;
  timeScale: () => {
    fitContent: () => void;
    getVisibleRange: () => ChartRange | null;
    setVisibleRange: (range: ChartRange) => void;
    getVisibleLogicalRange: () => ChartRange | null;
    setVisibleLogicalRange: (range: ChartRange) => void;
    width: () => number;
    coordinateToTime: (x: number) => number | null;
    coordinateToLogical: (x: number) => number | null;
    logicalToCoordinate: (logical: number) => number | null;
    subscribeVisibleTimeRangeChange: (fn: (range: ChartRange | null) => void) => void;
    unsubscribeVisibleTimeRangeChange: (fn: (range: ChartRange | null) => void) => void;
  };
  subscribeClick: (fn: (point: {time?: number; point?: {x: number; y: number}} | undefined) => void) => void;
  subscribeCrosshairMove: (fn: (point: {time?: number} | undefined) => void) => void;
  unsubscribeCrosshairMove: (fn: (point: {time?: number} | undefined) => void) => void;
  remove: () => void;
};
type SeriesApi = {
  setData: (rows: unknown[]) => void;
  priceToCoordinate: (price: number) => number | null;
  attachPrimitive?: (primitive: WickPrimitive) => void;
};
type LightweightChartsApi = {
  createChart: (target: HTMLElement, options: Record<string, unknown>) => ChartApi;
  CandlestickSeries: unknown;
  HistogramSeries: unknown;
  LineSeries: unknown;
  createSeriesMarkers?: (series: SeriesApi, markers: unknown[],
    options?: Record<string, unknown>) => {setMarkers: (markers: unknown[]) => void};
};
type Options = {
  bars: Bar[];
  hasOpenInterest?: boolean;
  timeZone?: string;
  loadRange?: (minimum: number, maximum: number, maxPoints: number) => Promise<Bar[]>;
  translate?: (value: string) => string;
  onReady?: (controls: {
    focusRange: (minimum: number, maximum: number) => void;
    mergeOverview: (rows: Bar[]) => void;
    fitContent: () => void;
    setTimeZone: (timeZone: string) => void;
    setRangeBands: (ranges: RangeBand[]) => void;
    selectRangeBand: (id: string) => boolean;
  }) => void;
};

declare global {
  interface Window { LightweightCharts?: LightweightChartsApi }
}

const roots = new WeakMap<HTMLElement, Root>();

function sortedBars(source: Bar[]): Bar[] {
  const byTime = new Map<number, Bar>();
  for (const bar of source) {
    if (!Number.isFinite(bar.timestamp) || ![bar.open, bar.high, bar.low, bar.close]
      .every(Number.isFinite)) continue;
    byTime.set(Math.floor(bar.timestamp / 1000), bar);
  }
  return [...byTime.entries()].sort(([left], [right]) => left - right)
    .map(([, bar]) => bar);
}

function toTime(bar: Bar): number { return Math.floor(bar.timestamp / 1000); }

function timeAtLogical(rows: Bar[], logical: number): number {
  if (!rows.length) return 0;
  const before = Math.max(0, Math.min(rows.length - 1, Math.floor(logical)));
  const after = Math.min(rows.length - 1, before + 1);
  return toTime(rows[before]) + (logical - before)
    * (toTime(rows[after]) - toTime(rows[before]));
}

// Time ranges are expressed in seconds; logical positions are bar indexes.
// Interpolate at a missing timestamp so an overview bar can be replaced by
// source-frequency bars without snapping the pointer to a neighbouring bar.
function logicalAtTime(rows: Bar[], time: number): number {
  if (!rows.length) return 0;
  if (time <= toTime(rows[0])) return 0;
  if (time >= toTime(rows[rows.length - 1])) return rows.length - 1;
  let low = 0;
  let high = rows.length - 1;
  while (low + 1 < high) {
    const middle = (low + high) >>> 1;
    if (toTime(rows[middle]) <= time) low = middle;
    else high = middle;
  }
  const before = toTime(rows[low]);
  const after = toTime(rows[high]);
  return low + (time - before) / (after - before);
}

function priceDecimals(bar: Bar): number {
  return Math.min(12, Math.max(...[bar.open, bar.high, bar.low, bar.close].map(value => {
    const text = String(value);
    return text.includes(".") ? text.split(".")[1].length : 0;
  })));
}

function localTick(time: number, kind: number, locale: string, timeZone?: string): string {
  const options: Intl.DateTimeFormatOptions = kind === 0 ? {year: "numeric"}
    : kind === 1 ? {month: "short"}
    : kind === 2 ? {month: "numeric", day: "numeric"}
    : {hour: "2-digit", minute: "2-digit", hour12: false,
      ...(kind === 4 ? {second: "2-digit"} : {})};
  return new Date(Number(time) * 1000).toLocaleString(locale,
    {...options, ...(timeZone ? {timeZone} : {})});
}

function MarketChart({bars, hasOpenInterest, timeZone, loadRange, onReady,
  translate = value => value}: Options) {
  const chartNode = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<{
    bar: Bar; x: number; y: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [displayTimeZone, setDisplayTimeZone] = useState(timeZone);

  useEffect(() => {
    const api = window.LightweightCharts;
    const node = chartNode.current;
    if (!api || !node) return;
    let activeTimeZone = timeZone;
    const formatTime = (time: number) => new Date(Number(time) * 1000)
      .toLocaleString(undefined, activeTimeZone ? {timeZone: activeTimeZone} : undefined);
    const chart = api.createChart(node, {
      autoSize: true, height: 460,
      attributionLogo: true,
      layout: {background: {color: "#ffffff"}, textColor: "#5f6672"},
      grid: {vertLines: {color: "#edf0f4"}, horzLines: {color: "#edf0f4"}},
      crosshair: {vertLine: {color: "#2563eb", width: 1,
        labelBackgroundColor: "#2563eb"}},
      timeScale: {timeVisible: true, secondsVisible: false, rightOffset: 0,
        fixLeftEdge: true, fixRightEdge: true, minBarSpacing: 0.02,
        tickMarkFormatter: (time: number, kind: number, locale: string) =>
          localTick(time, kind, locale, activeTimeZone)},
      localization: {timeFormatter: formatTime},
      ...chartInteraction,
    });
    const candle = chart.addSeries(api.CandlestickSeries, {
      upColor: "#19a47b", downColor: "#e14f5b",
      borderVisible: false, wickUpColor: "#19a47b", wickDownColor: "#e14f5b",
    });
    const wick = new WickPrimitive();
    candle.attachPrimitive?.(wick);
    const hoverMarker = api.createSeriesMarkers?.(candle, [], {autoScale: false});
    let hoveredTime: number | null = null;
    const hasVolume = bars.some(bar => bar.volume !== null);
    const showOpenInterest = hasOpenInterest === true
      || bars.some(bar => bar.openInterest !== null);
    const volume = hasVolume ? chart.addSeries(api.HistogramSeries, {
      priceFormat: {type: "volume"}, priceLineVisible: false,
    }, 1) : null;
    const openInterest = showOpenInterest ? chart.addSeries(api.LineSeries, {
      color: "#805bd6", lineWidth: 2, priceLineVisible: false,
    }, hasVolume ? 2 : 1) : null;
    let overview = sortedBars(bars);
    const apply = (rows: Bar[]) => {
      hoveredTime = null;
      hoverMarker?.setMarkers([]);
      candle.setData(rows.map(bar => ({time: toTime(bar), open: bar.open,
        high: bar.high, low: bar.low, close: bar.close})));
      wick.setRows(rows.map(bar => ({time: toTime(bar), open: bar.open,
        high: bar.high, low: bar.low, close: bar.close})));
      volume?.setData(rows.filter(bar => bar.volume !== null).map(bar => ({
        time: toTime(bar), value: bar.volume,
        color: bar.close >= bar.open ? "#a9d8c9" : "#efb4b9",
      })));
      openInterest?.setData(rows.map(bar => bar.openInterest === null
        ? {time: toTime(bar)} : {time: toTime(bar), value: bar.openInterest}));
      return new Map(rows.map(bar => [toTime(bar), bar]));
    };
    let cached = overview;
    let indexed = apply(cached);
    let displayed = cached;
    const bandLayer = document.createElement("div");
    bandLayer.className = "ft-lightweight-range-bands";
    node.append(bandLayer);
    const switchLayer = document.createElement("div");
    switchLayer.className = "ft-asset-roll-switches";
    node.append(switchLayer);
    let rangeBands: RangeBand[] = [];
    const bandElements = new Map<string, HTMLDivElement>();
    let selectedBandID = "";
    const drawRangeBands = () => {
      const scale = chart.timeScale();
      const width = scale.width();
      bandLayer.style.width = `${width}px`;
      switchLayer.style.width = `${width}px`;
      switchLayer.replaceChildren();
      if (!displayed.length) return;
      const earliest = rangeBands.reduce((value, band) => Math.min(value, band.start), Infinity);
      for (const band of rangeBands) {
        const element = bandElements.get(band.id);
        if (!element) continue;
        if (!Number.isFinite(band.start) || !Number.isFinite(band.end)
          || band.end <= band.start || band.end < displayed[0].timestamp
          || band.start > displayed[displayed.length - 1].timestamp) {
          element.hidden = true;
          continue;
        }
        const from = scale.logicalToCoordinate(
          logicalAtTime(displayed, band.start / 1000));
        const to = scale.logicalToCoordinate(
          logicalAtTime(displayed, band.end / 1000));
        if (from === null || to === null || to <= 0 || from >= width) {
          element.hidden = true;
          continue;
        }
        const left = Math.max(0, from);
        const right = Math.min(width, to);
        if (right <= left) { element.hidden = true; continue; }
        element.hidden = false;
        element.className = `ft-lightweight-range-band${band.id === selectedBandID
          ? " is-selected" : ""}`;
        element.style.left = `${left}px`;
        element.style.width = `${right - left}px`;
        if (band.start > earliest && from >= 0 && from <= width) {
          const marker = document.createElement("div");
          marker.className = "ft-asset-roll-switch";
          marker.style.left = `${from}px`;
          marker.title = `${translate("主力切换至")} ${band.label || band.id}`;
          const label = document.createElement("span");
          label.textContent = `${translate("换主力")} · ${band.label || band.id}`;
          marker.append(label);
          switchLayer.append(marker);
        }
      }
    };
    chart.timeScale().fitContent();
    const bandResizeObserver = typeof ResizeObserver === "undefined" ? null
      : new ResizeObserver(drawRangeBands);
    bandResizeObserver?.observe(node);
    let userChangedRange = false;
    let pendingInteraction = false;
    let pointerActive = false;
    let pointerX: number | null = null;
    const rememberPointer = (event: PointerEvent | WheelEvent) => {
      pointerX = event.clientX - node.getBoundingClientRect().left;
    };
    const markInteraction = () => {
      userChangedRange = true;
      pendingInteraction = true;
    };
    const pointerDown = () => { pointerActive = true; markInteraction(); };
    const pointerMove = (event: PointerEvent) => {
      rememberPointer(event);
      if (pointerActive) markInteraction();
    };
    const pointerUp = () => { pointerActive = false; };
    const wheel = (event: WheelEvent) => { rememberPointer(event); markInteraction(); };
    const pointerLeave = () => { pointerX = null; };
    node.addEventListener("wheel", wheel);
    node.addEventListener("pointerdown", pointerDown);
    node.addEventListener("pointermove", pointerMove);
    node.addEventListener("pointerup", pointerUp);
    node.addEventListener("pointercancel", pointerUp);
    node.addEventListener("pointerleave", pointerLeave);
    node.addEventListener("touchstart", markInteraction);
    node.addEventListener("touchmove", markInteraction);
    const onHover = (point: {time?: number} | undefined) => {
      const time = point?.time === undefined ? null : Number(point.time);
      if (time === hoveredTime) return;
      hoveredTime = time;
      hoverMarker?.setMarkers(time !== null && indexed.has(time)
        ? [{time, position: "aboveBar", shape: "circle",
          color: "#2563eb", size: 0.6}] : []);
    };
    chart.subscribeCrosshairMove(onHover);
    chart.subscribeClick(point => {
      const bar = point?.time === undefined ? null : indexed.get(Number(point.time));
      if (!bar || !point?.point) { setSelected(null); return; }
      const x = Math.min(Math.max(point.point.x + 14, 8),
        Math.max(8, node.clientWidth - 320));
      const y = Math.min(Math.max(point.point.y + 14, 8),
        Math.max(8, node.clientHeight - 270));
      setSelected(previous => previous?.bar.timestamp === bar.timestamp
        ? null : {bar, x, y});
    });

    let timer: ReturnType<typeof setTimeout> | undefined;
    let loadingTimer: ReturnType<typeof setTimeout> | undefined;
    let revision = 0;
    let lastRequest = "";
    let detailCoverage: ChartRange | null = null;
    let detailViewportSpan = 0;
    const replaceData = (rows: Bar[], visible: ChartRange | null) => {
      const scale = chart.timeScale();
      const previousLogical = scale.getVisibleLogicalRange();
      const pointerLogical = pointerX === null ? null : scale.coordinateToLogical(pointerX);
      let target: ChartRange | null = null;
      if (visible && rows.length > 1) {
        const from = logicalAtTime(rows, previousLogical
          ? timeAtLogical(displayed, previousLogical.from) : Number(visible.from));
        const to = logicalAtTime(rows, previousLogical
          ? timeAtLogical(displayed, previousLogical.to) : Number(visible.to));
        const span = Math.max(1, to - from);
        // The plot excludes the right price axis. Logical range endpoints do
        // not map to the full React node width, especially at fine spacing.
        const fraction = pointerX === null ? null
          : Math.max(0, Math.min(1, pointerX / Math.max(1, scale.width())));
        const wantedFrom = pointerLogical === null || fraction === null ? from
          : logicalAtTime(rows, timeAtLogical(displayed, pointerLogical)) - fraction * span;
        const boundedFrom = Math.max(0, Math.min(rows.length - 1 - span, wantedFrom));
        target = {from: boundedFrom, to: boundedFrom + span};
      }
      indexed = apply(rows);
      displayed = rows;
      if (target) scale.setVisibleLogicalRange(target);
      drawRangeBands();
    };
    const stopLoading = () => {
      if (loadingTimer) clearTimeout(loadingTimer);
      loadingTimer = undefined;
      setLoading(false);
    };
    const restoreOverview = () => {
      if (cached === overview) return;
      const visible = chart.timeScale().getVisibleRange();
      // setData emits its own range event. Keep the user gesture pending for
      // the debounce below, but never treat this chart redraw as a gesture.
      const wasPending = pendingInteraction;
      pendingInteraction = false;
      cached = overview;
      replaceData(cached, visible);
      pendingInteraction = wasPending;
      detailCoverage = null;
      lastRequest = "";
      stopLoading();
    };
    const onRange = (range: ChartRange | null) => {
      drawRangeBands();
      // setData and setVisibleRange also emit range changes. Only a direct
      // gesture (or focusRange below) may start a data request.
      if (!range || !loadRange || !pendingInteraction) return;
      const desiredRevision = ++revision;
      // A wider viewport exposes the overview/fine-data seam immediately,
      // before the debounced request could replace it. Switch to one coherent
      // overview resolution synchronously, then refine the settled viewport.
      if (detailCoverage && cached !== overview
        && Number(range.to) - Number(range.from) > detailViewportSpan * 1.1) {
        restoreOverview();
      }
      const settledRange = chart.timeScale().getVisibleRange() || range;
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        pendingInteraction = false;
        const first = Number(overview[0]?.timestamp) / 1000;
        const last = Number(overview[overview.length - 1]?.timestamp) / 1000;
        const minimum = Math.max(Number(settledRange.from), first);
        const maximum = Math.min(Number(settledRange.to), last);
        if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || maximum <= minimum) return;
        // The overview is sufficient for broad ranges. Drop the fine bars as
        // soon as the user zooms back out; otherwise their minimum spacing
        // prevents the chart from reaching the full source interval.
        if (maximum - minimum >= (last - first) / 2) {
          revision += 1;
          stopLoading();
          setError("");
          lastRequest = "";
          detailCoverage = null;
          restoreOverview();
          return;
        }
        const span = maximum - minimum;
        if (detailCoverage && minimum >= detailCoverage.from
          && maximum <= detailCoverage.to
          && span >= detailViewportSpan / 2) {
          stopLoading();
          return;
        }
        const key = `${Math.round(minimum)}:${Math.round(maximum)}`;
        if (key === lastRequest) return;
        lastRequest = key;
        setError("");
        if (loadingTimer) clearTimeout(loadingTimer);
        loadingTimer = setTimeout(() => setLoading(true), 250);
        try {
          const pointBudget = Math.min(5000, Math.max(600,
            Math.round(node.clientWidth * 2) || 2400));
          // Fetch outside the viewport so the coarse/fine boundary never
          // appears at its edge. Nearby pans then reuse this detail instead
          // of replacing all three series after every small gesture.
          const fetchStart = Math.max(first, minimum - span / 2);
          const fetchEnd = Math.min(last, maximum + span / 2);
          const detailed = sortedBars(await loadRange(
            fetchStart * 1000, fetchEnd * 1000, pointBudget));
          if (desiredRevision !== revision) return;
          if (!detailed.length) {
            lastRequest = "";
            stopLoading();
            return;
          }
          // An overview candle summarizes multiple source bars. Keep it only
          // outside the fetched interval, otherwise it would be drawn beside
          // the finer candles and misrepresent the same period twice.
          const start = fetchStart * 1000;
          const end = fetchEnd * 1000;
          cached = sortedBars(mergeBars(overview.filter(bar =>
            bar.timestamp < start || bar.timestamp > end), detailed));
          detailCoverage = {from: fetchStart, to: fetchEnd};
          detailViewportSpan = span;
          const visible = chart.timeScale().getVisibleRange();
          replaceData(cached, visible);
          setError("");
          stopLoading();
        } catch (reason) {
          if (desiredRevision === revision) {
            lastRequest = "";
            setError(reason instanceof Error ? reason.message : String(reason));
            stopLoading();
          }
        }
      }, 180);
    };
    chart.timeScale().subscribeVisibleTimeRangeChange(onRange);
    onReady?.({
      focusRange(minimum, maximum) {
        if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || maximum <= minimum) return;
        markInteraction();
        chart.timeScale().setVisibleRange({from: Math.floor(minimum / 1000),
          to: Math.ceil(maximum / 1000)});
      },
      mergeOverview(rows) {
        const extra = sortedBars(rows);
        if (!extra.length) return;
        const visible = chart.timeScale().getVisibleRange();
        overview = sortedBars(mergeBars(extra, overview));
        cached = sortedBars(mergeBars(overview, cached));
        if (userChangedRange && visible) replaceData(cached, visible);
        else { indexed = apply(cached); chart.timeScale().fitContent(); }
      },
      fitContent() {
        userChangedRange = false;
        pendingInteraction = false;
        revision += 1;
        if (timer) clearTimeout(timer);
        stopLoading();
        lastRequest = "";
        detailCoverage = null;
        cached = overview;
        indexed = apply(cached);
        displayed = cached;
        chart.timeScale().fitContent();
      },
      setTimeZone(nextTimeZone) {
        activeTimeZone = nextTimeZone;
        setDisplayTimeZone(nextTimeZone);
        chart.applyOptions({timeScale: {tickMarkFormatter:
          (time: number, kind: number, locale: string) =>
            localTick(time, kind, locale, activeTimeZone)},
        localization: {timeFormatter: formatTime}});
      },
      setRangeBands(ranges) {
        rangeBands = ranges;
        bandLayer.replaceChildren();
        bandElements.clear();
        for (const band of ranges) {
          const element = document.createElement("div");
          element.className = "ft-lightweight-range-band";
          bandLayer.append(element);
          bandElements.set(band.id, element);
        }
        drawRangeBands();
      },
      selectRangeBand(id) {
        selectedBandID = id;
        drawRangeBands();
        const band = rangeBands.find(item => item.id === id);
        if (!band || !displayed.length) return false;
        const first = toTime(displayed[0]) * 1000;
        const last = toTime(displayed[displayed.length - 1]) * 1000;
        if (band.end < first || band.start > last) return false;
        const visible = chart.timeScale().getVisibleRange();
        if (visible && band.start / 1000 <= Number(visible.to)
          && band.end / 1000 >= Number(visible.from)) return true;
        const from = Math.max(0, logicalAtTime(displayed, band.start / 1000) - 1);
        const to = Math.min(displayed.length - 1,
          logicalAtTime(displayed, band.end / 1000) + 1);
        chart.timeScale().setVisibleLogicalRange({from, to: Math.max(from + 1, to)});
        return true;
      },
    });
    return () => {
      revision += 1;
      if (timer) clearTimeout(timer);
      if (loadingTimer) clearTimeout(loadingTimer);
      bandResizeObserver?.disconnect();
      bandLayer.remove();
      switchLayer.remove();
      node.removeEventListener("wheel", wheel);
      node.removeEventListener("pointerdown", pointerDown);
      node.removeEventListener("pointermove", pointerMove);
      node.removeEventListener("pointerup", pointerUp);
      node.removeEventListener("pointercancel", pointerUp);
      node.removeEventListener("pointerleave", pointerLeave);
      node.removeEventListener("touchstart", markInteraction);
      node.removeEventListener("touchmove", markInteraction);
      chart.unsubscribeCrosshairMove(onHover);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(onRange);
      chart.remove();
    };
  }, [bars, hasOpenInterest, loadRange]);

  return <div className="ft-lightweight-price">
    <div ref={chartNode} className="ft-lightweight-price-canvas"
      aria-label={translate("行情 K 线、成交量和持仓量")} />
    {loading && <div className="ft-lightweight-price-loading" role="status">
      {translate("正在细化当前时间范围…")}
    </div>}
    {selected && <section className="ft-chart-inspector ft-lightweight-price-detail"
      role="dialog" aria-label={translate("蜡烛详情")}
      style={{left: selected.x, top: selected.y}}>
      <header><strong>{new Date(selected.bar.timestamp).toLocaleString(undefined,
        displayTimeZone ? {timeZone: displayTimeZone} : undefined)}</strong>
        <button type="button" aria-label={translate("关闭")}
          onClick={() => setSelected(null)}>×</button></header>
      <dl>{[["开盘价", selected.bar.open.toFixed(priceDecimals(selected.bar))],
        ["最高价", selected.bar.high.toFixed(priceDecimals(selected.bar))],
        ["最低价", selected.bar.low.toFixed(priceDecimals(selected.bar))],
        ["收盘价", selected.bar.close.toFixed(priceDecimals(selected.bar))],
        ["成交量", selected.bar.volume ?? "—"],
        ["持仓量", selected.bar.openInterest ?? "—"]]
        .map(([label, value]) => <div key={label}>
          <dt>{translate(String(label))}</dt><dd>{value}</dd>
        </div>)}</dl>
    </section>}
    {error && <p role="status" className="ft-lightweight-price-error">{error}</p>}
  </div>;
}

type PriceChartHandle = (() => void) & {
  focusRange: (minimum: number, maximum: number) => void;
  mergeOverview: (rows: Bar[]) => void;
  fitContent: () => void;
  setTimeZone: (timeZone: string) => void;
  setRangeBands: (ranges: RangeBand[]) => void;
  selectRangeBand: (id: string) => boolean;
};

export function mountPriceChart(target: HTMLElement, options: Options): PriceChartHandle {
  roots.get(target)?.unmount();
  const root = createRoot(target);
  roots.set(target, root);
  let controls: Parameters<NonNullable<Options["onReady"]>>[0] | null = null;
  let pending: [number, number] | null = null;
  let pendingOverview: Bar[] | null = null;
  let pendingBands: RangeBand[] | null = null;
  let pendingBandID = "";
  root.render(<MarketChart {...options} onReady={ready => {
    controls = ready;
    if (pendingOverview) { ready.mergeOverview(pendingOverview); pendingOverview = null; }
    if (pendingBands) { ready.setRangeBands(pendingBands); pendingBands = null; }
    if (pendingBandID) { ready.selectRangeBand(pendingBandID); pendingBandID = ""; }
    if (pending) { ready.focusRange(...pending); pending = null; }
  }} />);
  const dispose = (() => {
    if (roots.get(target) === root) {
      root.unmount();
      roots.delete(target);
    }
    controls = null;
    pending = null;
    pendingOverview = null;
    pendingBands = null;
    pendingBandID = "";
  }) as PriceChartHandle;
  dispose.focusRange = (minimum, maximum) => {
    if (controls) controls.focusRange(minimum, maximum);
    else pending = [minimum, maximum];
  };
  dispose.mergeOverview = rows => {
    if (controls) controls.mergeOverview(rows);
    else pendingOverview = rows;
  };
  dispose.fitContent = () => controls?.fitContent();
  dispose.setTimeZone = timeZone => controls?.setTimeZone(timeZone);
  dispose.setRangeBands = ranges => {
    if (controls) controls.setRangeBands(ranges);
    else pendingBands = ranges;
  };
  dispose.selectRangeBand = id => {
    if (controls) return controls.selectRangeBand(id);
    pendingBandID = id;
    return true;
  };
  return dispose;
}
