// A range response may contain only part of the currently drawn series. Keep
// earlier bars when the user zooms back out, while letting newer source data
// replace bars at the same timestamp.
export function mergeBars<T extends {timestamp: number}>(current: T[], incoming: T[]): T[] {
  const byTime = new Map<number, T>();
  for (const bar of [...current, ...incoming]) {
    if (Number.isFinite(bar.timestamp)) byTime.set(Math.floor(bar.timestamp / 1000), bar);
  }
  return [...byTime].sort(([left], [right]) => left - right).map(([, bar]) => bar);
}
