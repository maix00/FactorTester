import React, { useEffect, useState } from "react";
import { Alert, Button, Collapse, Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { runSpecURL } from "../job-model.ts";
import { ResultView } from "./result-view.tsx";
export function FrozenRunSpec({hash,serverID}:{hash?:string;serverID?:string}):React.ReactElement {
 const {t}=useTranslation();const [value,setValue]=useState<Record<string,any>|null>(null),[error,setError]=useState(""),[retry,setRetry]=useState(0);
 useEffect(() => {setValue(null);setError("");if(!hash)return;const abort=new AbortController();
  void (async () => {const data=await request(runSpecURL(hash,serverID),{signal:abort.signal});if(!abort.signal.aborted)setValue(data.run_spec);})().catch(reason => {if(!abort.signal.aborted)setError(reason.message);});return () => abort.abort();
 },[hash,serverID,retry]);
 if(!hash)return <Empty description={t("empty")} />;
 if(error)return <Alert type="error" message={error} action={<Button onClick={() => setRetry(value => value+1)}>{t("retry")}</Button>} />;
 if(!value)return <Spin />;
 const execution=value.configuration?.payload?.analyses?.backtest?.execution;
 // A backtest displays only its effective Nautilus contract, never editor aliases.
 if(execution){
  if(execution.backend!=="nautilus_trader" || !execution.nautilus_contract)return <Alert type="warning" message={t("jobs.noNautilusContract")} />;
  const contract=execution.nautilus_contract, {venues,...settings}=contract.settings || {};
  return <div className="tr-frozen-spec"><ResultView value={{...contract,settings}} />{Array.isArray(venues) && venues.length ? <Collapse ghost defaultActiveKey={["0"]} items={venues.map((venue:Record<string,any>,index:number) => ({key:String(index),label:venue.name,children:<ResultView value={venue} />}))} /> : null}</div>;
 }
 return <ResultView value={value} />;
}
