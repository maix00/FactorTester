import React from "react";
import { DownOutlined } from "@ant-design/icons";
import { Button, Dropdown, Tooltip, type MenuProps } from "antd";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth.tsx";
import { PageIcon } from "../icon.tsx";
import { objectReferenceLabel } from "../object-reference.ts";

export function AccountActions(): React.ReactElement {
  const {t}=useTranslation(),{session,openAuth,logout}=useAuth();
  return <div className="tr-account-actions" aria-label={t("auth.account")}>
    {session ? <Button onClick={()=>void logout()}>{t("auth.signOut")}</Button> : <>
      <Button onClick={()=>openAuth("login")}>{t("auth.signIn")}</Button>
    </>}
  </div>;
}
export function AccountMenu({collapsed=false,onOpenSettings}:{collapsed?:boolean;onOpenSettings?:()=>void}):React.ReactElement {
  const {t}=useTranslation(),{session,openAuth,logout}=useAuth();
  const accountLabel = session ? objectReferenceLabel({kind:"user",ref:session.username || "",label:session.alias},session) || t("auth.account") : t("auth.account");
  const items: MenuProps["items"] = session
    ? [{key:"settings",label:t("settings")},{type:"divider"},{key:"logout",label:t("auth.signOut"),danger:true}]
    : [{key:"login",label:t("auth.signIn")}];
  return <Dropdown trigger={["click"]} menu={{items,onClick:({key})=>{
    if(key==="logout")void logout();
    else if(key==="settings")onOpenSettings?.();
    else openAuth("login");
  }}}>
    <Tooltip title={collapsed?accountLabel:undefined} placement="right"><button type="button" className="tr-account-menu" aria-label={accountLabel}>
      <PageIcon name="account"/>{collapsed?null:<><span>{accountLabel}</span><DownOutlined/></>}
    </button></Tooltip>
  </Dropdown>;
}
