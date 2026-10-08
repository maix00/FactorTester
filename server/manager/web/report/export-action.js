(() => {
  const FORMATS = [
    ["md", "导出 Markdown"],
    ["pdf", "导出 PDF"],
  ];

  // A report is addressed by the same three channels the reader already uses:
  // a server-held tree (``server:``), the client's own copy (``local:``) and a
  // published projection (a bare publication id).  The report tab and the
  // dedicated report page both hand over that publication id, so one address
  // builder serves every page and channel.
  function address(target) {
    const explicit = String(
      target?.publication_id || target?.source_ref || "",
    ).trim();
    if (explicit.startsWith("local:")) {
      return {channel: "client", ref: explicit.slice("local:".length)};
    }
    if (explicit.startsWith("server:")) {
      return {channel: "server", ref: explicit.slice("server:".length)};
    }
    if (explicit) {
      // A published projection keeps its own key even when that key happens to
      // look like a tree reference.
      const kind = String(
        target?.source_kind || target?.selected_branch?.source_kind || "",
      ).trim();
      if (kind === "publication") return {channel: "public", ref: explicit};
      // A tree reference is profile:package:branch; anything else is already
      // the canonical publication key.
      return explicit.includes(":")
        ? {channel: "server", ref: explicit}
        : {channel: "public", ref: explicit};
    }
    const parts = [
      target?.profile_ref || target?.profile_id || "",
      target?.report_workspace_id || "",
      target?.branch_id || "",
    ].map(value => String(value || "").trim());
    return parts.every(Boolean)
      ? {channel: "server", ref: parts.join(":")} : null;
  }

  function channelPath(channel, ref) {
    const encoded = encodeURIComponent(ref);
    if (channel === "client") return `/api/client/research/${encoded}`;
    if (channel === "server") return `/api/server-research/${encoded}`;
    return `/api/public-research/${encoded}`;
  }

  function ownerRef(target) {
    return String(target?.owner_ref || "").trim();
  }

  function exportURL(target, format) {
    const resolved = address(target);
    if (!resolved) return "";
    const query = [`format=${encodeURIComponent(format)}`];
    // Only a server tree can belong to another profile and needs the reader's
    // authorization; a local copy and a publication are read as-is.
    if (resolved.channel === "server" && ownerRef(target)) {
      query.push(`target_ref=${encodeURIComponent(ownerRef(target))}`);
    }
    return `${channelPath(resolved.channel, resolved.ref)}/export?${query.join("&")}`;
  }

  function bridgePayload(target, format) {
    return {
      publication_id: String(target?.publication_id || "").trim(),
      profile_ref: String(target?.profile_ref || target?.profile_id || "").trim(),
      report_workspace_id: String(target?.report_workspace_id || "").trim(),
      branch_id: String(target?.branch_id || "").trim(),
      owner_ref: ownerRef(target),
      // The client names the format as the CLI does.
      format: format === "md" ? "markdown" : String(format || ""),
      title: String(target?.title || ""),
    };
  }

  function safeName(title) {
    const value = String(title || "").replace(/[/\\:]/g, "-").trim();
    return value || "report";
  }

  async function run(context, target, format) {
    // Embedded in the Swift client: the native export owns the local tree and
    // the PDF renderer, so hand the request over.  For a report the client
    // cannot export locally the native handler falls back to the manager
    // export below.
    const bridge = window.webkit?.messageHandlers?.researchReportExport;
    if (bridge && typeof bridge.postMessage === "function") {
      bridge.postMessage(bridgePayload(target, format));
      return;
    }
    const url = exportURL(target, format);
    if (!url) {
      context.showNotice?.(context.t("无法识别该报告的来源，不能导出"), true);
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
      // The registry glyph every other download control in the app uses.
      context, "arrow.down.circle", context.t("导出报告"), () => toggle(),
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
