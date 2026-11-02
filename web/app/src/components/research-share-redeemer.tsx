import React, { useRef, useState } from "react";
import { Alert, Button, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth.tsx";
import { request } from "../configuration/api.ts";
import { notify } from "../notifications/core.ts";
import { clearResearchShare, pendingResearchShare } from "../research-share-intent.ts";
import { objectReferenceLabel } from "../object-reference.ts";

/** Explicit confirmation ensures an invitation is not consumed by the wrong account. */
export function ResearchShareRedeemer(): React.ReactElement | null {
  const {t}=useTranslation(), {session,openAuth}=useAuth();
  const [token,setToken]=useState(pendingResearchShare), [busy,setBusy]=useState(false);
  const mutation=useRef(false);
  if(!token || !session)return null;
  const account = objectReferenceLabel({kind:"user",ref:session.username || "",label:session.alias},session);
  const dismiss=():void=>{if(!mutation.current){clearResearchShare();setToken("");}};
  const redeem=async():Promise<void>=>{
    if(mutation.current)return;mutation.current=true;setBusy(true);
    try {
      const result=await request("/api/research/keycloak-share-links/redeem",{method:"POST",body:JSON.stringify({token})});
      if(!result.grant?.research_id || !["research","report"].includes(result.grant?.target_kind))throw new Error(t("researchDetail.invalidResponse"));
      clearResearchShare();setToken("");
      notify({code:"research.sharing.redeemed",type:"success",message:t("researchSharing.claimed"),description:t("researchSharing.claimedHint")});
    } catch(reason) {
      const issue=reason as Error & {status?:number;code?:string};
      notify({code:"research.sharing.redeem.failed",type:"error",message:t("researchSharing.claimFailed"),description:issue.status===404?t("researchSharing.invalidOrUnsupported"):issue.code==="keycloak_sharing_unavailable"?t("researchSharing.unavailable"):issue.message});
    } finally {mutation.current=false;setBusy(false);}
  };
  return <Modal open title={t("researchSharing.claimTitle")} onCancel={dismiss} closable={!busy} maskClosable={!busy} footer={
    <><Button disabled={busy} onClick={dismiss}>{t("configuration.cancel")}</Button>{session.visitor_login
      ? <Button type="primary" onClick={()=>openAuth("login")}>{t("researchSharing.signInToClaim")}</Button>
      : <Button type="primary" loading={busy} onClick={()=>void redeem()}>{t("researchSharing.claim")}</Button>}</>
  }><p>{t("researchSharing.claimAs",{name:account})}</p><Alert type="info" showIcon message={t("researchSharing.claimHint")} /></Modal>;
}
