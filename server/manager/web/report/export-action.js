(() => {
  const FORMATS = [
    ["md", "导出 Markdown"],
    ["pdf", "导出 PDF"],
  ];

  function serverRef(target) {
    const explicit = String(target?.server_ref || "").trim();
    if (explicit) return explicit;
    const parts = [
      target?.profile_ref || target?.profile_id || "",
      target?.work_package_id || "",
      target?.branch_id || "",
    ].map(value => String(value || "").trim());
    return parts.every(Boolean) ? parts.join(":") : "";
  }

  function targetOwner(target) {
    return String(target?.owner_ref || target?.target_ref || "").trim();
  }

  function exportURL(target, format) {
    const ref = serverRef(target);
    if (!ref) return "";
    const owner = targetOwner(target);
    return `/api/server-research/${encodeURIComponent(ref)}`
      + `/export?format=${encodeURIComponent(format)}`
      + (owner ? `&target_ref=${encodeURIComponent(owner)}` : "");
  }

  function safeName(title) {
    const value = String(title || "").replace(/[/\\:]/g, "-").trim();
    return value || "report";
  }

  async function run(context, target, format) {
    // Embedded in the Swift client: the native export owns the authoritative
    // tree and the PDF renderer, so hand the request over.  For a report the
    // client cannot export locally the native handler falls back to the
    // server export below.
    const bridge = window.webkit?.messageHandlers?.researchReportExport;
    if (bridge && typeof bridge.postMessage === "function") {
      bridge.postMessage({
        publication_id: String(target?.publication_id || ""),
        server_ref: serverRef(target),
        target_ref: targetOwner(target),
        format: String(format || "md"),
        title: String(target?.title || ""),
      });
      return;
    }
    const url = exportURL(target, format);
    if (!url) {
      context.showNotice?.(context.t("该报告不在此服务器，无法导出"), true);
      return;
    }
    try {
      const response = await fetch(url, {credentials: "same-origin"});
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || context.t("导出失败"));
      }
      const objectURL = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = objectURL;
      anchor.download = `${safeName(target?.title)}.${format}`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
    } catch (error) {
      context.showNotice?.(error.message || String(error), true);
    }
  }

  // A download icon that reveals the .md / .pdf choices.
  function menu(context, target) {
    const root = document.createElement("span");
    root.className = "report-export-menu";
    const trigger = window.FTUI.iconButton(
      context, "square.and.arrow.up", context.t("导出报告"), () => toggle(),
    );
    trigger.classList.add("report-export-trigger");
    trigger.setAttribute("aria-haspopup", "menu");
    const list = document.createElement("span");
    list.className = "report-export-choices";
    list.setAttribute("role", "menu");
    list.hidden = true;
    FORMATS.forEach(([format, label]) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "report-export-choice";
      item.setAttribute("role", "menuitem");
      item.textContent = context.t(label);
      item.addEventListener("click", event => {
        event?.stopPropagation?.();
        close();
        void run(context, target, format);
      });
      list.append(item);
    });
    const close = () => {
      list.hidden = true;
      root.classList.remove("open");
      document.removeEventListener?.("click", close);
    };
    const toggle = () => {
      const open = list.hidden;
      if (open) {
        list.hidden = false;
        root.classList.add("open");
        setTimeout(() => document.addEventListener?.("click", close), 0);
      } else {
        close();
      }
    };
    root.append(trigger, list);
    return root;
  }

  window.FTReportExport = Object.freeze({menu, run});
})();
