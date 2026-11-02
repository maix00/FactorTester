import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { Button, ConfigProvider, Modal } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useCompactLayout } from "../configuration/layout.ts";
const DismissContext = createContext<(() => void) | null>(null);
/** Reuse the panel's history-aware close action for a form inside that panel. */
export function DetailsCancelButton({ onCancel, closePanel, disabled }: { onCancel: () => void; closePanel: boolean; disabled?: boolean }): React.ReactElement {
  const dismiss = useContext(DismissContext), { t } = useTranslation();
  return <Button disabled={disabled} onClick={closePanel && dismiss ? dismiss : onCancel}>{t("configuration.cancel")}</Button>;
}
export function DetailsPanel({ title, onClose, children, width = 960, forceFullscreen = false, landscape = false }: { title: string; onClose: () => void; children: React.ReactNode; width?: number; forceFullscreen?: boolean; landscape?: boolean }): React.ReactElement {
  const compact = useCompactLayout(), mobile = compact || forceFullscreen, { t } = useTranslation();
  const [portrait, setPortrait] = useState(() => window.matchMedia("(orientation: portrait)").matches);
  useEffect(() => {
    const query = window.matchMedia("(orientation: portrait)");
    const update = (): void => setPortrait(query.matches);
    query.addEventListener("change", update); return () => query.removeEventListener("change", update);
  }, []);
  const rotated = mobile && landscape && portrait;
  const id = useRef(crypto.randomUUID()), close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    if (!mobile) return;
    history.pushState({ ...history.state, trDetail: id.current }, "", location.href);
    const pop = (): void => { if (history.state?.trDetail !== id.current) close.current(); };
    window.addEventListener("popstate", pop); return () => window.removeEventListener("popstate", pop);
  }, [mobile]);
  const dismiss = (): void => { if (mobile && history.state?.trDetail === id.current) history.back(); else onClose(); };
  // Both layouts use the same Modal focus boundary and accessible dialog semantics.
  return <Modal open wrapClassName={rotated ? "tr-landscape-table-modal" : undefined} title={mobile ? <div style={{display:"flex",alignItems:"center",gap:12}}>
    <Button type="text" icon={<ArrowLeftOutlined />} onClick={dismiss} aria-label={t("back")}>{t("back")}</Button>
    <span style={{fontSize:18,minWidth:0,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{title}</span>
  </div> : title} footer={null} width={rotated ? "100dvh" : mobile ? "100%" : width} closable={!mobile} onCancel={dismiss} maskClosable={!mobile}
    style={rotated ? {position:"fixed",top:0,left:"100vw",width:"100dvh",maxWidth:"100dvh",margin:0,paddingBottom:0,transform:"rotate(90deg)",transformOrigin:"top left"} : mobile ? {top:0,maxWidth:"100vw",margin:0,paddingBottom:0} : undefined}
    styles={mobile ? {
      wrapper:{overflow:"hidden"},content:{height:rotated?"100vw":"100dvh",borderRadius:0,padding:0,display:"flex",flexDirection:"column"},
      header:{padding:"16px 20px",margin:0,borderBottom:"1px solid var(--line)",flexShrink:0},
      body:{padding:20,overflow:"auto",minHeight:0,flex:1},
    } : {body:{maxHeight:"75vh",overflow:"auto"}}}><DismissContext.Provider value={dismiss}>{rotated ? <ConfigProvider getPopupContainer={(trigger) => trigger?.closest<HTMLElement>(".ant-modal-content") || document.body}>{children}</ConfigProvider> : children}</DismissContext.Provider></Modal>;
}
