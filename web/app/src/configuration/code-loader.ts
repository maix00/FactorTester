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
  loading = new Promise<CodeFactory>((resolve, reject) => {
    if (!document.querySelector("link[data-tr-configuration-code]")) {
      const css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "/research-static/vendor/web-app/configuration-code.css";
      css.dataset.trConfigurationCode = "true"; document.head.append(css);
    }
    const script = document.createElement("script");
    script.src = "/research-static/vendor/web-app/configuration-code.js";
    script.onload = () => {
      if (window.TRConfigurationCode) resolve(window.TRConfigurationCode);
      else { script.remove(); loading = undefined; reject(new Error("Editor did not initialize")); }
    };
    script.onerror = () => { script.remove(); loading = undefined; reject(new Error("Editor could not load")); };
    document.head.append(script);
  });
  return loading;
}
