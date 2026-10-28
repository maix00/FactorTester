import React, { useEffect } from "react";
import { notification } from "antd";
import { bindNotificationSink } from "./core.ts";

export function DesktopNotificationHost(): React.ReactElement {
  const [api, holder] = notification.useNotification({ top: 112 });
  useEffect(() => {
    bindNotificationSink((notice, done) => {
      api.open({
        key: notice.key,
        type: notice.type ?? "info",
        message: notice.message,
        description: notice.description,
        placement: "topRight",
        duration: notice.duration ?? (notice.type === "error" ? 8 : 4),
        onClose: done,
      });
    });
    return () => bindNotificationSink(null);
  }, [api]);
  return <>{holder}</>;
}
