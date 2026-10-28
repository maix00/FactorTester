import { useCallback, useEffect, useState } from "react";
import { usePageInstance } from "../page-instance.ts";
import type { Path } from "./draft.ts";

export type ConfigurationView = { page: "overview" | "strategies" | "catalog" | "settings" | "json" | "preview"; id?: string; path?: Path }
  | { page: "strategy" | "field"; id?: string; path?: Path };
const pages = new Set(["overview", "strategies", "catalog", "settings", "json", "preview", "strategy", "field"]);
export function readConfigurationView(search: string): ConfigurationView {
  const params = new URLSearchParams(search);
  const page = params.get("tr_config") || "overview";
  if (!pages.has(page)) return { page: "overview" };
  let path: Path | undefined;
  try { const value = JSON.parse(params.get("tr_path") || "null"); if (Array.isArray(value) && value.every((item) => typeof item === "string")) path = value; } catch { /* ignore invalid deep link */ }
  return { page: page as ConfigurationView["page"], id: params.get("tr_item") || undefined, path };
}
export function configurationURL(href: string, view: ConfigurationView): string {
  const url = new URL(href);
  for (const key of ["tr_config", "tr_item", "tr_path"]) url.searchParams.delete(key);
  if (view.page !== "overview") url.searchParams.set("tr_config", view.page);
  if (view.id) url.searchParams.set("tr_item", view.id);
  if (view.path) url.searchParams.set("tr_path", JSON.stringify(view.path));
  return url.href;
}
export function useConfigurationNavigation(): { view: ConfigurationView; navigate: (view: ConfigurationView, replace?: boolean) => void; back: () => void } {
  const instance = usePageInstance();
  const [view, setView] = useState<ConfigurationView>(() => instance.mobile ? readConfigurationView(location.search) : { page: "overview" });
  useEffect(() => {
    const update = (event: PopStateEvent): void => { if (instance.mobile && event.state?.trPage === instance.id) setView(readConfigurationView(location.search)); };
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, [instance.id, instance.mobile]);
  const navigate = useCallback((next: ConfigurationView, replace = false) => {
    if (instance.mobile) history[replace ? "replaceState" : "pushState"]({ ...history.state, trPage: instance.id, trConfiguration: true }, "", configurationURL(location.href, next));
    setView(next);
  }, [instance.id, instance.mobile]);
  const back = useCallback(() => {
    if (instance.mobile && history.state?.trConfiguration && view.page !== "overview") history.back();
    else navigate({ page: "overview" }, true);
  }, [navigate, view.page, instance.mobile]);
  return { view, navigate, back };
}
