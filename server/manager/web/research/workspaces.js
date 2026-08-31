(() => {
  const fallbackSections = [
    ["researches", "研究"],
    ["graph", "研究图"],
    ["profiles", "研究身份"],
    ["agent-models", "智能体模型"],
  ];

  async function list(context) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    const sections = sectionsFor(context);
    const params = new URLSearchParams(location.search);
    const requested = params.get("section") || "researches";
    const researchID = params.get("research_id") || "";
    const profileID = params.get("profile") || "";
    const allowedSections = new Set(sections.map(item => item[0]));
    const selected = requested === "reports"
      ? "researches"
      : (allowedSections.has(requested)
        ? requested : (sections[0]?.[0] || "researches"));
    const embedded = new URLSearchParams(location.search).get("presentation") === "embedded";
    context.activeNav("research");
    context.setHeading(context.t("研究"), context.t(labelFor(selected, sections)));
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
      if (selected === "profiles") {
        await window.FTStaticLoader?.loadGroups?.(["profile-directory"]);
        if (profileID) {
          // Older links may still carry the embedded query form.  Normalize
          // them to the same independent Profile tab used by row clicks.
          context.navigate(`/profiles/${encodeURIComponent(profileID)}`);
          return;
        } else {
          await FTProfiles.list({...context, content: body}, {embedded: true});
        }
      } else if (selected === "agent-models") {
        await window.FTStaticLoader?.loadGroups?.(["profile-agent-models"]);
        await FTAgentModels.list({...context, content: body});
      } else if (selected === "researches") {
        await window.FTStaticLoader?.loadGroups?.(["research-core"]);
        if (researchID) {
          // The query form is kept only as an old-link bridge.  A concrete
          // Research is always promoted to its own left-sidebar tab; it is
          // never rendered as a nested page inside the Research root tab.
          context.navigate(`/researches/${encodeURIComponent(researchID)}`, {
            parentFolder: "research",
            parentResearchID: researchID,
          });
          return;
        }
        await window.FTResearchCatalog.render({...context, content: body}, body);
      } else if (selected === "graph") {
        await window.FTStaticLoader?.loadGroups?.(["research-graph"]);
        await FTResearchGraphList.render(context, body);
      } else {
        await window.FTResearchCatalog.render({...context, content: body}, body);
      }
      if (!isCurrent()) return;
    } catch (error) {
      if (!isCurrent()) return;
      body.replaceChildren(FTUI.empty(context.t("无法读取"), error.message));
    }
  }

  function sectionsFor(context) {
    const research = (context.modules || []).find(item => item.id === "research");
    const children = Array.isArray(research?.children) ? research.children : [];
    const registered = children.map(item => {
      const path = String(item.path || "");
      const section = new URL(path, "http://factortester.invalid")
        .searchParams.get("section") || String(item.id || "").split(".").pop();
      return [section, item.title_key || item.title || section];
    });
    const sections = registered.length ? registered : fallbackSections.slice(1);
    return [["researches", "研究"], ...sections.filter(item => item[0] !== "researches" && item[0] !== "reports")];
  }

  function labelFor(section, sections) {
    return sections.find(item => item[0] === section)?.[1] || "研究";
  }

  function tabBar(context, selected, embedded) {
    const sections = sectionsFor(context);
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
        url.searchParams.delete("profile");
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
    sectionTabs: tabBar,
    resolvePublicationSource: (...args) =>
      window.FTResearchShared.resolvePublicationSource(...args),
  };
})();
