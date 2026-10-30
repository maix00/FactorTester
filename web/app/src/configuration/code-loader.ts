import { loadScript, loadStylesheet } from "../assets.ts";
import type { JSONObject } from "./draft.ts";

export interface CodeEditor {
  setValue(text: string): void;
  revealPath(path: string[]): void;
  dispose(): void;
}
export type CodeFactory = (element: HTMLElement, text: string, schema: JSONObject,
                           onChange: (text: string) => void) => CodeEditor;
declare global { interface Window { TRConfigurationCode?: CodeFactory } }

let loading: Promise<CodeFactory> | undefined;
export function loadCodeEditor(): Promise<CodeFactory> {
  if (window.TRConfigurationCode) return Promise.resolve(window.TRConfigurationCode);
  if (loading) return loading;
  loadStylesheet("/research-static/vendor/web-app/configuration-code.css");
  loading = loadScript("/research-static/vendor/web-app/configuration-code.js").then(() => {
    if (!window.TRConfigurationCode) throw new Error("Editor did not initialize");
    return window.TRConfigurationCode;
  }).catch(reason => { loading=undefined; throw reason; });
  return loading;
}
