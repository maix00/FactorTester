export const REPORT_FONT_SIZES = [14,16,18,20,22,24] as const;
type FontStorage = Pick<Storage,"getItem" | "setItem">;

export function reportFontKey(username:string): string {
  return `tr.report.font:${encodeURIComponent(username || "anonymous")}`;
}

export function readReportFont(storage:FontStorage, username:string): number {
  try {
    const current = storage.getItem(reportFontKey(username));
    const raw = current ?? storage.getItem(`ft-report-font:${username || "anonymous"}`);
    const value = Number(raw);
    return REPORT_FONT_SIZES.some(size => size === value) ? value : 16;
  } catch { return 16; }
}

export function writeReportFont(storage:FontStorage, username:string, value:number): void {
  if (!REPORT_FONT_SIZES.some(size => size === value)) return;
  try {storage.setItem(reportFontKey(username),String(value));} catch { /* Storage may be unavailable. */ }
}
