import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "./notifications/core.ts";
import type { LocalResearchCapabilities, LocalResearchClient } from "./local-research-bridge.ts";

/** Synchronize only reports with an explicit publication receipt, in bounded pages. */
export function useLocalReportSync(client:LocalResearchClient|null,capabilities:LocalResearchCapabilities|null,active:boolean,onChanged:()=>void):()=>void {
  const {t}=useTranslation();
  const wake=useRef<(()=>void)|null>(null),noticed=useRef(new Map<string,string>()),callback=useRef(onChanged);
  callback.current=onChanged;
  useEffect(()=>{
    if(!active||!client||!capabilities?.actions.includes("sync_reports")||!capabilities.profiles.length)return;
    const snapshot=client.snapshot(),profiles=capabilities.profiles;
    let alive=true,running=false,requested=false,timer:number|undefined,profileIndex=0,cursor="";
    const schedule=(delay:number)=>{if(timer!==undefined)window.clearTimeout(timer);if(alive)timer=window.setTimeout(()=>void tick(),delay);};
    const tick=async()=>{
      if(!alive||running)return;
      running=true;
      try{
        const page=await client.syncReports(profiles[profileIndex].profile_id,cursor,4);
        if(!alive||!client.isCurrent(snapshot))return;
        noticed.current.delete("transport");
        let changed=false;
        for(const item of page.reports){
          if(item.status==="updated"||item.status==="published")changed=true;
          if(["conflict","denied","unavailable"].includes(item.status)){
            if(noticed.current.get(item.report_id)!==item.status){
              noticed.current.set(item.report_id,item.status);
              notify({code:`research.report.sync.${item.report_id}`,type:"warning",message:item.status==="conflict"?t("localResearch.syncConflict"):item.status==="denied"?t("localResearch.publicationDenied"):t("localResearch.syncUnavailable")});
            }
          } else noticed.current.delete(item.report_id);
        }
        if(changed){callback.current();notify({code:"research.report.sync.changed",type:"info",message:t("localResearch.syncUpdated")});}
        if(page.next_report_id)cursor=page.next_report_id;
        else {cursor="";profileIndex=(profileIndex+1)%profiles.length;}
        const more=!!page.next_report_id||profileIndex!==0;
        schedule(more?250:60000);
      }catch{
        if(alive&&client.isCurrent(snapshot)&&noticed.current.get("transport")!=="unavailable"){
          noticed.current.set("transport","unavailable");notify({code:"research.report.sync.unavailable",type:"warning",message:t("localResearch.syncUnavailable")});
        }
        cursor="";profileIndex=0;schedule(60000);
      }finally{
        running=false;
        if(alive&&requested){requested=false;cursor="";profileIndex=0;schedule(250);}
      }
    };
    wake.current=()=>{if(running)requested=true;else {cursor="";profileIndex=0;schedule(250);}};
    schedule(250);
    return()=>{alive=false;wake.current=null;if(timer!==undefined)window.clearTimeout(timer);};
  },[client,capabilities,active,t]);
  return useCallback(()=>wake.current?.(),[]);
}
