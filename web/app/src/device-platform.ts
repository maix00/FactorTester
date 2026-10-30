export const DEVICE_PLATFORMS = ["all", "web", "mobile", "desktop", "cli", "other"] as const;
export type DevicePlatform = typeof DEVICE_PLATFORMS[number];

/** Map client metadata to stable user-facing device classes. */
export function devicePlatform(value: { client_type?: unknown; client_name?: unknown }): DevicePlatform {
  const type = String(value.client_type || "").trim().toLowerCase();
  const name = String(value.client_name || "").trim().toLowerCase();
  const source = `${type} ${name}`;
  if (/\b(cli|command[- ]line|terminal|python[- ]sdk)\b/.test(source) || type.startsWith("cli-")) return "cli";
  if (/\b(mobile|ios|android|iphone|ipad)\b/.test(source)) return "mobile";
  if (/\b(swift|desktop|macos|windows|linux|native)\b/.test(source)) return "desktop";
  if (/\b(browser|web|safari|chrome|firefox|edge)\b/.test(source)) return "web";
  return "other";
}

export function deviceUsernames(devices: ReadonlyArray<{ username?: unknown }>): string[] {
  return [...new Set(devices.map(device => String(device.username || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
}
