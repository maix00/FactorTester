(() => {
  async function render(context, mount) {
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    const graphID = "factor-research";
    const locale = graphLocale();
    const localeQuery = `?locale=${encodeURIComponent(locale)}`;
    const [versionsResult, activeResult] = await Promise.allSettled([
      context.api(context.servicePath(
        `/api/research-graphs/${graphID}/versions${localeQuery}`,
      )),
      context.api(context.servicePath(
        `/api/research-graphs/${graphID}/active${localeQuery}`,
      )),
    ]);
    if (!isCurrent()) return;
    if (versionsResult.status !== "fulfilled") throw versionsResult.reason;
    const versions = versionsResult.value.versions || [];
    const active = activeResult.status === "fulfilled" ? activeResult.value.graph : null;
    const requested = Number(new URLSearchParams(location.search).get("version"));
    const graph = versions.find(item => item.version === requested) || active || versions.at(-1);
    if (!graph) {
      mount.append(FTUI.empty(
        context.t("尚无研究图版本"),
        context.t("没有可读取的研究图服务器"),
      ));
      return;
    }

    const section = document.createElement("section");
    section.className = "research-graph-view";
    const toolbar = document.createElement("div");
    toolbar.className = "research-graph-toolbar";
    const title = document.createElement("h2");
    title.textContent = `${graph.presentation?.title || context.t("研究图")} @v${graph.version}`;
    toolbar.append(title);
    const actions = document.createElement("div");
    actions.className = "research-graph-actions";
    actions.append(versionPicker(context, versions, graph));
    const download = document.createElement("a");
    download.className = "button secondary";
    download.href = context.servicePath(
      `/api/research-graphs/${encodeURIComponent(graphID)}/versions/${graph.version}/yaml${localeQuery}`,
    );
    download.download = "";
    download.textContent = context.t("下载 YAML");
    download.title = context.t("下载当前研究图版本");
    download.addEventListener("click", event => {
      event.preventDefault();
      void downloadGraph(context, download.href, graph, graphID);
    });
    actions.append(download);
    toolbar.append(actions);
    section.append(toolbar);

    const meta = document.createElement("p");
    meta.className = "secondary research-graph-meta";
    meta.textContent = [
      `${context.t("当前激活版本")}: v${active?.version || "—"}`,
      formatCount(context, "%lld 个节点", (graph.nodes || []).length),
      formatCount(context, "%lld 条边", (graph.edges || []).length),
      `${context.t("内容哈希", "Content hash")}: ${graph.content_hash || "—"}`,
      graph.presentation_status === "available"
        ? `${context.t("语言版本")}: ${graph.presentation_locale}`
        : context.t("当前语言版本尚未发布"),
    ].join(" · ");
    section.append(meta);
    if (graph.presentation?.description) {
      const description = document.createElement("p");
      description.className = "secondary research-graph-description";
      description.textContent = graph.presentation.description;
      section.append(description);
    }

    const layout = document.createElement("div");
    layout.className = "research-graph-layout";
    const surface = document.createElement("div");
    surface.className = "research-graph-surface";
    const canvas = document.createElement("div");
    canvas.className = "research-graph-canvas";
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", context.t("研究图拓扑", "Research graph topology"));
    surface.append(canvas);
    const details = document.createElement("aside");
    details.className = "research-graph-details";
    layout.append(surface, details);
    section.append(layout);
    mount.append(section);
    renderNetwork(context, graph, canvas, details, surface);
  }

  function versionPicker(context, versions, graph) {
    const picker = document.createElement("select");
    picker.className = "graph-version-picker";
    picker.setAttribute("aria-label", context.t("研究图版本"));
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
    return picker;
  }

  async function downloadGraph(context, href, graph, graphID) {
    try {
      const response = await context.raw(href);
      const blob = await response.blob();
      const graphName = String(graph.graph_id || graphID).replace(
        /[^A-Za-z0-9._-]+/g, "-",
      ) || "research-graph";
      const localeSuffix = graph.presentation
        ? `-${graph.presentation.locale}-${String(
          graph.presentation.translation_hash || "",
        ).slice(0, 16)}`
        : `-${String(graph.content_hash || "").slice(0, 16)}`;
      const filename = `${graphName}-v${graph.version}${localeSuffix}.yaml`;
      const objectURL = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectURL;
      link.download = filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
    } catch (error) {
      context.showNotice?.(error.message || String(error), true);
    }
  }

  function renderNetwork(context, graph, canvas, details, surface) {
    if (typeof window.cytoscape !== "function") {
      details.append(FTUI.empty(
        context.t("网络图不可用"),
        context.t("图形资源尚未加载"),
      ));
      return;
    }
    const cy = window.cytoscape({
      container: canvas,
      elements: graphElements(graph),
      style: graphStyle(),
      layout: {
        name: "cose", animate: false, fit: true, padding: 42,
        idealEdgeLength: 110, nodeRepulsion: 5000, edgeElasticity: 0.35,
      },
      minZoom: 0.25,
      maxZoom: 3,
      wheelSensitivity: 0.18,
    });
    const controls = document.createElement("div");
    controls.className = "research-graph-controls";
    controls.append(
      graphButton(context, "+", "放大", () => cy.zoom(cy.zoom() * 1.18)),
      graphButton(context, "−", "缩小", () => cy.zoom(cy.zoom() / 1.18)),
      graphButton(context, "⌖", "适应窗口", () => cy.fit(undefined, 42)),
      graphButton(context, "↻", "重新布局", () => cy.layout({
        name: "cose", animate: true, fit: true, padding: 42,
        idealEdgeLength: 110, nodeRepulsion: 5000, edgeElasticity: 0.35,
      }).run()),
    );
    surface.append(controls);
    details.append(FTUI.empty(
      context.t("选择节点或边"),
      context.t("点击连线查看义务"),
    ));
    cy.on("tap", "node", event => {
      focus(cy, event.target);
      showNode(context, event.target.data(), details);
    });
    cy.on("tap", "edge", event => {
      focus(cy, event.target);
      showEdge(context, event.target.data(), details);
    });
    cy.on("tap", event => {
      if (event.target !== cy) return;
      cy.elements().removeClass("faded");
      details.replaceChildren(FTUI.empty(
        context.t("选择节点或边"),
        context.t("点击连线查看义务"),
      ));
    });
  }

  function graphButton(context, label, title, action) {
    const button = context.button(label, action, context.t(title));
    button.className = "research-graph-control";
    button.type = "button";
    return button;
  }

  function graphElements(graph) {
    const presentation = graph.presentation || {};
    const nodePresentations = presentation.nodes || {};
    const nodes = (graph.nodes || []).map(node => {
      const localizedNode = nodePresentations[node.node_id] || {};
      return {
        data: {
          id: `node:${node.node_id}`,
          nodeID: node.node_id,
          label: localizedNode.label || node.node_id,
          kind: node.kind || "research",
          enforcement: node.enforcement || "advisory",
          purpose: localizedNode.purpose || node.purpose || "",
          entryEvidence: localizedNode.entry_evidence || node.entry_evidence || [],
          exitEvidence: localizedNode.exit_evidence || node.exit_evidence || [],
          requiredCapabilities: node.required_capabilities || [],
          conditionalCapabilities: node.conditional_capabilities || [],
        },
      };
    });
    const edges = graph.edges || [];
    if (edges.some(edge => edge.from_node === "*")) {
      const wildcard = presentation.wildcard || {};
      nodes.push({data: {
        id: "node:any",
        nodeID: "*",
        label: wildcard.label || "*",
        kind: "wildcard",
        enforcement: "advisory",
        purpose: wildcard.purpose || "",
        synthetic: true,
      }});
    }
    return [
      ...nodes,
      ...edges.map(edge => {
        const from = edge.from_node === "*" ? "any" : edge.from_node;
        const localizedEdge = (presentation.edges || {})[edge.edge_id] || {};
        return {data: {
          id: `edge:${edge.edge_id}`,
          source: `node:${from}`,
          target: `node:${edge.to_node}`,
          label: localizedEdge.label || edge.edge_type || edge.edge_id,
          edgeID: edge.edge_id,
          edgeType: edge.edge_type || "recommended",
          riskLevel: edge.risk_level || "",
          serverAction: edge.server_action || "",
          fromNode: edge.from_node,
          toNode: edge.to_node,
          requiredEvidence: edge.required_evidence || [],
          requiredResearchEvidence: edge.required_research_evidence || [],
          requiredTransitionFacts: edge.required_transition_facts || [],
          requiredCapabilities: edge.required_capabilities || [],
          description: localizedEdge.description || "",
        }};
      }),
    ];
  }

  function graphStyle() {
    return [
      {selector: "node", style: {
        label: "data(label)", "font-size": 12, "text-wrap": "wrap",
        "text-max-width": 150, "text-valign": "center", "text-halign": "center",
        color: "#172033", "background-color": "#dbeafe", "border-width": 2,
        "border-color": "#4684c5", width: 48, height: 48,
      }},
      {selector: 'node[enforcement = "deterministic"]', style: {"background-color": "#dcfce7", "border-color": "#16824b"}},
      {selector: 'node[enforcement = "audited"]', style: {"background-color": "#fef3c7", "border-color": "#b7791f"}},
      {selector: 'node[kind = "wildcard"]', style: {shape: "diamond", "background-color": "#f3e8ff", "border-color": "#8b5cf6", "border-style": "dashed"}},
      {selector: "edge", style: {
        label: "data(label)", "font-size": 10, color: "#657084", width: 2,
        "line-color": "#91a4bc", "target-arrow-color": "#91a4bc",
        "target-arrow-shape": "triangle", "curve-style": "bezier",
        "text-background-color": "#ffffff", "text-background-opacity": 0.8,
        "text-background-padding": 2,
      }},
      {selector: 'edge[edgeType = "conditional"]', style: {"line-style": "dashed"}},
      {selector: 'edge[edgeType = "failure"]', style: {"line-color": "#c2413a", "target-arrow-color": "#c2413a"}},
      {selector: 'edge[edgeType = "recovery"]', style: {"line-color": "#16824b", "target-arrow-color": "#16824b"}},
      {selector: ".faded", style: {opacity: 0.16}},
      {selector: ":selected", style: {"overlay-color": "#2563eb", "overlay-opacity": 0.12, "border-width": 4}},
    ];
  }

  function focus(cy, element) {
    cy.elements().addClass("faded");
    element.closedNeighborhood().removeClass("faded");
  }

  function showNode(context, data, details) {
    details.replaceChildren(detailHeading(context, "节点：%@", data.label || data.nodeID));
    appendField(details, context.t("类型"), data.kind);
    appendField(details, context.t("执行约束"), data.enforcement);
    appendField(details, context.t("研究图对象"), data.nodeID);
    appendField(details, context.t("用途"), data.purpose);
    appendList(details, context.t("所需能力"), data.requiredCapabilities);
    appendList(details, context.t("期望证据"), [...data.entryEvidence, ...data.exitEvidence]);
    appendList(details, context.t("条件能力"), data.conditionalCapabilities);
  }

  function showEdge(context, data, details) {
    details.replaceChildren(detailHeading(
      context,
      "边：%@ 到 %@",
      data.fromNode,
      data.toNode,
    ));
    appendField(details, context.t("类型"), data.edgeType);
    appendField(details, context.t("风险等级"), data.riskLevel);
    appendField(details, context.t("服务器动作"), data.serverAction);
    appendField(details, context.t("说明"), data.description);
    appendList(details, context.t("期望证据"), data.requiredEvidence);
    appendList(details, context.t("研究证据"), data.requiredResearchEvidence);
    appendList(details, context.t("转换事实"), data.requiredTransitionFacts);
    appendList(details, context.t("所需能力"), data.requiredCapabilities);
  }

  function detailHeading(context, key, ...values) {
    const heading = document.createElement("h3");
    heading.textContent = values.reduce(
      (result, value) => result.replace("%@", String(value)),
      context.t(key, key),
    );
    return heading;
  }

  function appendField(parent, label, value) {
    if (value === undefined || value === null || value === "") return;
    const row = document.createElement("div");
    row.className = "research-graph-detail-field";
    const name = document.createElement("small");
    name.textContent = label;
    const content = document.createElement("div");
    content.textContent = valueText(value);
    row.append(name, content);
    parent.append(row);
  }

  function appendList(parent, label, values) {
    if (!Array.isArray(values) || !values.length) return;
    const section = document.createElement("section");
    section.className = "research-graph-detail-list";
    const heading = document.createElement("small");
    heading.textContent = `${label}（${values.length}）`;
    const list = document.createElement("ul");
    values.forEach(value => {
      const item = document.createElement("li");
      item.textContent = valueText(value);
      list.append(item);
    });
    section.append(heading, list);
    parent.append(section);
  }

  function valueText(value) {
    if (typeof value === "string") return value;
    try { return JSON.stringify(value); } catch (_) { return String(value); }
  }

  function formatCount(context, key, value) {
    return context.t(key, key).replace("%lld", String(value));
  }

  function graphLocale() {
    return String(document.documentElement.lang || "zh-Hans")
      .toLowerCase().startsWith("en") ? "en" : "zh-Hans";
  }

  window.FTResearchGraph = Object.freeze({render});
})();
