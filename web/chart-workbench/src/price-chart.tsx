import {useEffect, useRef, useState} from "react";
import {createRoot, type Root} from "react-dom/client";
import {mergeBars} from "./range-data";

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
type ChartApi = {
  addSeries: (kind: unknown, options: Record<string, unknown>, paneIndex?: number) => SeriesApi;
  timeScale: () => {
    fitContent: () => void;
    getVisibleRange: () => ChartRange | null;
    setVisibleRange: (range: ChartRange) => void;
    subscribeVisibleTimeRangeChange: (fn: (range: ChartRange | null) => void) => void;
    unsubscribeVisibleTimeRangeChange: (fn: (range: ChartRange | null) => void) => void;
  };
  subscribeClick: (fn: (point: {time?: number} | undefined) => void) => void;
  remove: () => void;
};
type SeriesApi = {setData: (rows: unknown[]) => void};
type LightweightChartsApi = {
  createChart: (target: HTMLElement, options: Record<string, unknown>) => ChartApi;
  CandlestickSeries: unknown;
  HistogramSeries: unknown;
  LineSeries: unknown;
};
type Options = {
  bars: Bar[];
  loadRange?: (minimum: number, maximum: number, maxPoints: number) => Promise<Bar[]>;
  translate?: (value: string) => string;
  onReady?: (focus: (minimum: number, maximum: number) => void) => void;
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

function localTick(time: number, kind: number, locale: string): string {
  const options: Intl.DateTimeFormatOptions = kind === 0 ? {year: "numeric"}
    : kind === 1 ? {month: "short"}
    : kind === 2 ? {month: "numeric", day: "numeric"}
    : {hour: "2-digit", minute: "2-digit", hour12: false,
      ...(kind === 4 ? {second: "2-digit"} : {})};
  return new Date(Number(time) * 1000).toLocaleString(locale, options);
}

function MarketChart({bars, loadRange, onReady, translate = value => value}: Options) {
  const chartNode = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<Bar | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const api = window.LightweightCharts;
    const node = chartNode.current;
    if (!api || !node) return;
    const chart = api.createChart(node, {
      autoSize: true, height: 460,
      attributionLogo: true,
      layout: {background: {color: "#ffffff"}, textColor: "#5f6672"},
      grid: {vertLines: {color: "#edf0f4"}, horzLines: {color: "#edf0f4"}},
      timeScale: {timeVisible: true, secondsVisible: false, rightOffset: 8,
        tickMarkFormatter: localTick},
      localization: {timeFormatter: (time: number) => new Date(Number(time) * 1000)
        .toLocaleString()},
      handleScroll: {mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true},
      handleScale: {mouseWheel: true, pinch: true, axisPressedMouseMove: true},
    });
    const candle = chart.addSeries(api.CandlestickSeries, {
      upColor: "#19a47b", downColor: "#e14f5b",
      borderVisible: false, wickUpColor: "#19a47b", wickDownColor: "#e14f5b",
    });
    const hasVolume = bars.some(bar => bar.volume !== null);
    const hasOpenInterest = bars.some(bar => bar.openInterest !== null);
    const volume = hasVolume ? chart.addSeries(api.HistogramSeries, {
      priceFormat: {type: "volume"}, priceLineVisible: false,
    }, 1) : null;
    const openInterest = hasOpenInterest ? chart.addSeries(api.LineSeries, {
      color: "#805bd6", lineWidth: 2, priceLineVisible: false,
    }, hasVolume ? 2 : 1) : null;
    const overview = sortedBars(bars);
    const apply = (rows: Bar[]) => {
      candle.setData(rows.map(bar => ({time: toTime(bar), open: bar.open,
        high: bar.high, low: bar.low, close: bar.close})));
      volume?.setData(rows.filter(bar => bar.volume !== null).map(bar => ({
        time: toTime(bar), value: bar.volume,
        color: bar.close >= bar.open ? "#a9d8c9" : "#efb4b9",
      })));
      openInterest?.setData(rows.filter(bar => bar.openInterest !== null).map(bar => ({
        time: toTime(bar), value: bar.openInterest,
      })));
      return new Map(rows.map(bar => [toTime(bar), bar]));
    };
    let cached = overview;
    let indexed = apply(cached);
    chart.timeScale().fitContent();
    chart.subscribeClick(point => setSelected(point?.time === undefined
      ? null : indexed.get(Number(point.time)) || null));

    let timer: ReturnType<typeof setTimeout> | undefined;
    let revision = 0;
    let lastRequest = "";
    const onRange = (range: ChartRange | null) => {
      const desiredRevision = ++revision;
      if (!range || !loadRange) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        const minimum = Number(range.from);
        const maximum = Number(range.to);
        if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || maximum <= minimum) return;
        const key = `${Math.round(minimum)}:${Math.round(maximum)}`;
        if (key === lastRequest) return;
        lastRequest = key;
        try {
          const detailed = sortedBars(await loadRange(minimum * 1000, maximum * 1000, 2400));
          if (desiredRevision !== revision) return;
          if (!detailed.length) {
            lastRequest = "";
            return;
          }
          cached = sortedBars(mergeBars(cached, detailed));
          const visible = chart.timeScale().getVisibleRange();
          indexed = apply(cached);
          if (visible) chart.timeScale().setVisibleRange(visible);
          setError("");
        } catch (reason) {
          if (desiredRevision === revision) {
            lastRequest = "";
            setError(reason instanceof Error ? reason.message : String(reason));
          }
        }
      }, 180);
    };
    chart.timeScale().subscribeVisibleTimeRangeChange(onRange);
    onReady?.((minimum, maximum) => {
      if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || maximum <= minimum) return;
      chart.timeScale().setVisibleRange({from: Math.floor(minimum / 1000),
        to: Math.ceil(maximum / 1000)});
    });
    return () => {
      revision += 1;
      if (timer) clearTimeout(timer);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(onRange);
      chart.remove();
    };
  }, [bars, loadRange]);

  return <div className="ft-lightweight-price">
    <div ref={chartNode} className="ft-lightweight-price-canvas"
      aria-label={translate("行情 K 线、成交量和持仓量")} />
    {selected && <section className="ft-chart-inspector ft-lightweight-price-detail">
      <strong>{new Date(selected.timestamp).toLocaleString()}</strong>
      <dl>{[["开盘价", selected.open], ["最高价", selected.high],
        ["最低价", selected.low], ["收盘价", selected.close],
        ["成交量", selected.volume ?? "—"], ["持仓量", selected.openInterest ?? "—"]]
        .map(([label, value]) => <div key={label}>
          <dt>{translate(String(label))}</dt><dd>{value}</dd>
        </div>)}</dl>
    </section>}
    {error && <p role="status" className="ft-lightweight-price-error">{error}</p>}
  </div>;
}

type PriceChartHandle = (() => void) & {
  focusRange: (minimum: number, maximum: number) => void;
};

export function mountPriceChart(target: HTMLElement, options: Options): PriceChartHandle {
  roots.get(target)?.unmount();
  const root = createRoot(target);
  roots.set(target, root);
  let focus: ((minimum: number, maximum: number) => void) | null = null;
  let pending: [number, number] | null = null;
  root.render(<MarketChart {...options} onReady={ready => {
    focus = ready;
    if (pending) { ready(...pending); pending = null; }
  }} />);
  const dispose = (() => {
    if (roots.get(target) === root) {
      root.unmount();
      roots.delete(target);
    }
    focus = null;
    pending = null;
  }) as PriceChartHandle;
  dispose.focusRange = (minimum, maximum) => {
    if (focus) focus(minimum, maximum);
    else pending = [minimum, maximum];
  };
  return dispose;
}
