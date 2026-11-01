import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "./notifications/core.ts";
import { LocalResearchBridgeError, type LocalResearchCapabilities, type LocalResearchClient } from "./local-research-bridge.ts";

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
    const discoveryCursors=new Map<string,string>(),discoveryDone=new Set<string>();
    let transportWarning=false,remoteUpdated=false;
    const schedule=(delay:number)=>{if(timer!==undefined)window.clearTimeout(timer);if(alive)timer=window.setTimeout(()=>void tick(),delay);};
    const tick=async()=>{
      if(!alive||running)return;
      running=true;
      try{
        const profile=profiles[profileIndex].profile_id;
        if(capabilities.actions.includes("discover_researches")&&!discoveryDone.has(profile)){
          const discoveryCursor=discoveryCursors.get(profile)||"";
          try{
            const discovery=await client.discoverResearches(profile,discoveryCursor,16);
            if(!alive||!client.isCurrent(snapshot))return;
            if(discovery.next_cursor)discoveryCursors.set(profile,discovery.next_cursor);
            else {discoveryCursors.delete(profile);discoveryDone.add(profile);}
          }catch(reason){
            if(!alive||!client.isCurrent(snapshot))return;
            discoveryCursors.delete(profile);
            // A restarted Manager invalidates its opaque cursor; restart on
            // the next tick. Other failures wait for the normal retry cycle.
            if(!(reason instanceof LocalResearchBridgeError&&reason.code==="local_research_cursor_expired")){
              discoveryDone.add(profile);seen.add("discovery");
              if(!warned.has("discovery")){warned.add("discovery");notify({code:"research.discovery.unavailable",type:"warning",message:t("research.importPending")});}
            }
          }
        } else if(!capabilities.actions.includes("discover_researches")) {
          discoveryDone.add(profile);seen.add("discovery");
          if(!warned.has("discovery")){warned.add("discovery");notify({code:"research.discovery.unavailable",type:"warning",message:t("research.importPending")});}
        }
        const page=await client.syncReports(profile,cursor,4);
        if(!alive||!client.isCurrent(snapshot))return;
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
        for(const item of page.researches ?? []){
          if(item.status==="imported"||item.status==="updated")changed=true;
          if(["conflict","denied","unavailable"].includes(item.status)){
            const key=`research-${item.status}`;seen.add(key);
            if(!warned.has(key)){warned.add(key);notify({code:`research.sync.${item.status}`,type:"warning",message:t("research.importPending")});}
          }
        }
        for(const item of page.report_imports){
          if(item.status==="imported"||item.status==="attached")changed=true;
          if(["conflict","denied","unavailable"].includes(item.status)){
            const key=`report-import-${item.status}`;seen.add(key);
            if(!warned.has(key)){warned.add(key);notify({code:`research.report.import.${item.status}`,type:"warning",message:item.status==="conflict"?t("localResearch.syncConflict"):t("localResearch.importReportFailed")});}
          }
        }
        for(const item of page.report_scans){
          const key=`report-scan-${item.status}`;seen.add(key);
          if(!warned.has(key)){warned.add(key);notify({code:`research.report.scan.${item.status}`,type:"warning",message:item.status==="conflict"?t("localResearch.syncConflict"):t("localResearch.importReportFailed")});}
        }
        if(changed)callback.current();
        const discoveryMore=!discoveryDone.has(profile);
        if(page.next_report_id)cursor=page.next_report_id;
        else {cursor="";if(!discoveryMore&&!page.researches_pending_more&&!page.report_imports_pending_more)profileIndex=(profileIndex+1)%profiles.length;}
        const more=!!page.next_report_id||profileIndex!==0||page.researches_pending_more===true||page.report_imports_pending_more===true||discoveryMore;
        if(!more){
          // A successful first page does not mean the whole scan recovered.
          // Clear the warning only after every page and Profile has succeeded.
          transportWarning=false;
          if(remoteUpdated)notify({code:"research.report.sync.changed",type:"info",message:t("localResearch.syncUpdated")});
          remoteUpdated=false;
          discoveryDone.clear();discoveryCursors.clear();
          for(const status of warned)if(!seen.has(status))warned.delete(status);
          seen.clear();
        }
        schedule(more?250:60000);
      }catch{
        if(alive&&client.isCurrent(snapshot)&&!transportWarning){
          transportWarning=true;notify({code:"research.report.sync.unavailable",type:"warning",message:t("localResearch.syncUnavailable")});
        }
        cursor="";profileIndex=0;discoveryDone.clear();discoveryCursors.clear();seen.clear();remoteUpdated=false;schedule(60000);
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
