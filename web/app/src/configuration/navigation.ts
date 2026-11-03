import {appEntrySearch} from "../app-route.ts";
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
export function useConfigurationNavigation(): { view: ConfigurationView; navigate: (view: ConfigurationView, replace?: boolean) => void; back: () => void } {
  const instance = usePageInstance();
  const [view, setView] = useState<ConfigurationView>(() => instance.mobile ? ((history.state?.trPage === instance.id ? history.state?.trConfigurationView : null) || readConfigurationView(appEntrySearch())) : { page: "overview" });
  useEffect(() => {
    const update = (event: PopStateEvent): void => { if (instance.mobile && event.state?.trPage === instance.id) setView(event.state?.trConfigurationView || {page:"overview"}); };
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, [instance.id, instance.mobile]);
  const navigate = useCallback((next: ConfigurationView, replace = false) => {
    if (instance.mobile && !replace) history.replaceState({...history.state, trPage: instance.id, trConfigurationView: view}, "", "/app");
    if (instance.mobile) history[replace ? "replaceState" : "pushState"]({ ...history.state, trPage: instance.id, trConfiguration: true, trConfigurationView: next }, "", "/app");
    setView(next);
  }, [instance.id, instance.mobile, view]);
  const back = useCallback(() => {
    if (instance.mobile && history.state?.trConfiguration && view.page !== "overview") history.back();
    else navigate({ page: "overview" }, true);
  }, [navigate, view.page, instance.mobile]);
  return { view, navigate, back };
}
