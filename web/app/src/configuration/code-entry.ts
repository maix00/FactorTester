/** Independent bundle: Monaco and workers never enter desktop/mobile startup. */
import * as monaco from "monaco-editor";
import type { CodeFactory } from "./code-loader.ts";

let modelSequence = 0;

(globalThis as typeof globalThis & { MonacoEnvironment: unknown }).MonacoEnvironment = {
  getWorkerUrl: (_module: string, label: string) => `/research-static/vendor/web-app/${label === "json" ? "configuration-json-worker" : "configuration-editor-worker"}.js`,
};

const mount: CodeFactory = (element, text, schema, onChange) => {
  const uri = monaco.Uri.parse(`inmemory://traderesearch/configuration-${Date.now()}-${++modelSequence}.json`);
  const model = monaco.editor.createModel(text, "json", uri);
  const schemaUri = String(schema.$id);
  const defaults = monaco.json.jsonDefaults;
  defaults.setDiagnosticsOptions({ validate: true, enableSchemaRequest: false,
    schemas: [...(defaults.diagnosticsOptions.schemas ?? []), { uri: schemaUri + uri.path, fileMatch: [uri.toString()], schema }] });
  const editor = monaco.editor.create(element, { model, automaticLayout: true, minimap: { enabled: false },
    fontSize: 14, tabSize: 2, scrollBeyondLastLine: false, wordWrap: "on", padding: { top: 16 }, editContext: false });
  let external = false;
  const listener = model.onDidChangeContent(() => { if (!external) onChange(model.getValue()); });
  return {
    setValue(value) {
      if (model.getValue() === value) return;
      external = true;
      editor.executeEdits("configuration-view", [{ range: model.getFullModelRange(), text: value }]);
      external = false;
    },
    dispose() {
      defaults.setDiagnosticsOptions({ ...defaults.diagnosticsOptions,
        schemas: (defaults.diagnosticsOptions.schemas ?? []).filter((item) => !item.fileMatch?.includes(uri.toString())) });
      listener.dispose(); editor.dispose(); model.dispose();
    },
  };
};
window.TRConfigurationCode = mount;
