import {useEffect, useRef, useState} from "react";
import {createRoot, type Root} from "react-dom/client";

type Bar = {timestamp: number; open: number; high: number; low: number; close: number;
  volume: number | null; openInterest: number | null};
type Event = {timestamp: number; artifact: string; orderID: string; side: string;
  stage: string; id: string; fillPrice: number | null; fields: [string, string][];
  raw: unknown};
type Data = {bars: Bar[]; events: Event[]};
type Range = {from: number; to: number};
type Marker = {time: number; position: string; shape: string; color: string;
  id: string; size?: number};
type Series = {setData: (rows: unknown[]) => void; createPriceLine: (options: object) => unknown;
  removePriceLine: (line: unknown) => void; priceScale: () => {applyOptions: (options: object) => void}};
type Chart = {addSeries: (kind: unknown, options: object, pane?: number) => Series;
  removeSeries: (series: Series) => void;
  panes: () => {setStretchFactor: (value: number) => void}[];
  timeScale: () => {fitContent: () => void; setVisibleRange: (range: Range) => void;
    subscribeVisibleTimeRangeChange: (handler: (range: Range | null) => void) => void;
    unsubscribeVisibleTimeRangeChange: (handler: (range: Range | null) => void) => void};
  subscribeClick: (handler: (point: {time?: number; hoveredInfo?: {objectId?: unknown}}) => void) => void;
  remove: () => void};
type MarkerPlugin = {setMarkers: (markers: Marker[]) => void};
type Library = {createChart: (element: HTMLElement, options: object) => Chart;
  createSeriesMarkers: (series: Series, markers: Marker[], options?: object) => MarkerPlugin;
  CandlestickSeries: unknown; HistogramSeries: unknown; LineSeries: unknown};
type Options = {bars: Bar[]; events: Event[]; frequencyMs: number;
  loadRange: (minimum: number, maximum: number, maxPoints: number) => Promise<Data | null>;
  onEventClick?: (events: unknown[]) => void; translate?: (value: string) => string};

const roots = new WeakMap<HTMLElement, Root>();
const library = () => (window as unknown as {LightweightCharts?: Library}).LightweightCharts;
const seconds = (milliseconds: number) => Math.floor(milliseconds / 1000);
const valid = (bar: Bar) => Number.isFinite(bar.timestamp)
  && [bar.open, bar.high, bar.low, bar.close].every(Number.isFinite);

function orderedBars(source: Bar[]): Bar[] {
  const bySecond = new Map<number, Bar>();
  for (const bar of source) if (valid(bar)) bySecond.set(seconds(bar.timestamp), bar);
  return [...bySecond.entries()].sort(([a], [b]) => a - b).map(([, bar]) => bar);
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

function orderRows(events: Event[], limit: number) {
  const orders = new Map<string, Event[]>();
  for (const event of events) {
    if (!event.orderID) continue;
    if (!orders.has(event.orderID)) orders.set(event.orderID, []);
    orders.get(event.orderID)!.push(event);
  }
  return {total: orders.size, rows: [...orders].sort((a, b) =>
    Math.max(...b[1].map(item => item.timestamp))
    - Math.max(...a[1].map(item => item.timestamp))).slice(0, limit)};
}

function phase(event: Event): {shape: string; color: string} {
  if (event.artifact === "fill_detail_data") return {shape: "circle", color: "#16a34a"};
  const stage = event.stage;
  if (stage.includes("撤单")) return {shape: "arrowDown", color: "#dc2626"};
  if (stage.includes("改单")) return {shape: "square", color: "#2563eb"};
  if (stage.includes("撮合")) return {shape: "circle", color: "#d97706"};
  return {shape: "circle", color: "#64748b"};
}

function AssetChart({bars, events, frequencyMs, loadRange, onEventClick,
  translate = value => value}: Options) {
  const node = useRef<HTMLDivElement>(null);
  const chart = useRef<Chart | null>(null);
  const candle = useRef<Series | null>(null);
  const volume = useRef<Series | null>(null);
  const interest = useRef<Series | null>(null);
  const fillPlugin = useRef<MarkerPlugin | null>(null);
  const orderSeries = useRef<Series[]>([]);
  const priceLines = useRef<unknown[]>([]);
  const markerItems = useRef(new Map<string, Event[]>());
  const barIndex = useRef(new Map<number, Bar>());
  const [data, setData] = useState<Data>({bars, events});
  const [orderLimit, setOrderLimit] = useState(10);
  const [selected, setSelected] = useState<{kind: "market" | "event";
    bar?: Bar; items?: Event[]} | null>(null);
  const [selectedPrices, setSelectedPrices] = useState<number[]>([]);
  const [orderTotal, setOrderTotal] = useState(0);
  const [error, setError] = useState("");
  const request = useRef(loadRange);
  const eventClick = useRef(onEventClick);
  const view = useRef<Range | null>(null);
  const requestKey = useRef("");
  const generation = useRef(0);
  request.current = loadRange;
  eventClick.current = onEventClick;

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
    candle.current = instance.addSeries(api.CandlestickSeries, {
      upColor: "#19a47b", downColor: "#e14f5b", borderVisible: false,
      wickUpColor: "#19a47b", wickDownColor: "#e14f5b",
    });
    volume.current = instance.addSeries(api.HistogramSeries, {
      priceFormat: {type: "volume"}, priceLineVisible: false,
    }, 1);
    interest.current = instance.addSeries(api.LineSeries, {
      color: "#805bd6", lineWidth: 2, priceLineVisible: false,
    }, 2);
    fillPlugin.current = api.createSeriesMarkers(candle.current, [], {autoScale: true});
    instance.subscribeClick(point => {
      const id = String(point?.hoveredInfo?.objectId ?? "");
      const items = markerItems.current.get(id);
      if (items) {
        setSelected({kind: "event", items});
        eventClick.current?.(items.map(item => item.raw));
      } else if (point?.time !== undefined) {
        const bar = barIndex.current.get(Number(point.time));
        if (bar) setSelected({kind: "market", bar});
      }
    });
    let timer: ReturnType<typeof setTimeout> | undefined;
    let skipInitialRange = true;
    const onRange = (range: Range | null) => {
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
            setData(result);
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
      instance.remove();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = chart.current;
    const api = library();
    if (!instance || !api || !candle.current || !volume.current || !interest.current) return;
    const rows = orderedBars(data.bars);
    const oldView = view.current;
    candle.current.setData(rows.map(bar => ({time: seconds(bar.timestamp),
      open: bar.open, high: bar.high, low: bar.low, close: bar.close})));
    volume.current.setData(rows.filter(bar => bar.volume !== null).map(bar => ({
      time: seconds(bar.timestamp), value: bar.volume,
      color: bar.close >= bar.open ? "#a9d8c9" : "#efb4b9",
    })));
    interest.current.setData(rows.filter(bar => bar.openInterest !== null).map(bar => ({
      time: seconds(bar.timestamp), value: bar.openInterest,
    })));
    barIndex.current = new Map(rows.map(bar => [seconds(bar.timestamp), bar]));
    for (const series of orderSeries.current) instance.removeSeries(series);
    orderSeries.current = [];
    const itemMap = new Map<string, Event[]>();
    const fills = fillMarkers(rows, data.events, frequencyMs);
    for (const [key, items] of fills.items) itemMap.set(key, items);
    fillPlugin.current?.setMarkers(fills.markers);
    const orders = orderRows(data.events, orderLimit);
    setOrderTotal(orders.total);
    if (orders.rows.length) {
      const pane = 3;
      for (const [index, [orderID, items]] of orders.rows.entries()) {
        const line = instance.addSeries(api.LineSeries, {color: "#8893a5",
          lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false}, pane);
        const byTime = new Map<number, Event[]>();
        for (const item of items) {
          const time = seconds(item.timestamp);
          if (!byTime.has(time)) byTime.set(time, []);
          byTime.get(time)!.push(item);
        }
        const times = [...byTime.keys()].sort((a, b) => a - b);
        line.setData(times.map(time => ({time, value: orders.rows.length - index})));
        const markers = times.map(time => {
          const group = byTime.get(time)!;
          const id = `order:${orderID}:${time}`;
          itemMap.set(id, group);
          const marker = group.length > 1
            ? {shape: "diamond", color: "#64748b"} : phase(group[0]);
          return {id, time, position: "inBar", ...marker, size: 1};
        });
        api.createSeriesMarkers(line, markers);
        orderSeries.current.push(line);
      }
    }
    instance.panes()[0]?.setStretchFactor(5.5);
    instance.panes()[1]?.setStretchFactor(1.3);
    instance.panes()[2]?.setStretchFactor(1.3);
    if (orders.rows.length) instance.panes()[3]?.setStretchFactor(
      Math.max(1.5, orders.rows.length * 0.25));
    markerItems.current = itemMap;
    if (oldView) instance.timeScale().setVisibleRange(oldView);
    else instance.timeScale().fitContent();
  }, [data, orderLimit, frequencyMs]);

  useEffect(() => {
    const series = candle.current;
    if (!series) return;
    for (const line of priceLines.current) series.removePriceLine(line);
    priceLines.current = selectedPrices.map(price => series.createPriceLine({price,
      color: "#2563eb", lineWidth: 1, lineStyle: 2, axisLabelVisible: true,
      title: `${translate("成交价")} ${price}`}));
  }, [selectedPrices, translate]);

  return <div className="ft-asset-chart-workbench">
    <div ref={node} className="ft-asset-chart-canvas"
      style={{height: Math.max(640, 450 + Math.min(orderLimit, orderTotal) * 26)}}
      aria-label={translate("行情、交易和订单历史图")} />
    <div className="ft-asset-chart-legend">{translate("订单历史")} · {Math.min(orderLimit, orderTotal)}/{orderTotal}
      {orderTotal > orderLimit && <button type="button" onClick={() => setOrderLimit(value => value + 10)}>
        {translate("加载更多订单")}</button>}
    </div>
    {selected?.kind === "market" && selected.bar && <div className="ft-asset-chart-market">
      <strong>{new Date(selected.bar.timestamp).toLocaleString()}</strong>
      <span>{translate("开 / 高 / 低 / 收")} {selected.bar.open} / {selected.bar.high} / {selected.bar.low} / {selected.bar.close}</span>
      <span>{translate("成交量")} {selected.bar.volume ?? "—"} · {translate("持仓量")} {selected.bar.openInterest ?? "—"}</span>
    </div>}
    {selected?.kind === "event" && <section className="ft-asset-chart-events">
      <header>{translate("交易事件")} · {selected.items?.length ?? 0}</header>
      {selected.items?.map((item, index) => <details key={`${item.id}:${index}`}
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
    </section>}
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
