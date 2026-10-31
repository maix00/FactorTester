import React from "react";
import "./i18n.ts";
import { installGlobalErrorNotifications } from "./notifications/install.ts";
import { setupIonicReact } from "@ionic/react";
import { createRoot } from "react-dom/client";
import { MobileShell } from "./mobile-shell.tsx";
import { AuthGate } from "./auth.tsx";
import { captureResearchShare } from "./research-share-intent.ts";
import { ResearchShareRedeemer } from "./components/research-share-redeemer.tsx";
import "@ionic/react/css/core.css";
import "@ionic/react/css/normalize.css";
import "@ionic/react/css/structure.css";
import "@ionic/react/css/typography.css";
import "./shell.css";

setupIonicReact({ mode: "md" });

const mount = document.querySelector<HTMLElement>("[data-tr-web-app]");
if (mount) { captureResearchShare(); createRoot(mount).render(<AuthGate mobile><MobileShell /><ResearchShareRedeemer /></AuthGate>); }
