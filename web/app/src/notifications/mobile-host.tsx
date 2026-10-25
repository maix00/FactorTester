import React, { useEffect, useState } from "react";
import { bindNotificationSink, type ActiveNotice } from "./core.ts";

type Item = ActiveNotice & { id: number };

export function MobileNotificationHost(): React.ReactElement {
  const [items, setItems] = useState<Item[]>([]);
  useEffect(() => {
    let nextId = 1;
    bindNotificationSink((notice, done) => {
      const item = { ...notice, id: nextId++ };
      setItems((current) => [item, ...current].slice(0, 3));
      window.setTimeout(() => {
        setItems((current) => current.filter((value) => value.id !== item.id));
        done();
      }, notice.duration ?? (notice.type === "error" ? 7000 : 3500));
    });
    return () => bindNotificationSink(null);
  }, []);
  return (
    <div className="tr-mobile-notifications" role="status" aria-live="polite">
      {items.map((item) => (
        <div key={item.id} className={`tr-mobile-notice is-${item.type ?? "info"}`}>
          <strong>{item.message}</strong>
          {item.description ? <span>{item.description}</span> : null}
        </div>
      ))}
    </div>
  );
}
