type WickBar = {time: number; open: number; high: number; low: number; close: number};
type Range = {from: number; to: number};
type Scale = {getVisibleRange: () => Range | null; timeToCoordinate: (time: number) => number | null};
type Series = {priceToCoordinate: (price: number) => number | null};
type CanvasTarget = {useMediaCoordinateSpace: (draw: (scope: {
  context: CanvasRenderingContext2D; mediaSize: {width: number; height: number};
}) => void) => void};

// The built-in candlestick style exposes wick colors, but not wick width.
// Draw only the exposed parts of each wick with the supported series primitive API.
export class WickPrimitive {
  private rows: WickBar[] = [];
  private scale: Scale | null = null;
  private series: Series | null = null;
  private requestUpdate: (() => void) | null = null;

  attached({chart, series, requestUpdate}: {
    chart: {timeScale: () => Scale}; series: Series; requestUpdate: () => void;
  }) {
    this.scale = chart.timeScale();
    this.series = series;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.scale = null;
    this.series = null;
    this.requestUpdate = null;
  }

  setRows(rows: WickBar[]) {
    this.rows = rows;
    this.requestUpdate?.();
  }

  paneViews() {
    return [{zOrder: () => "top", renderer: () => ({draw: (target: CanvasTarget) => {
      const scale = this.scale;
      const series = this.series;
      const range = scale?.getVisibleRange();
      if (!scale || !series || !range) return;
      target.useMediaCoordinateSpace(({context, mediaSize}) => {
        let start = 0;
        let end = this.rows.length;
        while (start < end) {
          const middle = (start + end) >>> 1;
          if (this.rows[middle].time < range.from) start = middle + 1;
          else end = middle;
        }
        const firstVisible = start;
        end = this.rows.length;
        while (start < end) {
          const middle = (start + end) >>> 1;
          if (this.rows[middle].time <= range.to) start = middle + 1;
          else end = middle;
        }
        // Dense views use the built-in renderer. Extra strokes would blend
        // adjacent candles together and slow down zooming.
        if (start - firstVisible > mediaSize.width / 3) return;
        context.lineWidth = 2;
        for (let index = firstVisible; index < start; index++) {
          const bar = this.rows[index];
          const x = scale.timeToCoordinate(bar.time);
          if (x === null || x < 0 || x > mediaSize.width) continue;
          const high = series.priceToCoordinate(bar.high);
          const bodyTop = series.priceToCoordinate(Math.max(bar.open, bar.close));
          const bodyBottom = series.priceToCoordinate(Math.min(bar.open, bar.close));
          const low = series.priceToCoordinate(bar.low);
          if ([high, bodyTop, bodyBottom, low].some(value => value === null)) continue;
          context.strokeStyle = bar.close >= bar.open ? "#19a47b" : "#e14f5b";
          context.beginPath();
          context.moveTo(x, high as number);
          context.lineTo(x, bodyTop as number);
          context.moveTo(x, bodyBottom as number);
          context.lineTo(x, low as number);
          context.stroke();
        }
      });
    }})}];
  }
}
