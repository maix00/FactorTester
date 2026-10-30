/** Independent bundle: Monaco and workers never enter desktop/mobile startup. */
import { assetURL } from "../assets.ts";
import * as monaco from "monaco-editor";
import { parseTree, findNodeAtLocation } from "jsonc-parser";
import type { CodeFactory } from "./code-loader.ts";

let modelSequence = 0;

(globalThis as typeof globalThis & { MonacoEnvironment: unknown }).MonacoEnvironment = {
  // Supplying the Worker directly bypasses Monaco's blob bootstrap under script-src self.
  getWorker: (_module: string, label: string) => new Worker(assetURL(`/research-static/vendor/web-app/${label === "json" ? "configuration-json-worker" : "configuration-editor-worker"}.js`), { name: label, type: "module" }),
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
    revealPath(path) {
      const root = parseTree(model.getValue());
      if (!root) return;
      let node = root;
      for (const part of path) {
        const next = findNodeAtLocation(node, [node.type === "array" ? Number(part) : part]);
        if (!next) return;
        node = next;
      }
      const start = model.getPositionAt(node.offset);
      const end = model.getPositionAt(node.offset + node.length);
      editor.setSelection(new monaco.Range(start.lineNumber, start.column, end.lineNumber, end.column));
      editor.revealLineInCenter(start.lineNumber); editor.focus();
    },
    dispose() {
      defaults.setDiagnosticsOptions({ ...defaults.diagnosticsOptions,
        schemas: (defaults.diagnosticsOptions.schemas ?? []).filter((item) => !item.fileMatch?.includes(uri.toString())) });
      listener.dispose(); editor.dispose(); model.dispose();
    },
  };
};
window.TRConfigurationCode = mount;
