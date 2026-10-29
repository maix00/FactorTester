/** A server snapshot is replaced by its live inventory, never added to it. */
export type QuotaRecord = Record<string, any>;
export type QuotaServer = { id: string; data: QuotaRecord; snapshot: boolean; observedAt?: unknown };
export type QuotaCategory = { group: string; bytes: number; billedBytes: number; count: number; lastObserved: unknown[] };

const amount = (value: unknown): number => typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
const time = (value: unknown): number => typeof value === "number" ? value * 1000 : typeof value === "string" ? Date.parse(value) || 0 : 0;

export function aggregateQuota(servers: QuotaServer[], profile: QuotaRecord | null, pending: QuotaRecord[]): QuotaCategory[] {
  const categories = new Map<string, QuotaCategory>();
  const add = (group: string, raw: unknown, count: unknown, observed: unknown = null, credit = 0): void => {
    const bytes = amount(raw), n = amount(count);
    if (!bytes && !n) return;
    const row = categories.get(group) || { group, bytes: 0, billedBytes: 0, count: 0, lastObserved: [] };
    row.bytes += bytes;
    row.billedBytes += Math.max(0, bytes - credit);
    row.count += n;
    if (observed) row.lastObserved.push(observed);
    categories.set(group, row);
  };
  for (const server of servers) {
    let credit = pending.filter(item => item.server_id === server.id && (item.status === "pending" || item.status === "executing")).reduce((sum, item) => sum + amount(item.credit_bytes), 0);
    if (server.snapshot) {
      const output = amount(server.data.output_bytes), deducted = Math.min(output, credit);
      add("output:historical", output, server.data.output_count, server.observedAt, deducted);
      add("input:other", server.data.input_bytes, server.data.input_count, server.observedAt);
      continue;
    }
    let coveredOutput = 0, coveredInput = 0;
    for (const item of server.data.business_groups || []) {
      const group = String(item.quota_group || "");
      if (!group) continue;
      const deducted = group.startsWith("output:") ? Math.min(credit, amount(item.bytes)) : 0;
      add(group, item.bytes, item.job_count, null, deducted);
      if (group.startsWith("output:")) coveredOutput += amount(item.bytes);
      if (group.startsWith("input:")) coveredInput += amount(item.bytes);
      credit -= deducted;
    }
    const remainingOutput = Math.max(0, amount(server.data.output_artifact_bytes) - coveredOutput);
    const remainingInput = Math.max(0, amount(server.data.input_artifact_bytes) - coveredInput);
    add("output:historical", remainingOutput, 0, null, Math.min(credit, remainingOutput));
    add("input:other", remainingInput, 0);
  }
  for (const [key, group] of [["factors", "input:factor"], ["product_groups", "input:product"], ["strategies", "input:strategy"], ["other", "protected:other"]]) {
    const row = profile?.protected_metadata?.[key];
    if (row) add(group, row.bytes, row.item_count);
  }
  const inventories = new Map<string, QuotaRecord>();
  for (const row of [...(profile?.profile_snapshots || []), ...(profile?.cross_server?.servers || [])]) {
    const id = String(row.storage_server_id || "");
    if (!id || !row.inventory) continue;
    const previous = inventories.get(id);
    if (!previous || time(row.inventory.observed_at) >= time(previous.inventory.observed_at)) inventories.set(id, row);
  }
  for (const row of inventories.values()) {
    for (const [key, value] of Object.entries(row.inventory.categories || {})) {
      const item = value as QuotaRecord;
      add(`profile:${key}`, item.bytes, item.file_count, row.status === "current" ? null : row.inventory.observed_at);
    }
  }
  return [...categories.values()].sort((a, b) => b.bytes - a.bytes);
}
