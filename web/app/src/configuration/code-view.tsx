import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { JSONObject } from "./draft.ts";
import { loadCodeEditor, type CodeEditor } from "./code-loader.ts";

export function CodeView({ text, schema, onChange, applyExternal = true }: {
  text: string; schema: JSONObject; onChange: (text: string) => void; applyExternal?: boolean;
}): React.ReactElement {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<CodeEditor | null>(null);
  const callback = useRef(onChange);
  const currentText = useRef(text);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const mobile = window.matchMedia("(max-width: 760px)").matches;
  callback.current = onChange;
  currentText.current = text;
  useEffect(() => {
    let active = true;
    setReady(false); setError("");
    if (mobile) return;
    loadCodeEditor().then((mount) => {
      if (!active || !host.current) return;
      instance.current = mount(host.current, currentText.current, schema, (value) => callback.current(value));
      setReady(true);
    }).catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; instance.current?.dispose(); instance.current = null; };
  }, [schema, mobile]);
  // Do not echo asynchronous React renders back over more recent Monaco input.
  useEffect(() => { if (applyExternal) instance.current?.setValue(text); }, [text, applyExternal]);
  return <div className="tr-config-code">
    {!ready && !mobile ? <p role="status">{error || t("configuration.loadingEditor")}</p> : null}
    {error || mobile ? <textarea aria-label={t("configuration.json")} value={text} onChange={(event) => onChange(event.target.value)} /> : null}
    <div ref={host} className="tr-config-monaco" hidden={mobile || !!error} />
  </div>;
}
