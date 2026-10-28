import { parseDraft, readPath, writePath, type Draft, type JSONObject } from "./draft.ts";
export interface BundleScope {bundle_id:string;owner:string}
export interface ExecutionChoice extends JSONObject {mode:"auto"|"manual";manager_id:string;bundles:BundleScope[];target?:Record<string,any>;resolved?:Record<string,any>;resolved_ref?:string}
export function planFromConfiguration(configuration: JSONObject): JSONObject {
  return {plan_version:2,run_spec:{analyses:[Object.keys((configuration.analyses as JSONObject)||{})[0]||"backtest"],retention_mode:"full",configuration},execution:{mode:"auto",manager_id:"",bundles:[]}};
}
export function configurationDraft(plan: Draft|null): Draft|null {
  if (!plan) return null;
  return {...plan,text:JSON.stringify(readPath(parseDraft(plan.text).value,["run_spec","configuration"])||{},null,2),savedText:JSON.stringify(readPath(parseDraft(plan.savedText).value,["run_spec","configuration"])||{},null,2)};
}
export function replaceConfiguration(plan: Draft, value: Draft): Draft {
  const parsed=parseDraft(value.text);if(!parsed.value)throw new Error(parsed.error);
  let text=writePath(plan.text,["run_spec","configuration"],parsed.value);
  text=writePath(text,["execution","resolved"],undefined);text=writePath(text,["execution","resolved_ref"],undefined);
  return {...plan,text,source:value.source};
}
export function planSchema(configurationSchema:JSONObject):JSONObject {
  return {type:"object",required:["plan_version","run_spec","execution"],additionalProperties:false,properties:{
    plan_version:{const:2},run_spec:{type:"object",required:["configuration","analyses"],properties:{configuration:configurationSchema,analyses:{type:"array",minItems:1,maxItems:1,items:{type:"string"}},retention_mode:{enum:["summary","full"]}}},
    execution:{type:"object",required:["mode","manager_id","bundles"],properties:{mode:{enum:["auto","manual"]},manager_id:{type:"string"},bundles:{type:"array",items:{type:"object",required:["bundle_id","owner"],properties:{bundle_id:{type:"string"},owner:{type:"string"}}}},target:{type:"object"},resolved:{type:"object",readOnly:true},resolved_ref:{type:"string",readOnly:true}}}}};
}

/** A temporarily incomplete JSON edit must not crash the form projection. */
export function executionChoiceFromDocument(value: JSONObject | undefined): ExecutionChoice {
  const raw=value?.execution;
  const execution=raw && typeof raw==='object' && !Array.isArray(raw) ? raw as JSONObject : {};
  const bundles=Array.isArray(execution.bundles) ? execution.bundles.filter((item:any)=>
    item && typeof item.bundle_id==='string' && typeof item.owner==='string') as BundleScope[] : [];
  const resolved=execution.resolved as Record<string,any>|undefined;
  return {mode:execution.mode==='manual'?'manual':'auto', manager_id:typeof execution.manager_id==='string'?execution.manager_id:'', bundles,
    target:execution.target as Record<string,any>|undefined,
    resolved:resolved && Array.isArray(resolved.inputs) && resolved.target ? resolved:undefined,
    resolved_ref:typeof execution.resolved_ref==='string'?execution.resolved_ref:undefined};
}

export function resolutionInputKey(value: JSONObject | undefined): string {
  if(!value)return '';
  const clean=structuredClone(value);
  if(clean.execution && typeof clean.execution==='object' && !Array.isArray(clean.execution)){
    delete (clean.execution as JSONObject).resolved; delete (clean.execution as JSONObject).resolved_ref;
  }
  return JSON.stringify(clean);
}
export function applyResolution(draft: Draft|null, inputKey:string, result?:{binding:JSONObject;binding_ref:string}): Draft|null {
  if(!draft)return draft;
  const value=parseDraft(draft.text).value;
  if(!value || resolutionInputKey(value)!==inputKey || !value.execution || typeof value.execution!=='object' || Array.isArray(value.execution))return draft;
  const execution={...(value.execution as JSONObject)};
  if(!result && execution.resolved===undefined && execution.resolved_ref===undefined)return draft;
  delete execution.resolved;delete execution.resolved_ref;
  if(result){execution.resolved=result.binding;execution.resolved_ref=result.binding_ref;}
  const updated={...value,execution};
  const saved=parseDraft(draft.savedText).value;
  const text=result && saved && canonicalJSON(updated)===canonicalJSON(saved) ? draft.savedText : JSON.stringify(updated,null,2);
  return {...draft,text,source:'form'};
}

function canonicalJSON(value:unknown):string {
  if(Array.isArray(value))return '['+value.map(canonicalJSON).join(',')+']';
  if(value && typeof value==='object')return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonicalJSON((value as Record<string,unknown>)[key])).join(',')+'}';
  return JSON.stringify(value);
}
