import { notify } from "./core.ts";
import i18n from "../i18n.ts";

export function installGlobalErrorNotifications(): void {
  window.addEventListener("error", (event) => {
    if (!event.error) return;
    notify({
      code: "window.error",
      type: "error",
      message: i18n.t("unexpectedError"),
      description: String((event.error as Error).message || event.error),
    });
  });
  window.addEventListener("unhandledrejection", (event) => {
    notify({
      code: "window.unhandledrejection",
      type: "error",
      message: i18n.t("unhandledRejection"),
      description: String((event.reason as Error)?.message || event.reason),
    });
  });
}
