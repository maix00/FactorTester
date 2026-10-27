import React, { useEffect, useRef } from "react";
import { Button, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { useCompactLayout } from "../configuration/layout.ts";
export function DetailsPanel({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }): React.ReactElement {
  const mobile = useCompactLayout(), { t } = useTranslation();
  const id = useRef(crypto.randomUUID()), close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    if (!mobile) return;
    history.pushState({ ...history.state, trDetail: id.current }, "", location.href);
    const pop = (): void => { if (history.state?.trDetail !== id.current) close.current(); };
    window.addEventListener("popstate", pop); return () => window.removeEventListener("popstate", pop);
  }, [mobile]);
  const dismiss = (): void => { if (mobile && history.state?.trDetail === id.current) history.back(); else onClose(); };
  if (mobile) return <section className="tr-mobile-detail-page"><header><Button type="text" onClick={dismiss}>‹ {t("back")}</Button><h2>{title}</h2></header><div>{children}</div></section>;
  return <Modal open title={title} footer={null} width={960} onCancel={dismiss} styles={{ body: { maxHeight: "75vh", overflow: "auto" } }}>{children}</Modal>;
}
