import type { Draft } from "./draft.ts";
import { parseDraft, readPath } from "./draft.ts";
import { TEMPLATE_PATH, LIBRARY_PATH } from "./strategies.ts";

export function runRequest(workspace: string, draft: Draft, analysis = "backtest"): Record<string, unknown> {
  if (!workspace || draft.text !== draft.savedText) throw new Error("Save configuration first");
  const value = parseDraft(draft.text).value;
  const bindings = [TEMPLATE_PATH, LIBRARY_PATH].flatMap((path) => {
    const items = readPath(value, path); return Array.isArray(items) ? items : [];
  });
  if (analysis === "backtest" && !bindings.length) throw new Error("Select a strategy first");
  return { workspace_id: workspace, configuration_revision: draft.revision, analyses: [analysis] };
}
