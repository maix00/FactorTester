import React, { useEffect, useRef, useState } from "react";
import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import { loadChartRuntime, type MarketBar, type PriceHandle, type RangeBand } from "../charts/runtime.ts";
const labels: Record<string, string> = { "开盘价": "open", "最高价": "high", "最低价": "low", "收盘价": "close", "成交量": "volume", "持仓量": "openInterest", "时间": "time", "关闭": "closePanel", "蜡烛详情": "candle", "行情 K 线、成交量和持仓量": "chart", "换主力": "roll", "主力切换至": "rollTo", "正在细化当前时间范围…": "loading" };
export function MarketChart({ bars, hasOI, zone, bands, selectedBand, onUnavailable }: { bars: MarketBar[]; hasOI: boolean; zone: string; bands: RangeBand[]; selectedBand: string; onUnavailable: () => void }): React.ReactElement {
  const { t } = useTranslation(); const host = useRef<HTMLDivElement>(null), handle = useRef<PriceHandle | null>(null);
  const latest = useRef({ zone, bands, selectedBand, onUnavailable }); latest.current = { zone, bands, selectedBand, onUnavailable };
  const [error, setError] = useState("");
  useEffect(() => { let cancelled = false; setError("");
    void loadChartRuntime().then(() => {
      if (cancelled || !host.current) return;
      const current = latest.current;
      const mounted = window.FTChartWorkbench!.mountPriceChart(host.current, { bars, hasOpenInterest: hasOI, timeZone: current.zone, translate: (value) => labels[value] ? t(`market.${labels[value]}`) : value });
      handle.current = mounted; mounted.setRangeBands(current.bands);
      if (current.selectedBand && !mounted.selectRangeBand(current.selectedBand)) current.onUnavailable();
    }).catch((reason) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; const mounted = handle.current; handle.current = null; if (mounted) queueMicrotask(() => mounted()); };
  }, [bars, hasOI, t]);
  useEffect(() => { handle.current?.setTimeZone(zone); }, [zone]);
  useEffect(() => { handle.current?.setRangeBands(bands); }, [bands]);
  useEffect(() => { if (selectedBand && handle.current && !handle.current.selectRangeBand(selectedBand)) latest.current.onUnavailable(); }, [selectedBand]);
  return <div className="tr-chart-host">{error ? <Alert type="error" message={error} /> : null}<div ref={host} /></div>;
}
