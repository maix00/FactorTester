import React, { useEffect } from "react";
import { notification } from "antd";
import { bindNotificationSink } from "./core.ts";
import { useCompactLayout } from "../configuration/layout.ts";

export function DesktopNotificationHost(): React.ReactElement {
  const compact = useCompactLayout();
  // Wide dialogs close on the right; compact dialogs use a top-left back button.
  // Keep the notification stack away from both controls without moving content.
  const [api, holder] = notification.useNotification({ top: compact ? 76 : 8, placement: "topLeft" });
  useEffect(() => {
    bindNotificationSink((notice, done) => {
      api.open({
        key: notice.key,
        type: notice.type ?? "info",
        message: notice.message,
        description: notice.description,
        placement: "topLeft",
        duration: notice.duration ?? (notice.type === "error" ? 8 : 4),
        onClose: done,
      });
    });
    return () => bindNotificationSink(null);
  }, [api]);
  return <>{holder}</>;
}
