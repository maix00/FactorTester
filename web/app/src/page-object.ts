import type {PageArguments} from "./page-instance.ts";
/** One detail view per Research/Profile/report; mutable titles are not identity. */
export function pageObjectKey(pageId:string,args:PageArguments={}):string|undefined {
  if(!["research-detail","research-report"].includes(pageId)||!args.researchId)return undefined;
  return JSON.stringify([pageId,args.researchId,args.reportId||"",args.localResearch===true,
    args.localResearch ? args.profileId||"self" : ""]);
}
export function pageObjectTitle(pageId:string,args:PageArguments={}):string|undefined {
  if(["research-detail","research-report"].includes(pageId))return args.reportTitle||args.researchTitle;
  if(pageId==="product-detail")return args.productTitle;
  return undefined;
}
