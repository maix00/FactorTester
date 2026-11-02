import React from "react";
import "./i18n.ts";
import { installGlobalErrorNotifications } from "./notifications/install.ts";
import { createRoot } from "react-dom/client";
import { DesktopShell } from "./desktop-shell.tsx";
import { AuthGate } from "./auth.tsx";
import { captureResearchShare } from "./research-share-intent.ts";
import { ResearchShareRedeemer } from "./components/research-share-redeemer.tsx";
import "./shell.css";
import "dockview-react/dist/styles/dockview.css";

const mount = document.querySelector<HTMLElement>("[data-tr-web-app]");
if (mount) { captureResearchShare(); createRoot(mount).render(<AuthGate><DesktopShell /><ResearchShareRedeemer /></AuthGate>); }
