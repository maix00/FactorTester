export type NoticeType = "success" | "info" | "warning" | "error";

export type NoticeInput = {
  key?: string;
  code?: string;
  type?: NoticeType;
  message: string;
  description?: string;
  duration?: number;
};

export type ActiveNotice = NoticeInput & { key: string };
type Sink = (notice: ActiveNotice, done: () => void) => void;

const MAX_VISIBLE = 3;
const active = new Map<string, ActiveNotice>();
const pending: ActiveNotice[] = [];
const recent = new Map<string, number>();
let sink: Sink | null = null;

function keyFor(input: NoticeInput): string {
  return input.key || input.code || `${input.type ?? "info"}:${input.message}`;
}

function pump(): void {
  while (sink && active.size < MAX_VISIBLE && pending.length) {
    const notice = pending.shift();
    if (!notice || active.has(notice.key)) continue;
    active.set(notice.key, notice);
    sink(notice, () => {
      active.delete(notice.key);
      pump();
    });
  }
}

export function bindNotificationSink(next: Sink | null): void {
  sink = next;
  pump();
}

export function notify(input: NoticeInput): void {
  const key = keyFor(input);
  const now = Date.now();
  const last = recent.get(key) ?? 0;
  if (now - last < 3000 || active.has(key) || pending.some((item) => item.key === key)) return;
  recent.set(key, now);
  pending.push({ ...input, key });
  pump();
}

export function pendingNoticeCount(): number {
  return pending.length + active.size;
}

export function resetNotifications(): void {
  active.clear();
  pending.length = 0;
  recent.clear();
}
