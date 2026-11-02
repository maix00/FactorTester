import type {PageArguments} from "./page-instance.ts";
const catalogPages=new Set(["products","factors","strategies"]);
/** A URL selects a registered view; it never grants object access. */
export function appCatalogLink(search:string):{pageId:string;args:PageArguments}|null {
 const params=new URLSearchParams(search),pageId=params.get("page")||"";
 if(!catalogPages.has(pageId))return null;
 return {pageId,args:{...(params.get("section")?{section:params.get("section")!}:{}),
  ...(params.get("object_ref")?{catalogRef:params.get("object_ref")!}:{}),
  ...(params.get("owner_username")?{catalogOwner:params.get("owner_username")!}:{}),
  ...(["create","edit"].includes(params.get("mode")||"")?{catalogMode:params.get("mode") as "create"|"edit"}:{})}};
}
