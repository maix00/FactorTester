export type TradingMode = "paper" | "live";
export function tradingSnapshot(value: Record<string, any> | null, mode: TradingMode): { installed: boolean; version: string; reported: boolean; available: boolean; reason: string } {
  const capability = value?.[mode === "live" ? "live" : "sandbox"];
  const reported = typeof capability?.available === "boolean";
  return { installed: value?.installed === true, version: String(value?.engine_version || ""), reported,
    available: value?.installed === true && reported && capability.available === true, reason: String(capability?.reason || "") };
}
