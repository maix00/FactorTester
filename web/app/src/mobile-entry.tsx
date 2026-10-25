import React from "react";
import { createRoot } from "react-dom/client";
import { MobileShell } from "./mobile-shell.tsx";
import "./shell.css";

const mount = document.querySelector<HTMLElement>("[data-tr-web-app]");
if (mount) createRoot(mount).render(<MobileShell />);
