import React, { useEffect, useState } from "react";
import { loadScript, loadStylesheet } from "../assets.ts";
type Renderer = { renderToString: (value: string, options: Record<string, unknown>) => string };
declare global { interface Window { katex?: Renderer } }
async function renderer(): Promise<Renderer> {
  loadStylesheet("/research-static/katex/katex.min.css");
  if (!window.katex) await loadScript("/research-static/katex/katex.min.js");
  if (!window.katex) throw new Error("Formula renderer unavailable");
  return window.katex;
}
export function Formula({ latex }: { latex: string }): React.ReactElement {
  const [html, setHTML] = useState("");
  useEffect(() => { let active = true; setHTML(""); void renderer().then((engine) => { const value = engine.renderToString(latex, { displayMode: true, throwOnError: false, trust: false, maxExpand: 1000 }); if (active) setHTML(value); }).catch(() => undefined); return () => { active = false; }; }, [latex]);
  return html ? <div className="tr-factor-formula" dangerouslySetInnerHTML={{ __html: html }} /> : <code className="tr-factor-formula">{latex}</code>;
}
