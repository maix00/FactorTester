import React, { useEffect, useState } from "react";
import { Alert, Button, Collapse, Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { runSpecURL } from "../job-model.ts";
import { frozenRunSpecSections } from "../frozen-run-spec-model.ts";
import { ResultView } from "./result-view.tsx";
export function FrozenRunSpec({hash,serverID}:{hash?:string;serverID?:string}):React.ReactElement {
 const {t}=useTranslation();const [value,setValue]=useState<Record<string,any>|null>(null),[error,setError]=useState(""),[retry,setRetry]=useState(0);
 useEffect(() => {setValue(null);setError("");if(!hash)return;const abort=new AbortController();
  void (async () => {const data=await request(runSpecURL(hash,serverID),{signal:abort.signal});if(!abort.signal.aborted)setValue(data.run_spec);})().catch(reason => {if(!abort.signal.aborted)setError(reason.message);});return () => abort.abort();
 },[hash,serverID,retry]);
 if(!hash)return <Empty description={t("empty")} />;
 if(error)return <Alert type="error" message={error} action={<Button onClick={() => setRetry(value => value+1)}>{t("retry")}</Button>} />;
 if(!value)return <Spin />;
 const sections=frozenRunSpecSections(value,hash);
 const items=[
  {key:"identity",label:t("jobs.specIdentity"),children:<ResultView value={sections.identity} />},
  ...(sections.hasConfiguration ? [{key:"configuration",label:t("jobs.specContent"),children:<ResultView value={sections.configuration} />}] : []),
  {key:"options",label:t("jobs.specOptions"),children:<ResultView value={sections.options} />},
 ];
 return <div className="tr-frozen-spec"><Collapse ghost defaultActiveKey={items.map(item => item.key)} items={items} /></div>;
}
