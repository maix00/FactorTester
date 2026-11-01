import React, {useEffect,useRef,useState} from "react";
import {Alert,Button,Form,Input,Spin} from "antd";
import {useTranslation} from "react-i18next";
import {useAuth} from "../auth.tsx";
import {ManagerBridgeError,managerBridge,managerURL,sameManagerURL,type ManagerClient,type ManagerConnection} from "../manager-bridge.ts";

type Phase="checking"|"browser"|"unsupported"|"ready"|"switching"|"handoff"|"uncertain";
export function nativeManagerSettingsAvailable(host:unknown):boolean {
  const handlers=(host as {webkit?:{messageHandlers?:Record<string,unknown>}} | null)?.webkit?.messageHandlers;
  return [handlers?.factorTesterAuthentication,handlers?.tradeResearchAuthentication,handlers?.tradeResearchManager]
    .some(value=>!!value && typeof (value as {postMessage?:unknown}).postMessage==="function");
}

/** The native client performs the switch and navigation; React never changes sessions itself. */
export function ManagerConnectionSettings():React.ReactElement {
  const {t}=useTranslation(),{session}=useAuth();
  const identity=session as (typeof session & {keycloak_issuer?:string;tr_identity_id?:string;keycloak_subject?:string});
  const identityKey=JSON.stringify([identity?.username,identity?.keycloak_issuer,identity?.tr_identity_id,identity?.keycloak_subject,identity?.visitor_login]);
  const [phase,setPhase]=useState<Phase>("checking"),[connection,setConnection]=useState<ManagerConnection|null>(null),[message,setMessage]=useState("");
  const [confirmedKey,setConfirmedKey]=useState("");
  const [revision,setRevision]=useState(0),[form]=Form.useForm<{url:string}>();
  const targetURL=Form.useWatch("url",form);
  const bridge=useRef<ManagerClient|null>(null),generation=useRef(0);
  const currentIdentity=useRef(identityKey);currentIdentity.current=identityKey;
  useEffect(()=>{
    const active=++generation.current;setConnection(null);setConfirmedKey("");setMessage("");
    const client=managerBridge(window);
    if(!client){setPhase(nativeManagerSettingsAvailable(window)?"unsupported":"browser");return;}
    bridge.current=client;setPhase("checking");
    const timer=window.setTimeout(()=>{if(generation.current!==active)return;client.close();bridge.current=null;setPhase("unsupported");},12000);
    void client.capabilities().then(()=>client.current()).then(value=>{
      if(generation.current!==active || currentIdentity.current!==identityKey)return;
      setConnection(value);setConfirmedKey(identityKey);form.setFieldsValue({url:value.url});setPhase("ready");
    }).catch(()=>{if(generation.current===active && currentIdentity.current===identityKey){client.close();bridge.current=null;setPhase("unsupported");}}).finally(()=>window.clearTimeout(timer));
    return()=>{generation.current++;window.clearTimeout(timer);client.close();if(bridge.current===client)bridge.current=null;};
  },[identityKey,revision,form]);
  const switchManager=async({url}: {url:string}):Promise<void>=>{
    const client=bridge.current;if(!client || phase!=="ready" || confirmedKey!==identityKey)return;
    if(connection?.auth_state==="authorized" && sameManagerURL(url,connection.url))return;
    const active=++generation.current;
    setPhase("switching");setConnection(null);setMessage("");
    const timer=window.setTimeout(()=>{
      if(generation.current!==active || currentIdentity.current!==identityKey)return;
      client.close();bridge.current=null;setMessage(t("managerConnection.uncertain"));setPhase("uncertain");
    },20000);
    try{
      const result=await client.switchTo(url);
      if(generation.current!==active || currentIdentity.current!==identityKey)return;
      client.close();bridge.current=null;setMessage(t(`managerConnection.handoff.${result.auth_state}`));setPhase("handoff");
    }catch(reason){
      if(generation.current!==active || currentIdentity.current!==identityKey)return;
      client.close();bridge.current=null;
      const code=reason instanceof ManagerBridgeError?reason.code:"manager_bridge_failed";
      setMessage(t(`managerConnection.errors.${code}`,{defaultValue:t("managerConnection.uncertain")}));setPhase("uncertain");
    }finally{window.clearTimeout(timer);}
  };
  const visiblePhase=["ready","switching","handoff","uncertain"].includes(phase) && confirmedKey!==identityKey ? "checking" : phase;
  return <section aria-label={t("managerConnection.title")}>
    <h3>{t("managerConnection.title")}</h3>
    {visiblePhase==="checking"?<Spin tip={t("loading")} />:null}
    {visiblePhase==="browser"?<p>{t("managerConnection.browserHint")}</p>:null}
    {visiblePhase==="unsupported"?<Alert type="info" showIcon message={t("managerConnection.unsupported")} action={<Button onClick={()=>setRevision(value=>value+1)}>{t("retry")}</Button>} />:null}
    {visiblePhase==="ready"&&connection?<>
      <p>{t("managerConnection.current")}: <strong>{connection.url}</strong></p>
      {connection.auth_state!=="authorized"?<Alert type="warning" showIcon message={t(`managerConnection.currentState.${connection.auth_state}`)}/>:null}
      <Form form={form} layout="vertical" onFinish={switchManager}>
        <Form.Item name="url" label={t("managerConnection.address")} rules={[{required:true,message:t("managerConnection.required")},{validator:async(_,value)=>{try{managerURL(value);}catch{return Promise.reject(new Error(t("managerConnection.invalid")));}}}]}>
          <Input type="url" autoComplete="url" aria-label={t("managerConnection.address")} />
        </Form.Item>
        <Button type="primary" htmlType="submit" disabled={connection.auth_state==="authorized" && sameManagerURL(targetURL,connection.url)}>{t("managerConnection.switch")}</Button>
      </Form>
    </>:null}
    {visiblePhase==="switching"?<Spin tip={t("managerConnection.switching")} />:null}
    {visiblePhase==="handoff"||visiblePhase==="uncertain"?<Alert type={visiblePhase==="uncertain"?"warning":"info"} showIcon message={message} action={visiblePhase==="uncertain"?<Button onClick={()=>setRevision(value=>value+1)}>{t("retry")}</Button>:undefined}/>:null}
  </section>;
}
