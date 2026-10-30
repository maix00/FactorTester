/** A server snapshot is replaced by its live inventory, never added to it. */
export type QuotaRecord = Record<string, any>;
export type QuotaServer = { id: string; data: QuotaRecord; snapshot: boolean; observedAt?: unknown; queueAllowed?: boolean };
export type QuotaCategory = { group: string; bytes: number; billedBytes: number; count: number; lastObserved: unknown[] };
export type CleanupTarget = { server: QuotaServer; preview: QuotaRecord };
export type CleanupPlan = { live: CleanupTarget[]; offline: QuotaServer[]; count: number; bytes: number };
export type QuotaServerSummary = {
  id: string;
  status: "current" | "last_observed" | "unavailable";
  bytes: number;
  count: number;
  observedAt?: unknown;
  pendingDeletions: number;
};

const amount = (value: unknown): number => typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
export function formatQuotaBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const power = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4);
  return `${(value / (1024 ** power)).toFixed(2)} ${["KiB", "MiB", "GiB", "TiB"][power - 1]}`;
}
const time = (value: unknown): number => typeof value === "number" ? value * 1000 : typeof value === "string" ? Date.parse(value) || 0 : 0;
function latestProfileInventories(profile: QuotaRecord | null): Map<string, QuotaRecord> {
  const inventories = new Map<string, QuotaRecord>();
  for (const row of [...(profile?.profile_snapshots || []), ...(profile?.cross_server?.servers || [])]) {
    const id = String(row.storage_server_id || "");
    if (!id || !row.inventory) continue;
    const previous = inventories.get(id);
    if (!previous || time(row.inventory.observed_at) >= time(previous.inventory.observed_at)) inventories.set(id, row);
  }
  return inventories;
}

/** One row per storage node; live job reads supersede snapshots for that node. */
export function summarizeQuotaServers(servers: QuotaServer[], profile: QuotaRecord | null, pending: QuotaRecord[]): QuotaServerSummary[] {
  const rows = new Map<string, QuotaServerSummary>();
  for (const server of servers) {
    const data = server.data;
    const outputBytes = amount(data.output_bytes ?? data.output_artifact_bytes);
    const inputBytes = amount(data.input_bytes ?? data.input_artifact_bytes);
    const outputCount = amount(data.output_count ?? data.output_artifact_count);
    const inputCount = amount(data.input_count ?? data.input_artifact_count);
    rows.set(server.id, {
      id: server.id,
      status: server.snapshot ? (server.queueAllowed === false ? "unavailable" : "last_observed") : "current",
      bytes: amount(data.artifact_bytes) || outputBytes + inputBytes,
      count: amount(data.artifact_count) || outputCount + inputCount,
      observedAt: server.observedAt ?? data.observed_at,
      pendingDeletions: 0,
    });
  }
  for (const [id, row] of latestProfileInventories(profile)) {
    const current = rows.get(id);
    const categories = Object.values(row.inventory.categories || {}) as QuotaRecord[];
    const profileBytes = categories.reduce((sum, item) => sum + amount(item.bytes), 0);
    const profileCount = categories.reduce((sum, item) => sum + amount(item.file_count), 0);
    if (current) {
      current.bytes += profileBytes;
      current.count += profileCount;
      if (!current.observedAt || time(row.inventory.observed_at) > time(current.observedAt)) current.observedAt = row.inventory.observed_at;
      if (current.status !== "current" && row.status === "current") current.status = "current";
    } else {
      rows.set(id, {
        id,
        status: row.status === "current" ? "current" : "last_observed",
        bytes: profileBytes,
        count: profileCount,
        observedAt: row.inventory.observed_at,
        pendingDeletions: 0,
      });
    }
  }
  for (const item of pending) {
    if (!["pending", "executing"].includes(String(item.status))) continue;
    const id = String(item.server_id || "");
    const row = rows.get(id);
    if (row) row.pendingDeletions += 1;
  }
  return [...rows.values()].sort((a, b) => b.bytes - a.bytes || a.id.localeCompare(b.id));
}

export function isOfflineFailure(reason: unknown): boolean {
  return reason instanceof TypeError || (typeof reason === "object" && reason !== null && [502, 503, 504].includes((reason as { status?: number }).status || 0));
}

/** Only use a complete server preview; the server verifies its token at execution. */
export function cleanupPlan(servers: QuotaServer[], pending: QuotaRecord[], group = ""): CleanupPlan {
  const live: CleanupTarget[] = [], offline: QuotaServer[] = [];
  for (const server of servers) {
    if (!server.snapshot && group !== "output:historical") {
      const preview = group ? (server.data.cleanup_business_groups || []).find((item: QuotaRecord) => item.group === group) : server.data.cleanup_preview;
      if (preview && amount(preview.artifact_count) && typeof preview.token === "string" && preview.token && typeof preview.bytes === "number" && Number.isFinite(preview.bytes) && preview.bytes >= 0) live.push({ server, preview });
    }
    if (server.snapshot && server.queueAllowed !== false && (!group || group === "output:historical") && amount(server.data.output_bytes) && amount(server.data.output_count) && server.observedAt && !pending.some(item => item.server_id === server.id && (item.status === "pending" || item.status === "executing"))) offline.push(server);
  }
  return { live, offline, count: live.reduce((sum, item) => sum + amount(item.preview.artifact_count), 0) + offline.reduce((sum, server) => sum + amount(server.data.output_count), 0), bytes: live.reduce((sum, item) => sum + amount(item.preview.bytes), 0) + offline.reduce((sum, server) => sum + amount(server.data.output_bytes), 0) };
}

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
  for (const row of latestProfileInventories(profile).values()) {
    for (const [key, value] of Object.entries(row.inventory.categories || {})) {
      const item = value as QuotaRecord;
      add(`profile:${key}`, item.bytes, item.file_count, row.status === "current" ? null : row.inventory.observed_at);
    }
  }
  return [...categories.values()].sort((a, b) => b.bytes - a.bytes);
}
