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
