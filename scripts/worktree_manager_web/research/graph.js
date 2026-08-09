(() => {
  async function render(context, mount) {
    const graphID = "factor-research";
    const [versionsResult, activeResult] = await Promise.allSettled([
      context.api(context.servicePath(`/api/research-graphs/${graphID}/versions`)),
      context.api(context.servicePath(`/api/research-graphs/${graphID}/active`)),
    ]);
    if (versionsResult.status !== "fulfilled") throw versionsResult.reason;
    const versions = versionsResult.value.versions || [];
    const active = activeResult.status === "fulfilled" ? activeResult.value.graph : null;
    const currentVersion = Number(new URLSearchParams(location.search).get("version"));
    const graph = versions.find(item => item.version === currentVersion) || active || versions.at(-1);
    if (!graph) {
      mount.append(FTUI.empty(context.t("暂无研究图"), context.t("服务器尚未提供可浏览的研究图版本")));
      return;
    }
    const section = document.createElement("section");
    section.className = "job-section";
    const header = document.createElement("div");
    header.className = "research-graph-toolbar";
    const title = document.createElement("h2");
    title.textContent = `${context.t("研究图")} ${graph.graph_id || graphID}@v${graph.version}`;
    header.append(title);
    const picker = document.createElement("select");
    picker.className = "graph-version-picker";
    versions.forEach(item => {
      const option = document.createElement("option");
      option.value = item.version;
      option.textContent = `v${item.version} · ${item.lifecycle || ""}`;
      option.selected = item.version === graph.version;
      picker.append(option);
    });
    picker.addEventListener("change", () => {
      const url = new URL(location.href);
      url.searchParams.set("section", "graph");
      url.searchParams.set("version", picker.value);
      history.pushState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    header.append(picker);
    section.append(header);
    const meta = document.createElement("p");
    meta.className = "secondary";
    meta.textContent = `${context.t("当前激活版本")}: v${active?.version || "—"} · ${graph.content_hash || ""}`;
    section.append(meta);
    const browser = document.createElement("div");
    browser.className = "graph-browser";
    browser.append(nodeList(context, graph), edgeList(context, graph));
    section.append(browser);
    mount.append(section);
  }

  function nodeList(context, graph) {
    const section = document.createElement("section");
    section.className = "graph-node-list";
    const heading = document.createElement("h3");
    heading.textContent = `${context.t("节点")}（${(graph.nodes || []).length}）`;
    section.append(heading);
    (graph.nodes || []).forEach((node, index) => {
      const item = document.createElement("article");
      item.className = "graph-node graph-node-static";
      item.innerHTML = `<span class="graph-node-index">${index + 1}</span><span><b></b><small></small></span>`;
      item.querySelector("b").textContent = node.title || node.label || node.node_id || node.id;
      item.querySelector("small").textContent = node.node_id || node.id || "";
      section.append(item);
    });
    return section;
  }

  function edgeList(context, graph) {
    const section = document.createElement("section");
    section.className = "graph-detail graph-edge-list";
    const heading = document.createElement("h3");
    heading.textContent = `${context.t("边与义务")}（${(graph.edges || []).length}）`;
    section.append(heading);
    (graph.edges || []).forEach(edge => {
      const item = document.createElement("article");
      item.className = "graph-edge";
      const title = document.createElement("b");
      title.textContent = `${edge.source || edge.from || edge.from_node || ""} → ${edge.target || edge.to || edge.to_node || ""}`;
      item.append(title);
      const requirements = edge.requirements || edge.edge_requirements || edge.obligations || [];
      if (requirements.length) {
        const list = document.createElement("div");
        list.className = "requirement-list";
        requirements.forEach(requirement => {
          const row = document.createElement("div");
          row.className = "requirement-row";
          row.innerHTML = "<b></b><small></small>";
          row.querySelector("b").textContent = requirement.title_zh || requirement.title || requirement.requirement_id || requirement.id || "";
          row.querySelector("small").textContent = requirement.requirement_id || requirement.id || "";
          list.append(row);
        });
        item.append(list);
      }
      section.append(item);
    });
    return section;
  }

  window.FTResearchGraph = Object.freeze({render});
})();
