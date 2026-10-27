export type JobScope = "server" | "cross-server" | "mine" | "subordinates";
export interface JobPage { jobs?: Record<string, any>[]; items?: Record<string, any>[]; total?: number; page?: number; has_more?: boolean; next_cursor?: string; users?: { username: string }[]; requires_login?: boolean; selection_required?: boolean }
type Reader = (url: string, options: { signal: AbortSignal }) => Promise<JobPage>;
/** Cursor-only navigation state: no second retained copy of result rows. */
export class JobFeed {
  private cursors = new Map<number, string>([[1, ""]]);
  async read(reader: Reader, options: { scope: JobScope; page: number; size: number; username?: string; signal: AbortSignal }): Promise<JobPage> {
    const { scope, size, signal, username } = options;
    const target = Math.max(1, Math.min(1000, options.page));
    const query = (page: number, cursor?: string): string => {
      const params = new URLSearchParams({ scope, page: String(page), limit: String(size) });
      if (cursor) params.set("cursor", cursor);
      if (scope === "subordinates" && username) params.set("username", username);
      return `/api/jobs?${params}`;
    };
    if (scope !== "server") return reader(query(target), { signal });
    let start = target;
    while (!this.cursors.has(start) && start > 1) start -= 1;
    for (let page = start; page <= target; page += 1) {
      signal.throwIfAborted();
      const value = await reader(query(page, this.cursors.get(page)), { signal });
      signal.throwIfAborted();
      if (value.next_cursor) this.cursors.set(page + 1, value.next_cursor);
      if (page === target || !value.has_more || !value.next_cursor) return { ...value, page };
    }
    throw new Error("Unreachable cursor state");
  }
}
