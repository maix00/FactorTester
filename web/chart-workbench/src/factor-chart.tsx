import {useEffect, useRef, useState} from "react";
import {createRoot, type Root} from "react-dom/client";
import {mergeBars} from "./range-data";
import {ChartPopover, type ChartSelection} from "./chart-popover";

type Bar = {timestamp: number; open: number; high: number; low: number; close: number;
  volume: number | null; openInterest: number | null};
type Point = {timestamp: number; value: number | null};
type Indicator = {id: string; label: string; points: Point[]};
type Range = {from: number; to: number};
type Series = {setData: (data: unknown[]) => void;
  applyOptions: (options: object) => void};
type Pane = {setStretchFactor: (weight: number) => void};
type Chart = {addSeries: (type: unknown, options: object, pane?: number) => Series;
  panes: () => Pane[]; timeScale: () => {
    fitContent: () => void; setVisibleRange: (range: Range) => void;
    getVisibleRange: () => Range | null;
    subscribeVisibleTimeRangeChange: (callback: (range: Range | null) => void) => void;
    unsubscribeVisibleTimeRangeChange: (callback: (range: Range | null) => void) => void;
  }; subscribeClick: (callback: (point: {time?: number; point?: ChartSelection}) => void) => void;
  remove: () => void};
type Library = {createChart: (node: HTMLElement, options: object) => Chart;
  CandlestickSeries: unknown; HistogramSeries: unknown; LineSeries: unknown};
type Options = {bars: Bar[]; indicators: Indicator[]; product: string;
  loadRange: (minimum: number, maximum: number, maxPoints: number) => Promise<Bar[] | null>;
  translate?: (value: string) => string};
type Controller = {dispose: () => void; setVisibleRange: (minimum: number, maximum: number) => void};

const roots = new WeakMap<HTMLElement, Root>();
const disposers = new WeakMap<HTMLElement, () => void>();
const indicatorColors = ["#8e44ad", "#2563eb", "#0d9488", "#db2777", "#d97706"];
const seconds = (milliseconds: number) => Math.floor(milliseconds / 1000);
const library = () => (window as unknown as {LightweightCharts?: Library}).LightweightCharts;

function normalizeBars(bars: Bar[]): Bar[] {
  const entries = new Map<number, Bar>();
  for (const bar of bars) {
    if (Number.isFinite(bar.timestamp) && [bar.open, bar.high, bar.low, bar.close]
      .every(Number.isFinite)) entries.set(seconds(bar.timestamp), bar);
  }
  return [...entries].sort(([left], [right]) => left - right).map(([, bar]) => bar);
}

function normalizedPoints(points: Point[]) {
  const entries = new Map<number, number | null>();
  for (const point of points) {
    if (Number.isFinite(point.timestamp)) entries.set(seconds(point.timestamp),
      point.value !== null && Number.isFinite(point.value) ? point.value : null);
  }
  return [...entries].sort(([left], [right]) => left - right).map(([time, value]) =>
    value === null ? {time} : {time, value});
}

function FactorChart({bars, indicators, product, loadRange, controller,
  translate = value => value}: Options & {controller: {current: Chart | null}}) {
  const chartNode = useRef<HTMLDivElement>(null);
  const chart = useRef<Chart | null>(null);
  const sourceBars = useRef(normalizeBars(bars));
  const candle = useRef<Series | null>(null);
  const volume = useRef<Series | null>(null);
  const interest = useRef<Series | null>(null);
  const indicatorSeries = useRef(new Map<string, Series>());
  const [visible, setVisible] = useState(() => new Set(indicators.map(item => item.id)));
  const [selected, setSelected] = useState<{
    timestamp: number; rows: [string, string][]; anchor: ChartSelection;
  } | null>(null);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const requestKey = useRef("");
  const request = useRef(loadRange);
  request.current = loadRange;

  useEffect(() => {
    const api = library();
    if (!api || !chartNode.current) return;
    const instance = api.createChart(chartNode.current, {
      autoSize: true, attributionLogo: true,
      layout: {background: {color: "#fff"}, textColor: "#5f6672",
        panes: {enableResize: true}},
      grid: {vertLines: {color: "#edf0f4"}, horzLines: {color: "#edf0f4"}},
      timeScale: {timeVisible: true, secondsVisible: true, rightOffset: 6,
        tickMarkFormatter: (time: number, kind: number, locale: string) =>
          new Date(Number(time) * 1000).toLocaleString(locale, kind < 3
            ? {month: "numeric", day: "numeric"}
            : {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false})},
      localization: {timeFormatter: (time: number) =>
        new Date(Number(time) * 1000).toLocaleString()},
      handleScale: {mouseWheel: true, pinch: true, axisPressedMouseMove: true},
      handleScroll: {mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true},
    });
    chart.current = instance;
    controller.current = instance;
    candle.current = instance.addSeries(api.CandlestickSeries, {
      upColor: "#19a47b", downColor: "#e14f5b", borderVisible: false,
      wickUpColor: "#19a47b", wickDownColor: "#e14f5b",
    });
    const hasVolume = sourceBars.current.some(bar => bar.volume !== null);
    const hasInterest = sourceBars.current.some(bar => bar.openInterest !== null);
    let pane = 1;
    for (const [index, item] of indicators.entries()) {
      const series = instance.addSeries(api.LineSeries, {
        color: indicatorColors[index % indicatorColors.length], lineWidth: 2,
        priceLineVisible: false, title: item.label,
      }, pane++);
      series.setData(normalizedPoints(item.points));
      indicatorSeries.current.set(item.id, series);
    }
    if (hasVolume) volume.current = instance.addSeries(api.HistogramSeries,
      {color: "#8aa4c8", priceFormat: {type: "volume"}, priceLineVisible: false}, pane++);
    if (hasInterest) interest.current = instance.addSeries(api.LineSeries,
      {color: "#d97706", lineWidth: 2, priceLineVisible: false}, pane);
    instance.panes()[0]?.setStretchFactor(4);
    for (let index = 1; index < instance.panes().length; index += 1) {
      instance.panes()[index]?.setStretchFactor(index <= indicators.length ? 1.8 : 1);
    }
    const applyBars = (source: Bar[]) => {
      sourceBars.current = normalizeBars(source);
      const rows = sourceBars.current;
      candle.current?.setData(rows.map(bar => ({time: seconds(bar.timestamp),
        open: bar.open, high: bar.high, low: bar.low, close: bar.close})));
      volume.current?.setData(rows.filter(bar => bar.volume !== null).map(bar => ({
        time: seconds(bar.timestamp), value: bar.volume})));
      interest.current?.setData(rows.filter(bar => bar.openInterest !== null).map(bar => ({
        time: seconds(bar.timestamp), value: bar.openInterest})));
    };
    applyBars(bars);
    instance.timeScale().fitContent();
    instance.subscribeClick(point => {
      if (point.time === undefined || !point.point) return;
      const time = Number(point.time);
      const bar = sourceBars.current.find(item => seconds(item.timestamp) === time);
      const rows: [string, string][] = [];
      if (bar) {
        rows.push([translate("开盘价"), String(bar.open)]);
        rows.push([translate("最高价"), String(bar.high)]);
        rows.push([translate("最低价"), String(bar.low)]);
        rows.push([translate("收盘价"), String(bar.close)]);
        rows.push([translate("成交量"), String(bar.volume ?? "—")]);
        rows.push([translate("持仓量"), String(bar.openInterest ?? "—")]);
      }
      for (const item of indicators) {
        const value = item.points.find(value => seconds(value.timestamp) === time);
        if (value) rows.push([item.label, String(value.value ?? "—")]);
      }
      if (rows.length) setSelected({timestamp: time * 1000, rows, anchor: point.point});
    });
    let timer: ReturnType<typeof setTimeout> | undefined;
    let initial = true;
    const onRange = (range: Range | null) => {
      if (timer) clearTimeout(timer);
      if (!range) return;
      if (initial) { initial = false; return; }
      const current = ++generation.current;
      timer = setTimeout(async () => {
        const minimum = Number(range.from) * 1000;
        const maximum = Number(range.to) * 1000;
        if (!Number.isFinite(minimum) || !Number.isFinite(maximum)
          || maximum <= minimum) return;
        const key = `${Math.round(minimum)}:${Math.round(maximum)}`;
        if (key === requestKey.current) return;
        requestKey.current = key;
        try {
          const updated = await request.current(minimum, maximum, 5000);
          if (current !== generation.current || !updated) return;
          const visible = instance.timeScale().getVisibleRange();
          applyBars(mergeBars(sourceBars.current, updated));
          if (visible) instance.timeScale().setVisibleRange(visible);
          setError("");
        } catch (cause) {
          if (current === generation.current) {
            requestKey.current = "";
            setError(String(cause));
          }
        }
      }, 160);
    };
    instance.timeScale().subscribeVisibleTimeRangeChange(onRange);
    return () => {
      generation.current += 1;
      if (timer) clearTimeout(timer);
      instance.timeScale().unsubscribeVisibleTimeRangeChange(onRange);
      instance.remove();
      chart.current = null;
      controller.current = null;
    };
  }, []);

  useEffect(() => {
    for (const [id, series] of indicatorSeries.current) {
      series.applyOptions({visible: visible.has(id)});
    }
  }, [visible]);

  return <div className="ft-factor-workbench">
    <div className="ft-factor-indicators" aria-label={translate("因子指标")}>
      {indicators.map((item, index) => <label key={item.id}>
        <input type="checkbox" checked={visible.has(item.id)} onChange={() => setVisible(previous => {
          const next = new Set(previous);
          if (next.has(item.id)) next.delete(item.id); else next.add(item.id);
          return next;
        })} /><span aria-hidden="true" className="ft-factor-indicator-swatch"
          style={{backgroundColor: indicatorColors[index % indicatorColors.length]}} />
        {item.label}</label>)}
    </div>
    <div className="ft-chart-popover-host">
      <div ref={chartNode} className="ft-factor-chart-canvas"
        style={{height: Math.max(620, 340 + indicators.length * 130)}}
        aria-label={`${product} · ${translate("价格与因子指标")}`} />
      {selected && <ChartPopover anchor={selected.anchor}
        title={new Date(selected.timestamp).toLocaleString()}
        onClose={() => setSelected(null)}>
        <dl>{selected.rows.map(([label, value]) => <div key={label}>
          <dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      </ChartPopover>}
    </div>
    {error && <p role="status">{error}</p>}
  </div>;
}

export function mountFactorChart(target: HTMLElement, options: Options): Controller {
  disposers.get(target)?.();
  const root = createRoot(target);
  roots.set(target, root);
  const controller = {current: null as Chart | null};
  root.render(<FactorChart {...options} controller={controller} />);
  const observer = new MutationObserver(() => {
    if (!target.isConnected) dispose();
  });
  observer.observe(document.body, {childList: true, subtree: true});
  const dispose = () => {
    observer.disconnect();
    if (roots.get(target) === root) { root.unmount(); roots.delete(target); }
    if (disposers.get(target) === dispose) disposers.delete(target);
  };
  disposers.set(target, dispose);
  return {
    dispose,
    setVisibleRange: (minimum, maximum) => controller.current?.timeScale().setVisibleRange({
      from: seconds(minimum), to: seconds(maximum),
    }),
  };
}
