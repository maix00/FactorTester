import React, { useEffect, useState } from "react";
type Renderer = { renderToString: (value: string, options: Record<string, unknown>) => string };
declare global { interface Window { katex?: Renderer } }
let ready: Promise<Renderer> | undefined;
function renderer(): Promise<Renderer> {
  if (window.katex) return Promise.resolve(window.katex);
  if (!ready) ready = new Promise<Renderer>((resolve, reject) => {
    if (!document.querySelector('[data-tr-katex]')) { const style = document.createElement("link"); style.rel = "stylesheet"; style.href = "/research-static/katex/katex.min.css"; style.dataset.trKatex = "1"; document.head.append(style); }
    const script = document.createElement("script"); script.src = "/research-static/katex/katex.min.js";
    script.onload = () => window.katex ? resolve(window.katex) : reject(new Error("Formula renderer unavailable")); script.onerror = () => reject(new Error("Formula renderer unavailable")); document.head.append(script);
  }).catch((error) => { ready = undefined; throw error; });
  return ready;
}
export function Formula({ latex }: { latex: string }): React.ReactElement {
  const [html, setHTML] = useState("");
  useEffect(() => { let active = true; setHTML(""); void renderer().then((engine) => { const value = engine.renderToString(latex, { displayMode: true, throwOnError: false, trust: false, maxExpand: 1000 }); if (active) setHTML(value); }).catch(() => undefined); return () => { active = false; }; }, [latex]);
  return html ? <div className="tr-factor-formula" dangerouslySetInnerHTML={{ __html: html }} /> : <code className="tr-factor-formula">{latex}</code>;
}
