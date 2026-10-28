export interface ExecutionDeployment { manager_id: string; node_id: string; service_id: string; deployment_ref: string; test_types: string[] }
export interface BarInput { product_ref: string; bar_spec: string; price_basis: string; time_semantics: string; fields: string[]; start_ns: number; end_ns: number }
export interface BarOffer extends Omit<BarInput, "start_ns" | "end_ns"> { source_ref: string; available: boolean; coverage_start_ns: number | null; coverage_end_ns: number | null; installation: { bundle_id: string; bundle_version: string; node_id: string } }
export interface ExecutionTarget { route_id: string; service_port: number; online: boolean; target: ExecutionDeployment; offers: BarOffer[] }
export interface ExecutionSelection { data_requirements: BarInput[]; execution_selection: { target: ExecutionDeployment; sources: Record<string,string>; expected_installations: Record<string,BarOffer["installation"]> } | {mode:"auto";manager_id:string} }

export function executionRequest(target: ExecutionTarget, offers: BarOffer[], start: string, end: string, type: string): ExecutionSelection {
  const from = Date.parse(start.endsWith("Z") ? start : start + "Z"), to = Date.parse(end.endsWith("Z") ? end : end + "Z");
  if (!target.online || !target.target.test_types.includes(type)) throw new Error("executionTopology.unavailable");
  if (!Number.isFinite(from) || !Number.isFinite(to) || from >= to || !offers.length) throw new Error("executionTopology.chooseInputs");
  if (new Set(offers.map(x => x.product_ref)).size !== offers.length) throw new Error("executionTopology.duplicateProduct");
  const sources: Record<string,string> = {};
  const expected_installations: Record<string,BarOffer["installation"]> = {};
  const requirements = offers.map(offer => {
    if (!offer.available || offer.installation.node_id !== target.target.node_id || !target.offers.some(x => x.source_ref === offer.source_ref && x.product_ref === offer.product_ref && x.bar_spec === offer.bar_spec)) throw new Error("executionTopology.unavailable");
    if ((offer.coverage_start_ns !== null && from * 1e6 < offer.coverage_start_ns) || (offer.coverage_end_ns !== null && to * 1e6 > offer.coverage_end_ns)) throw new Error("executionTopology.unavailable");
    sources[offer.product_ref] = offer.source_ref;
    expected_installations[offer.source_ref] = offer.installation;
    return { product_ref: offer.product_ref, bar_spec: offer.bar_spec, price_basis: offer.price_basis, time_semantics: offer.time_semantics, fields: offer.fields, start_ns: from * 1e6, end_ns: to * 1e6 };
  });
  return { data_requirements: requirements, execution_selection: { target: target.target, sources, expected_installations } };
}

export function automaticExecutionRequest(offers: BarOffer[], start: string, end: string, type: string, managerID: string, configured: BarInput[] = []): ExecutionSelection {
  if (!managerID || !type) throw new Error("executionTopology.unavailable");
  const from = Date.parse(start.endsWith("Z") ? start : start + "Z"), to = Date.parse(end.endsWith("Z") ? end : end + "Z");
  const requirements = configured.length ? configured : offers.map(offer => ({ product_ref:offer.product_ref, bar_spec:offer.bar_spec,
    price_basis:offer.price_basis,time_semantics:offer.time_semantics,fields:offer.fields,start_ns:from*1e6,end_ns:to*1e6 }));
  if (!requirements.length || new Set(requirements.map(row => row.product_ref)).size !== requirements.length || requirements.some(row => !Number.isFinite(row.start_ns) || !Number.isFinite(row.end_ns) || row.start_ns >= row.end_ns)) throw new Error("executionTopology.chooseInputs");
  return {data_requirements:requirements,execution_selection:{mode:"auto",manager_id:managerID}};
}

export function selectionManager(selection: ExecutionSelection): string {
  return "target" in selection.execution_selection ? selection.execution_selection.target.manager_id : selection.execution_selection.manager_id;
}
