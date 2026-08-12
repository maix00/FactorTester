(() => {
  const sections = [
    ["local", "本地研究"],
    ["shared", "共享研究"],
    ["graph", "研究图"],
  ];

  async function list(context) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    const selected = new URLSearchParams(location.search).get("section") || "shared";
    const embedded = new URLSearchParams(location.search).get("presentation") === "embedded";
    context.activeNav("research");
    context.setHeading(context.t("研究"), context.t(labelFor(selected)));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取研究…")));
    // The Web page is the single owner of the research section switcher in
    // both standalone Web and embedded Swift presentation.  Swift owns the
    // surrounding tab and WebView session, but must not duplicate this
    // control with a second native picker.
    context.toolbar.append(tabBar(context, selected, embedded));
    context.toolbar.append(context.button("↻", () => list(context), context.t("刷新")));
    const body = document.createElement("div");
    body.className = "research-workspace-page";
    body.append(FTUI.loading(context.t("正在读取研究…")));
    context.content.replaceChildren(body);
    try {
      // Keep an explicit loading state visible until the selected page has
      // finished its first request. Clearing the container before the async
      // branch used to leave a blank research page during cold start.
      body.replaceChildren();
      if (selected === "local") await FTResearchLocal.render(context, body, embedded);
      else if (selected === "graph") await FTResearchGraph.render(context, body);
      else await FTResearchShared.render(context, body, embedded);
      if (!isCurrent()) return;
    } catch (error) {
      if (!isCurrent()) return;
      body.replaceChildren(FTUI.empty(context.t("无法读取"), error.message));
    }
  }

  function labelFor(section) {
    return sections.find(item => item[0] === section)?.[1] || "共享研究";
  }

  function tabBar(context, selected, embedded) {
    const nav = document.createElement("nav");
    nav.className = "research-section-tabs";
    nav.setAttribute("aria-label", context.t("研究页面"));
    sections.forEach(([id, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `research-section-tab${id === selected ? " active" : ""}`;
      button.textContent = context.t(label);
      button.setAttribute("aria-current", id === selected ? "page" : "false");
      button.addEventListener("click", () => {
        const url = new URL(location.href);
        url.searchParams.set("section", id);
        history.pushState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
        // In the embedded client the Web page owns rendering, while Swift
        // owns the lightweight tab session.  Persist only the section key;
        // do not ask Swift to open a second research tab.
        if (embedded && window.webkit?.messageHandlers?.researchNavigation) {
          window.webkit.messageHandlers.researchNavigation.postMessage({
            path: `/research?section=${encodeURIComponent(id)}`,
          });
        }
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
      nav.append(button);
    });
    return nav;
  }

  // Keep the source resolver on the public research seam for integrations
  // that only load the page coordinator; ownership remains in shared.js.
  window.FTResearch = {
    list,
    resolvePublicationSource: (...args) =>
      window.FTResearchShared.resolvePublicationSource(...args),
  };
})();
