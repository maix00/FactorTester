import React, { useEffect, useState } from "react";
import {
  IonBadge, IonButton, IonButtons, IonContent, IonHeader, IonItem, IonLabel,
  IonList, IonModal, IonTitle, IonToast, IonToolbar,
} from "@ionic/react";
import { useTranslation } from "react-i18next";
import { bindNotificationSink, type ActiveNotice } from "./core.ts";

type Entry = ActiveNotice & { id: number; read: boolean; at: number };
type Queued = { notice: ActiveNotice; done: () => void; id: number };

export function MobileNotificationHost(): React.ReactElement {
  const { t } = useTranslation();
  const [items, setItems] = useState<Entry[]>([]);
  const [queue, setQueue] = useState<Queued[]>([]);
  const [open, setOpen] = useState(false);
  const unread = items.filter((item) => !item.read).length;
  const current = queue[0];

  useEffect(() => {
    let nextId = 1;
    bindNotificationSink((notice, done) => {
      const id = nextId++;
      setItems((existing) => [
        { ...notice, id, read: false, at: Date.now() },
        ...existing,
      ].slice(0, 50));
      setQueue((existing) => [...existing, { notice, done, id }]);
    });
    return () => bindNotificationSink(null);
  }, []);

  const dismiss = (): void => {
    setQueue((existing) => {
      const [first, ...rest] = existing;
      first?.done();
      return rest;
    });
  };

  return (
    <>
      <IonToast
        key={current?.id ?? "none"}
        isOpen={Boolean(current)}
        message={current ? `${current.notice.message}${current.notice.description ? ` — ${current.notice.description}` : ""}` : ""}
        color={current?.notice.type === "error" ? "danger" : current?.notice.type === "success" ? "success" : "dark"}
        duration={current?.notice.duration ?? (current?.notice.type === "error" ? 7000 : 3500)}
        position="top"
        onDidDismiss={dismiss}
      />
      {!open ? (
        <button type="button" className="tr-mobile-bell" aria-label={t("notifications.bell")} onClick={() => { setOpen(true); setItems((existing) => existing.map((item) => ({ ...item, read: true }))); }}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></svg>
          {unread > 0 ? <IonBadge color="danger">{unread > 99 ? "99+" : unread}</IonBadge> : null}
        </button>
      ) : null}
      <IonModal isOpen={open} onDidDismiss={() => setOpen(false)}>
        <IonHeader>
          <IonToolbar>
            <IonTitle>{t("notifications.title")}</IonTitle>
            <IonButtons slot="end"><IonButton onClick={() => setOpen(false)}>{t("notifications.close")}</IonButton></IonButtons>
          </IonToolbar>
        </IonHeader>
        <IonContent>
          <IonList>
            {items.length === 0 ? (
              <IonItem lines="none"><IonLabel>{t("notifications.empty")}</IonLabel></IonItem>
            ) : items.map((item) => (
              <IonItem key={item.id} lines="full">
                <IonLabel>
                  <h3>{item.message}</h3>
                  {item.description ? <p>{item.description}</p> : null}
                  <small>{new Date(item.at).toLocaleTimeString()}</small>
                </IonLabel>
                {!item.read ? <IonBadge color="primary">{t("notifications.new")}</IonBadge> : null}
              </IonItem>
            ))}
          </IonList>
        </IonContent>
      </IonModal>
    </>
  );
}
