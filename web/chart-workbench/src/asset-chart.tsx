import {useEffect, useRef, useState} from "react";
import {createRoot, type Root} from "react-dom/client";
import {mergeBars} from "./range-data";
import {ChartPopover, type ChartSelection} from "./chart-popover";

type Bar = {timestamp: number; open: number; high: number; low: number; close: number;
  volume: number | null; openInterest: number | null};
type Event = {timestamp: number; artifact: string; orderID: string; side: string;
  stage: string; id: string; fillPrice: number | null; fields: [string, string][];
  raw: unknown};
type Data = {bars: Bar[]; events: Event[]};
type Indicator = {id: string; label: string; formula?: string;
  points: {timestamp: number; value: number | null}[]};
type Range = {from: number; to: number};
type RollSwitch = {timestamp: number; label: string};
type Marker = {time: number; position: string; shape: string; color: string;
  id: string; size?: number};
type Series = {setData: (rows: unknown[]) => void; data: () => {time: number}[];
  createPriceLine: (options: object) => unknown;
  removePriceLine: (line: unknown) => void; priceScale: () => {applyOptions: (options: object) => void}};
type Chart = {addSeries: (kind: unknown, options: object, pane?: number) => Series;
  removeSeries: (series: Series) => void;
  panes: () => {setStretchFactor: (value: number) => void}[];
  timeScale: () => {fitContent: () => void; setVisibleRange: (range: Range) => void;
    width: () => number; logicalToCoordinate: (logical: number) => number | null;
    subscribeVisibleTimeRangeChange: (handler: (range: Range | null) => void) => void;
    unsubscribeVisibleTimeRangeChange: (handler: (range: Range | null) => void) => void};
  subscribeClick: (handler: (point: {time?: number; point?: ChartSelection;
    hoveredInfo?: {objectId?: unknown}}) => void) => void;
  remove: () => void};
type MarkerPlugin = {setMarkers: (markers: Marker[]) => void};
type Library = {createChart: (element: HTMLElement, options: object) => Chart;
  createSeriesMarkers: (series: Series, markers: Marker[], options?: object) => MarkerPlugin;
  CandlestickSeries: unknown; HistogramSeries: unknown; LineSeries: unknown};
type Options = {bars: Bar[]; events: Event[]; indicators?: Indicator[]; frequencyMs: number;
  runWindow?: {start: number; end: number}; rollSwitches?: RollSwitch[];
  loadRange: (minimum: number, maximum: number, maxPoints: number) => Promise<Data | null>;
  translate?: (value: string) => string};

const roots = new WeakMap<HTMLElement, Root>();
const indicatorColors = ["#8e44ad", "#2563eb", "#0d9488", "#db2777"];
const library = () => (window as unknown as {LightweightCharts?: Library}).LightweightCharts;
function IndicatorFormula({latex}: {latex: string}) {
  const node = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!node.current) return;
    const ui = (window as unknown as {FTUI?: {renderMath?: (
      target: HTMLElement, formula: string, options?: {display?: boolean}) => void}}).FTUI;
    if (ui?.renderMath) ui.renderMath(node.current, latex);
    else node.current.textContent = latex;
  }, [latex]);
  return <span ref={node} className="ft-asset-indicator-formula" />;
}
const seconds = (milliseconds: number) => Math.floor(milliseconds / 1000);
const valid = (bar: Bar) => Number.isFinite(bar.timestamp)
  && [bar.open, bar.high, bar.low, bar.close].every(Number.isFinite);

function orderedBars(source: Bar[]): Bar[] {
  const bySecond = new Map<number, Bar>();
  for (const bar of source) if (valid(bar)) bySecond.set(seconds(bar.timestamp), bar);
  return [...bySecond.entries()].sort(([a], [b]) => a - b).map(([, bar]) => bar);
}

function windowTicks(start: number, end: number, frequencyMs: number) {
  const span = end - start;
  const base = Math.max(1000, frequencyMs);
  const step = Math.ceil(span / 1200 / base) * base;
  const ticks: {time: number; value?: number}[] = [{time: seconds(start), value: 0}];
  for (let time = start + step; time < end; time += step) {
    const tick = seconds(time);
    if (tick > ticks[ticks.length - 1].time) ticks.push({time: tick});
  }
  ticks.push({time: seconds(end), value: 0});
  return ticks;
}

function logicalAtTime(times: number[], time: number): number {
  if (!times.length || time <= times[0]) return 0;
  if (time >= times[times.length - 1]) return times.length - 1;
  let low = 0; let high = times.length - 1;
  while (low + 1 < high) {
    const middle = (low + high) >>> 1;
    if (times[middle] <= time) low = middle;
    else high = middle;
  }
  return low + (time - times[low]) / (times[high] - times[low]);
}

function mergeEvents(current: Event[], incoming: Event[]): Event[] {
  const byIdentity = new Map<string, Event>();
  for (const event of [...current, ...incoming]) {
    byIdentity.set(JSON.stringify([event.artifact, event.id, event.timestamp,
      event.orderID, event.stage]), event);
  }
  return [...byIdentity.values()].sort((left, right) => left.timestamp - right.timestamp);
}

function nearestBar(bars: Bar[], timestamp: number, toleranceMs: number): Bar | null {
  let low = 0; let high = bars.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (bars[middle].timestamp < timestamp) low = middle + 1;
    else high = middle;
  }
  const candidates = [bars[low], bars[low - 1]].filter(Boolean);
  const nearest = candidates.sort((a, b) => Math.abs(a.timestamp - timestamp)
    - Math.abs(b.timestamp - timestamp))[0];
  return nearest && Math.abs(nearest.timestamp - timestamp) <= toleranceMs ? nearest : null;
}

function fillKind(event: Event): "buy" | "sell" | "other" {
  if (/^(buy|long|b|买)/i.test(event.side)) return "buy";
  if (/^(sell|short|s|卖)/i.test(event.side)) return "sell";
  return "other";
}

function fillMarkers(bars: Bar[], events: Event[], toleranceMs: number) {
  const groups = new Map<string, {bar: Bar; kind: string; items: Event[]}>();
  for (const event of events) {
    if (event.artifact !== "fill_detail_data") continue;
    const bar = nearestBar(bars, event.timestamp, toleranceMs);
    if (!bar) continue;
    const kind = fillKind(event);
    const key = `${seconds(bar.timestamp)}:${kind}`;
    if (!groups.has(key)) groups.set(key, {bar, kind, items: []});
    groups.get(key)!.items.push(event);
  }
  const items = new Map<string, Event[]>();
  const markers = [...groups.entries()].map(([id, group]) => {
    items.set(id, group.items);
    return {id, time: seconds(group.bar.timestamp),
      position: group.kind === "sell" ? "aboveBar" : "belowBar",
      shape: group.kind === "sell" ? "arrowDown" : "arrowUp",
      color: group.kind === "sell" ? "#dc2626"
        : group.kind === "buy" ? "#16a34a" : "#2563eb", size: 1};
  });
  markers.sort((a, b) => a.time - b.time);
  return {markers, items};
}

function phase(event: Event): {shape: string; color: string} {
  const stage = event.stage;
  if (stage.includes("撤单")) return {shape: "square", color: "#dc2626"};
  if (stage.includes("改单")) return {shape: "square", color: "#2563eb"};
  if (stage.includes("撮合")) return {shape: "square", color: "#d97706"};
  return {shape: "square", color: "#64748b"};
}

function orderMarkers(bars: Bar[], events: Event[], toleranceMs: number) {
  const groups = new Map<string, {bar: Bar; items: Event[]}>();
  for (const event of events) {
    if (event.artifact === "fill_detail_data") continue;
    const bar = nearestBar(bars, event.timestamp, toleranceMs);
    if (!bar) continue;
    const id = `order:${seconds(bar.timestamp)}`;
    if (!groups.has(id)) groups.set(id, {bar, items: []});
    groups.get(id)!.items.push(event);
  }
  const items = new Map<string, Event[]>();
  const markers = [...groups].map(([id, group]) => {
    items.set(id, group.items);
    return {id, time: seconds(group.bar.timestamp), position: "aboveBar",
      ...phase(group.items[0]), size: 0.45};
  });
  return {items, markers};
}

function AssetChart({bars, events, indicators = [], frequencyMs, runWindow,
  rollSwitches = [], loadRange,
  translate = value => value}: Options) {
  const node = useRef<HTMLDivElement>(null);
  const chart = useRef<Chart | null>(null);
  const candle = useRef<Series | null>(null);
  const windowAxis = useRef<Series | null>(null);
  const plotTimes = useRef<number[]>([]);
  const volume = useRef<Series | null>(null);
  const interest = useRef<Series | null>(null);
  const fillPlugin = useRef<MarkerPlugin | null>(null);
  const indicatorSeries = useRef<Series[]>([]);
  const priceLines = useRef<unknown[]>([]);
  const markerItems = useRef(new Map<string, Event[]>());
  const barIndex = useRef(new Map<number, Bar>());
  const [data, setData] = useState<Data>({bars, events});
  const [selected, setSelected] = useState<{kind: "market" | "event";
    bar?: Bar; items?: Event[]; anchor: ChartSelection} | null>(null);
  const [selectedPrices, setSelectedPrices] = useState<number[]>([]);
  const [error, setError] = useState("");
  const request = useRef(loadRange);
  const view = useRef<Range | null>(null);
  const requestKey = useRef("");
  const generation = useRef(0);
  const applyingData = useRef(false);
  const drawRolls = useRef<() => void>(() => {});
  request.current = loadRange;

  useEffect(() => {
    const api = library();
    if (!api || !node.current) return;
    const instance = api.createChart(node.current, {
      autoSize: true, height: 640, attributionLogo: true,
      layout: {background: {color: "#fff"}, textColor: "#5f6672",
        panes: {enableResize: false}},
      grid: {vertLines: {color: "#edf0f4"}, horzLines: {color: "#edf0f4"}},
      timeScale: {timeVisible: true, secondsVisible: true, rightOffset: 5,
        tickMarkFormatter: (time: number, kind: number, locale: string) => {
          const date = new Date(Number(time) * 1000);
          return date.toLocaleString(locale, kind < 3
            ? {month: "numeric", day: "numeric"}
            : {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
        }},
      localization: {timeFormatter: (time: number) =>
        new Date(Number(time) * 1000).toLocaleString()},
      handleScale: {mouseWheel: true, pinch: true, axisPressedMouseMove: true},
      handleScroll: {mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true},
    });
    chart.current = instance;
    const rollLayer = document.createElement("div");
    rollLayer.className = "ft-asset-roll-switches";
    node.current.append(rollLayer);
    drawRolls.current = () => {
      const times = plotTimes.current;
      const scale = instance.timeScale();
      rollLayer.style.width = `${scale.width()}px`;
      rollLayer.replaceChildren();
      if (times.length < 2) return;
      for (const item of rollSwitches) {
        const coordinate = scale.logicalToCoordinate(logicalAtTime(times,
          seconds(item.timestamp)));
        if (coordinate === null || coordinate < 0 || coordinate > scale.width()) continue;
        const marker = document.createElement("div");
        marker.className = "ft-asset-roll-switch";
        marker.style.left = `${coordinate}px`;
        marker.title = `${translate("主力切换至")} ${item.label}`;
        const label = document.createElement("span");
        label.textContent = `${translate("换主力")} · ${item.label}`;
        marker.append(label);
        rollLayer.append(marker);
      }
    };
    const resizeObserver = typeof ResizeObserver === "undefined" ? null
      : new ResizeObserver(() => drawRolls.current());
    resizeObserver?.observe(node.current);
    candle.current = instance.addSeries(api.CandlestickSeries, {
      upColor: "#19a47b", downColor: "#e14f5b", borderVisible: false,
      wickUpColor: "#19a47b", wickDownColor: "#e14f5b",
    });
    // Lightweight Charts drops whitespace-only candlestick data. A hidden
    // series owns the run boundaries so empty contracts still retain the
    // configured backtest interval without fabricating an OHLC bar.
    windowAxis.current = instance.addSeries(api.LineSeries, {
      visible: false, priceLineVisible: false, lastValueVisible: false,
    });
    volume.current = instance.addSeries(api.HistogramSeries, {
      priceFormat: {type: "volume"}, priceLineVisible: false,
    }, 1);
    interest.current = instance.addSeries(api.LineSeries, {
      color: "#805bd6", lineWidth: 2, priceLineVisible: false,
    }, 2);
    for (const [index, item] of indicators.entries()) {
      const series = instance.addSeries(api.LineSeries, {
        color: indicatorColors[index % indicatorColors.length],
        lineWidth: 2, priceLineVisible: false, title: `F${index + 1}`,
      }, index + 3);
      series.setData(item.points.filter(point => point.value !== null
        && Number.isFinite(point.value) && Number.isFinite(point.timestamp))
        .map(point => ({time: seconds(point.timestamp), value: point.value})));
      indicatorSeries.current.push(series);
    }
    fillPlugin.current = api.createSeriesMarkers(candle.current, [], {autoScale: true});
    instance.subscribeClick(point => {
      if (!point?.point) return;
      const id = String(point?.hoveredInfo?.objectId ?? "");
      const items = markerItems.current.get(id);
      if (items) {
        setSelected({kind: "event", items, anchor: point.point});
      } else if (point?.time !== undefined) {
        const bar = barIndex.current.get(Number(point.time));
        if (bar) setSelected({kind: "market", bar, anchor: point.point});
      }
    });
    let timer: ReturnType<typeof setTimeout> | undefined;
    let skipInitialRange = true;
    const onRange = (range: Range | null) => {
      drawRolls.current();
      if (applyingData.current) return;
      if (timer) clearTimeout(timer);
      if (!range) return;
      view.current = range;
      if (skipInitialRange) {
        skipInitialRange = false;
        return;
      }
      const revision = ++generation.current;
      timer = setTimeout(async () => {
        const minimum = Number(range.from) * 1000;
        const maximum = Number(range.to) * 1000;
        if (!Number.isFinite(minimum) || !Number.isFinite(maximum)
          || maximum <= minimum) return;
        const key = `${Math.round(minimum)}:${Math.round(maximum)}`;
        if (key === requestKey.current) return;
        requestKey.current = key;
        try {
          const result = await request.current(minimum, maximum, 2400);
          if (revision !== generation.current) return;
          if (result) {
            setData(previous => ({bars: mergeBars(previous.bars, result.bars),
              events: mergeEvents(previous.events, result.events)}));
            setError("");
          } else requestKey.current = "";
        } catch (cause) {
          if (revision !== generation.current) return;
          requestKey.current = "";
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      }, 160);
    };
    instance.timeScale().subscribeVisibleTimeRangeChange(onRange);
    return () => {
      generation.current += 1;
      if (timer) clearTimeout(timer);
      instance.timeScale().unsubscribeVisibleTimeRangeChange(onRange);
      resizeObserver?.disconnect();
      rollLayer.remove();
      instance.remove();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = chart.current;
    if (!instance || !candle.current || !volume.current || !interest.current) return;
    const rows = orderedBars(data.bars);
    const oldView = view.current;
    const boundaries = runWindow && Number.isFinite(runWindow.start)
      && Number.isFinite(runWindow.end) && runWindow.end > runWindow.start
      ? [seconds(runWindow.start), seconds(runWindow.end)] : [];
    const candleRows = rows.map(bar => ({time: seconds(bar.timestamp),
      open: bar.open, high: bar.high, low: bar.low, close: bar.close}));
    applyingData.current = true;
    const ticks = boundaries.length === 2
      ? windowTicks(runWindow!.start, runWindow!.end, frequencyMs) : [];
    plotTimes.current = [...new Set([...candleRows.map(item => item.time),
      ...ticks.map(item => item.time)])].sort((a, b) => a - b);
    windowAxis.current?.setData(ticks);
    candle.current.setData(candleRows);
    volume.current.setData(rows.filter(bar => bar.volume !== null).map(bar => ({
      time: seconds(bar.timestamp), value: bar.volume,
      color: bar.close >= bar.open ? "#a9d8c9" : "#efb4b9",
    })));
    interest.current.setData(rows.filter(bar => bar.openInterest !== null).map(bar => ({
      time: seconds(bar.timestamp), value: bar.openInterest,
    })));
    barIndex.current = new Map(rows.map(bar => [seconds(bar.timestamp), bar]));
    const itemMap = new Map<string, Event[]>();
    const fills = fillMarkers(rows, data.events, frequencyMs);
    const orders = orderMarkers(rows, data.events, frequencyMs);
    for (const [key, items] of fills.items) itemMap.set(key, items);
    for (const [key, items] of orders.items) itemMap.set(key, items);
    fillPlugin.current?.setMarkers([...fills.markers, ...orders.markers]
      .sort((left, right) => left.time - right.time));
    instance.panes()[0]?.setStretchFactor(5.5);
    instance.panes()[1]?.setStretchFactor(1.3);
    instance.panes()[2]?.setStretchFactor(1.3);
    for (let index = 3; index < instance.panes().length; index += 1) {
      instance.panes()[index]?.setStretchFactor(1.5);
    }
    markerItems.current = itemMap;
    if (oldView) instance.timeScale().setVisibleRange(oldView);
    else if (boundaries.length === 2) {
      const full = {from: boundaries[0], to: boundaries[1]};
      instance.timeScale().setVisibleRange(full);
      view.current = full;
    } else instance.timeScale().fitContent();
    applyingData.current = false;
    drawRolls.current();
  }, [data, frequencyMs, runWindow]);

  useEffect(() => {
    const series = candle.current;
    if (!series) return;
    for (const line of priceLines.current) series.removePriceLine(line);
    priceLines.current = selectedPrices.map(price => series.createPriceLine({price,
      color: "#2563eb", lineWidth: 1, lineStyle: 2, axisLabelVisible: true,
      title: `${translate("成交价")} ${price}`}));
  }, [selectedPrices, translate]);

  return <div className="ft-asset-chart-workbench">
    {indicators.length > 0 && <details className="ft-asset-indicator-list">
      <summary>{translate("因子曲线")} · {indicators.length}</summary>
      <ol>{indicators.map((item, index) => <li key={`${item.id}:${index}`}>
        <span className="ft-asset-indicator-swatch"
          style={{backgroundColor: indicatorColors[index % indicatorColors.length]}} />
        <strong>F{index + 1}</strong>
        <span className="ft-asset-indicator-name">{item.label}</span>
        {item.formula && <IndicatorFormula latex={item.formula} />}
      </li>)}</ol>
    </details>}
    <div className="ft-chart-popover-host">
      <div ref={node} className="ft-asset-chart-canvas"
        style={{height: Math.max(640, 450 + indicators.length * 120)}}
        aria-label={translate("行情、交易和订单历史图")} />
      {selected && <ChartPopover anchor={selected.anchor}
        title={selected.kind === "market" && selected.bar
          ? new Date(selected.bar.timestamp).toLocaleString()
          : `${translate("交易事件")} · ${selected.items?.length ?? 0}`}
        onClose={() => setSelected(null)}>
      {selected.kind === "market" && selected.bar &&
        <dl>{[["开盘价", selected.bar.open], ["最高价", selected.bar.high],
          ["最低价", selected.bar.low], ["收盘价", selected.bar.close],
          ["成交量", selected.bar.volume ?? "—"], ["持仓量", selected.bar.openInterest ?? "—"]]
          .map(([label, value]) => <div key={label}>
            <dt>{translate(String(label))}</dt><dd>{value}</dd>
          </div>)}</dl>}
      {selected.kind === "event" && selected.items?.map((item, index) =>
        <details key={`${item.id}:${index}`}
        ref={element => {
          if (element && !element.dataset.initialized) {
            element.open = index === 0;
            element.dataset.initialized = "1";
          }
        }}>
        <summary>{translate(item.stage)} · {item.id}</summary>
        <dl>{item.fields.map(([label, value], fieldIndex) => <div key={fieldIndex}>
          <dt>{translate(label)}</dt><dd>{value}</dd></div>)}</dl>
        {item.artifact === "fill_detail_data" && item.fillPrice !== null
          && <button type="button" onClick={() => setSelectedPrices(prices =>
            prices.includes(item.fillPrice!) ? prices.filter(price => price !== item.fillPrice)
              : [...prices, item.fillPrice!])}>
            {selectedPrices.includes(item.fillPrice)
              ? translate("移除价格线") : translate("显示价格线")} · {item.fillPrice}
          </button>}
      </details>)}
      </ChartPopover>}
    </div>
    {error && <p role="status" className="ft-lightweight-price-error">{error}</p>}
  </div>;
}

export function mountAssetChart(target: HTMLElement, options: Options): () => void {
  roots.get(target)?.unmount();
  const root = createRoot(target);
  roots.set(target, root);
  root.render(<AssetChart {...options} />);
  return () => {
    if (roots.get(target) === root) {
      root.unmount();
      roots.delete(target);
    }
  };
}
