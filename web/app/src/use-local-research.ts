import { useCallback, useEffect, useState } from "react";
import { hasDesktopClientBridge } from "./desktop-client.ts";
import { LocalResearchBridgeError, localResearchBridge, type LocalResearchCapabilities, type LocalResearchClient } from "./local-research-bridge.ts";

type SessionProjection = { username?:string; keycloak_issuer?:string; tr_identity_id?:string; keycloak_subject?:string; visitor_login?:boolean } | null;
type NativeState = {
  key:string;
  phase:"unsupported"|"missing"|"checking"|"unavailable"|"ready";
  code:string;
  client:LocalResearchClient|null;
  capabilities:LocalResearchCapabilities|null;
};

/** Native binding, not the presence of a WebKit object, decides capability. */
export function useLocalResearch(session:SessionProjection,mobile:boolean):NativeState & {retry:()=>void} {
  // New clients can expose this independently of the legacy catalog/run bridges.
  const desktop = !mobile && typeof window!=="undefined" && (hasDesktopClientBridge(window) || localResearchBridge(window)!==null);
  const key=JSON.stringify([desktop,session?.username||"",session?.keycloak_issuer||"",session?.tr_identity_id||"",session?.keycloak_subject||"",!!session?.visitor_login]);
  const [state,setState]=useState<NativeState>({key:"",phase:"unsupported",code:"",client:null,capabilities:null});
  const [revision,setRevision]=useState(0);
  const retry=useCallback(()=>setRevision(value=>value+1),[]);
  useEffect(()=>{
    let active=true, timedOut=false;
    if(!desktop){setState({key,phase:"unsupported",code:"",client:null,capabilities:null});return;}
    const client=localResearchBridge(window);
    if(!client){setState({key,phase:"missing",code:"",client:null,capabilities:null});return;}
    if(!session?.username || !session.keycloak_issuer || !session.tr_identity_id || session.visitor_login){
      client.close();setState({key,phase:"unavailable",code:"local_research_session_unverified",client:null,capabilities:null});return;
    }
    setState({key,phase:"checking",code:"",client:null,capabilities:null});
    const timeout=window.setTimeout(()=>{
      if(!active)return;timedOut=true;client.close();
      setState({key,phase:"unavailable",code:"local_research_timeout",client:null,capabilities:null});
    },12000);
    void client.capabilities({issuer:session.keycloak_issuer,identity_id:session.tr_identity_id}).then(capabilities=>{
      if(!active||timedOut)return;
      if(!capabilities.actions.includes("list") || capabilities.profiles.length===0){
        client.close();setState({key,phase:"unavailable",code:"local_research_capability_unavailable",client:null,capabilities:null});return;
      }
      setState({key,phase:"ready",code:"",client,capabilities});
    }).catch(reason=>{
      if(!active||timedOut)return;
      client.close();setState({key,phase:"unavailable",code:reason instanceof LocalResearchBridgeError ? reason.code : "local_research_bridge_failed",client:null,capabilities:null});
    }).finally(()=>window.clearTimeout(timeout));
    return()=>{active=false;window.clearTimeout(timeout);client.close();};
  },[key,revision]);
  if(state.key!==key)return {key,phase:desktop ? "checking" : "unsupported",code:"",client:null,capabilities:null,retry};
  return {...state,retry};
}
