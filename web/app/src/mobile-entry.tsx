import React from "react";
import "./i18n.ts";
import { installGlobalErrorNotifications } from "./notifications/install.ts";
import { setupIonicReact } from "@ionic/react";
import { createRoot } from "react-dom/client";
import { MobileShell } from "./mobile-shell.tsx";
import { AuthGate } from "./auth.tsx";
import "@ionic/react/css/core.css";
import "@ionic/react/css/normalize.css";
import "@ionic/react/css/structure.css";
import "@ionic/react/css/typography.css";
import "./shell.css";

setupIonicReact({ mode: "md" });

const mount = document.querySelector<HTMLElement>("[data-tr-web-app]");
if (mount) createRoot(mount).render(<AuthGate><MobileShell /></AuthGate>);
