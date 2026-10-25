import React from "react";
import "./i18n.ts";
import { createRoot } from "react-dom/client";
import { DesktopShell } from "./desktop-shell.tsx";
import "./shell.css";
import "dockview-react/dist/styles/dockview.css";

const mount = document.querySelector<HTMLElement>("[data-tr-web-app]");
if (mount) createRoot(mount).render(<DesktopShell />);
