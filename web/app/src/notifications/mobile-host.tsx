import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  IonBadge, IonButton, IonButtons, IonContent, IonHeader, IonItem, IonLabel,
  IonList, IonModal, IonTitle, IonToast, IonToolbar,
} from "@ionic/react";
import { useTranslation } from "react-i18next";
import { bindNotificationSink, type ActiveNotice } from "./core.ts";

type Entry = ActiveNotice & { id: number; read: boolean; at: number };
type Queued = { notice: ActiveNotice; done: () => void; id: number };
type MobileNotificationCenter = { openCenter: () => void; unread: number };

const MobileNotificationContext = createContext<MobileNotificationCenter | null>(null);

export function useMobileNotificationCenter(): MobileNotificationCenter {
  const value = useContext(MobileNotificationContext);
  if (!value) throw new Error("useMobileNotificationCenter must be used within MobileNotificationHost");
  return value;
}

export function MobileNotificationHost({ children }: { children: React.ReactNode }): React.ReactElement {
  const { t } = useTranslation();
  const [items, setItems] = useState<Entry[]>(() => {
    try {
      const value = JSON.parse(localStorage.getItem("tr.notifications") ?? "[]");
      return Array.isArray(value) ? value.filter((item) => item && typeof item.message === "string").slice(0, 50) : [];
    } catch {
      return [];
    }
  });
  const [queue, setQueue] = useState<Queued[]>([]);
  const [open, setOpen] = useState(false);
  const unread = items.filter((item) => !item.read).length;
  useEffect(() => { localStorage.setItem("tr.notifications", JSON.stringify(items)); }, [items]);
  const current = queue[0];
  const openCenter = useCallback((): void => {
    setOpen(true);
    setItems((existing) => existing.map((item) => ({ ...item, read: true })));
  }, []);
  const contextValue = useMemo(() => ({ openCenter, unread }), [openCenter, unread]);

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
    <MobileNotificationContext.Provider value={contextValue}>
      {children}
      <IonToast
        key={current?.id ?? "none"}
        isOpen={Boolean(current)}
        message={current ? `${current.notice.message}${current.notice.description ? ` — ${current.notice.description}` : ""}` : ""}
        color={current?.notice.type === "error" ? "danger" : current?.notice.type === "success" ? "success" : "dark"}
        duration={current?.notice.duration ?? (current?.notice.type === "error" ? 7000 : 3500)}
        position="top"
        onDidDismiss={dismiss}
      />
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
    </MobileNotificationContext.Provider>
  );
}
