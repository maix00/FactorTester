import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "./notifications/core.ts";
import type { LocalResearchCapabilities, LocalResearchClient } from "./local-research-bridge.ts";

/** Synchronize only reports with an explicit publication receipt, in bounded pages. */
export function useLocalReportSync(client:LocalResearchClient|null,capabilities:LocalResearchCapabilities|null,active:boolean,onChanged:()=>void):()=>void {
  const {t}=useTranslation();
  const wake=useRef<(()=>void)|null>(null),callback=useRef(onChanged);
  callback.current=onChanged;
  useEffect(()=>{
    if(!active||!client||!capabilities?.actions.includes("sync_reports")||!capabilities.profiles.length)return;
    const snapshot=client.snapshot(),profiles=capabilities.profiles;
    let alive=true,running=false,requested=false,timer:number|undefined,profileIndex=0,cursor="";
    const warned=new Set<string>(),seen=new Set<string>();
    let transportWarning=false,remoteUpdated=false;
    const schedule=(delay:number)=>{if(timer!==undefined)window.clearTimeout(timer);if(alive)timer=window.setTimeout(()=>void tick(),delay);};
    const tick=async()=>{
      if(!alive||running)return;
      running=true;
      try{
        const page=await client.syncReports(profiles[profileIndex].profile_id,cursor,4);
        if(!alive||!client.isCurrent(snapshot))return;
        transportWarning=false;
        let changed=false;
        for(const item of page.reports){
          if(item.status==="updated"||item.status==="published")changed=true;
          if(item.status==="updated")remoteUpdated=true;
          if(["conflict","denied","unavailable"].includes(item.status)){
            seen.add(item.status);
            if(!warned.has(item.status)){
              warned.add(item.status);
              notify({code:`research.report.sync.${item.status}`,type:"warning",message:item.status==="conflict"?t("localResearch.syncConflict"):item.status==="denied"?t("localResearch.publicationDenied"):t("localResearch.syncUnavailable")});
            }
          }
        }
        if(changed)callback.current();
        if(page.next_report_id)cursor=page.next_report_id;
        else {cursor="";profileIndex=(profileIndex+1)%profiles.length;}
        const more=!!page.next_report_id||profileIndex!==0;
        if(!more){
          if(remoteUpdated)notify({code:"research.report.sync.changed",type:"info",message:t("localResearch.syncUpdated")});
          remoteUpdated=false;
          for(const status of warned)if(!seen.has(status))warned.delete(status);
          seen.clear();
        }
        schedule(more?250:60000);
      }catch{
        if(alive&&client.isCurrent(snapshot)&&!transportWarning){
          transportWarning=true;notify({code:"research.report.sync.unavailable",type:"warning",message:t("localResearch.syncUnavailable")});
        }
        cursor="";profileIndex=0;seen.clear();remoteUpdated=false;schedule(60000);
      }finally{
        running=false;
        if(alive&&requested){requested=false;cursor="";profileIndex=0;schedule(250);}
      }
    };
    wake.current=()=>{if(running)requested=true;else {cursor="";profileIndex=0;schedule(250);}};
    const resume=()=>{if(document.visibilityState==="visible" && navigator.onLine)wake.current?.();};
    window.addEventListener("online",resume);
    document.addEventListener("visibilitychange",resume);
    schedule(250);
    return()=>{alive=false;wake.current=null;window.removeEventListener("online",resume);document.removeEventListener("visibilitychange",resume);if(timer!==undefined)window.clearTimeout(timer);};
  },[client,capabilities,active,t]);
  return useCallback(()=>wake.current?.(),[]);
}
