import type { JobReference } from "./job-model.ts";

type Row = Record<string, any>;
export type ReportNode = { component:Row; children:ReportNode[] };

export function validReportComponents(components:unknown): components is Row[] {
  if (!Array.isArray(components)) return false;
  const ids = new Set<string>();
  for (const component of components) {
    const id = component && typeof component === "object" ? String(component.component_id || "") : "";
    if (!id || ids.has(id)) return false;
    ids.add(id);
  }
  return true;
}

/** Preserve sibling order from the projection, even when it is breadth-first. */
export function reportTree(components:Row[]): ReportNode[] {
  const byID = new Map<string,Row>();
  const children = new Map<string,Row[]>();
  for (const component of components) {
    const id = String(component.component_id || "");
    if (id && !byID.has(id)) byID.set(id,component);
  }
  const roots:Row[] = [];
  for (const [id,component] of byID) {
    const parent = String(component.parent_id || "");
    if (!parent || parent === id || !byID.has(parent)) roots.push(component);
    else {const list = children.get(parent);if (list) list.push(component);else children.set(parent,[component]);}
  }
  const visited = new Set<string>();
  const result:ReportNode[] = [];
  const append = (root:Row): void => {
    const pending:{component:Row; parent:ReportNode | null}[] = [{component:root,parent:null}];
    while (pending.length) {
      const item = pending.pop()!, id = String(item.component.component_id || "");
      if (visited.has(id)) continue;
      visited.add(id);
      const node:ReportNode = {component:item.component,children:[]};
      if (item.parent) item.parent.children.push(node); else result.push(node);
      const entries = children.get(id) || [];
      for (let i = entries.length - 1; i >= 0; i--) pending.push({component:entries[i],parent:node});
    }
  };
  for (const component of roots) append(component);
  for (const component of byID.values()) if (!visited.has(String(component.component_id || ""))) append(component);
  return result;
}

/** Only the report's concrete Job identity and its recorded routing are used. */
export function reportJobReference(component:Row, bindings:Row[]): JobReference | null {
  if (component.kind !== "special" || component.display_kind !== "test_result") return null;
  const match = /^job-([a-f0-9]{32}|[a-f0-9]{64})-result$/i.exec(String(component.component_id || ""));
  if (!match) return null;
  const jobID = match[1].toLowerCase();
  const direct = bindings.filter(item => item.kind === "job" && item.target_ref === `job:${jobID}`);
  const candidates = direct.length ? direct : bindings.filter(item => item.kind === "evidence" && item.data && (item.data.server_id || item.data.execution_server_id));
  let result:JobReference | null = null;
  for (const binding of candidates) {
    const data = binding.data || {}, serverID = String(data.server_id || data.execution_server_id || "").trim();
    const declaredPort = data.port || data.execution_port || data.service_port, port = Number(declaredPort);
    // Without exact, consistent routing even a locally readable report can point to another Manager.
    if (!serverID || !declaredPort || !Number.isInteger(port) || port <= 0 || port > 65535) return null;
    const next:JobReference = {job_id:jobID,server_id:serverID,service_port:port,...(data.execution_node_id ? {execution_node_id:String(data.execution_node_id)} : {})};
    if (result && (result.server_id !== next.server_id || result.service_port !== next.service_port || result.execution_node_id !== next.execution_node_id)) return null;
    result = next;
  }
  return result;
}
