import React from "react";
import { DownOutlined } from "@ant-design/icons";
import { Button, Dropdown, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth.tsx";
import { PageIcon } from "../icon.tsx";

export function AccountActions(): React.ReactElement {
  const {t}=useTranslation(),{session,openAuth,logout}=useAuth();
  return <div className="tr-account-actions" aria-label={t("auth.account")}>
    <Button onClick={()=>openAuth("login")}>{t("auth.signIn")}</Button>
    <Button onClick={()=>openAuth("register")}>{t("auth.register")}</Button>
    {session?<Button onClick={()=>void logout()}>{t("auth.signOut")}</Button>:null}
  </div>;
}
export function AccountMenu({collapsed=false}:{collapsed?:boolean}):React.ReactElement {
  const {t}=useTranslation(),{session,openAuth,logout,registrationEnabled}=useAuth();
  const items=[{key:"login",label:t("auth.signIn")},
    {key:"register",label:registrationEnabled?t("auth.register"):t("auth.registrationClosed")},
    ...(session?[{key:"logout",label:t("auth.signOut")}]:[])];
  return <Dropdown trigger={["click"]} menu={{items,onClick:({key})=>key==="logout"?void logout():openAuth(key as "login"|"register")}}>
    <Tooltip title={collapsed?t("auth.account"):undefined} placement="right"><button type="button" className="tr-account-menu" aria-label={t("auth.account")}>
      <PageIcon name="account"/>{collapsed?null:<><span>{session?.alias||session?.username||t("auth.account")}</span><DownOutlined/></>}
    </button></Tooltip>
  </Dropdown>;
}
