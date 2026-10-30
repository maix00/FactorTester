/**
 * The macOS desktop shell installs both handlers only for its own trusted
 * embedded pages. This is a presentation hint; Keycloak still authorizes
 * every package request. Window size and browser user-agent are not proof of
 * a desktop client.
 */
export function hasDesktopClientBridge(host: unknown): boolean {
  if (!host || typeof host !== "object") return false;
  const handlers = (host as { webkit?: { messageHandlers?: Record<string, unknown> } }).webkit?.messageHandlers;
  const available = (value: unknown): boolean => !!value && typeof value === "object" &&
    typeof (value as { postMessage?: unknown }).postMessage === "function";
  return !!handlers && available(handlers.factorTesterLocalRun) && available(handlers.factorTesterLocalCatalog);
}
