import type {ReactNode} from "react";

export type ChartSelection = {x: number; y: number};

export function ChartPopover({anchor, title, onClose, children}: {
  anchor: ChartSelection; title: string; onClose: () => void; children: ReactNode;
}) {
  return <section className="ft-chart-popover" role="dialog" aria-label={title}
    style={{left: `clamp(8px, ${anchor.x + 14}px, calc(100% - 368px))`,
      top: `clamp(8px, ${anchor.y + 14}px, calc(100% - 180px))`}}
    onWheel={event => event.stopPropagation()}>
    <header><strong>{title}</strong><button type="button" onClick={onClose}
      aria-label="关闭">×</button></header>
    {children}
  </section>;
}
