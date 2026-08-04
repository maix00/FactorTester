(() => {
  let publications = [];

  async function list(context) {
    context.activeNav("research");
    context.setHeading("研究", "共享研究报告");
    context.content.replaceChildren(FTUI.loading("正在读取共享报告…"));
    context.toolbar.append(context.button("↻", () => list(context), "刷新"));
    const [releaseResult, publicResult] = await Promise.allSettled([
      context.api(context.servicePath("/api/client/releases/beta.json")),
      context.api("/api/public-research"),
    ]);
    publications = publicResult.status === "fulfilled" ? publicResult.value.reports || [] : [];
    const remoteOnly = new URLSearchParams(location.search).get("mode") === "remote-only";
    const visible = remoteOnly ? publications.filter(item => !item.is_owned) : publications;
    const root = document.createElement("div"); root.className = "detail-stack";
    root.append(clientDownload(context, releaseResult));
    if (visible.length) root.append(publicationSection(context, visible));
    else root.append(FTUI.empty("暂无共享研究报告", "报告所有者在 FTClient 中开启共享后会显示在这里"));
    context.content.replaceChildren(root);
  }

  function clientDownload(context, releaseResult) {
    const section = document.createElement("section"); section.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = "FTClient"; section.append(heading);
    const value = releaseResult.status === "fulfilled" ? releaseResult.value : null;
    const description = document.createElement("p"); description.className = "secondary";
    description.textContent = "本地研究、研究图与报告编辑由 macOS FTClient 提供；Web 端只展示已共享的研究报告。";
    section.append(description);
    if (value?.url) {
      const link = document.createElement("a"); link.className = "button-link primary";
      link.href = value.url; link.textContent = `下载 FTClient ${value.version || value.short_version || "Beta"}`;
      section.append(link);
    } else {
      const note = document.createElement("p"); note.className = "secondary";
      note.textContent = "当前服务暂未提供可下载的客户端安装包"; section.append(note);
    }
    return section;
  }

  function publicationSection(context, reports) {
    const section = document.createElement("section"); section.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = "共享研究报告"; section.append(heading);
    const table = FTUI.table(["报告", "Generation", "访问范围", "同步时间"], reports.map(item => [
      item.title, item.generation, visibilityTitle(item.visibility), FTUI.formatDate(item.updated_at),
    ]));
    [...table.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(reports[index].href));
    });
    section.append(table.shell); return section;
  }

  async function workPackage(context, workPackageRef) {
    context.activeNav("research"); context.setHeading("研究详情", shortRef(workPackageRef));
    context.content.replaceChildren(FTUI.loading("正在读取研究分支…"));
    const value = await context.api(context.servicePath(`/api/profile-research/${encodeURIComponent(workPackageRef)}`));
    context.toolbar.append(
      context.button("‹", () => context.navigate("/research"), "返回研究列表"),
      context.button("研究图", () => context.navigate(`/research-graphs/${encodeURIComponent(graphID(value.branches?.[0]?.graph_ref || value.graph_ref))}`), "查看研究图"),
    );
    const root = document.createElement("div"); root.className = "detail-stack";
    root.append(FTUI.table(["字段", "值"], FTUI.fieldRows({
      research_ref: value.research_ref,
      work_package_ref: value.work_package_ref,
      lifecycle: value.lifecycle,
      mode: value.mode,
      product_group: value.product_group,
      branch_count: value.branch_count,
    })).shell);
    const branches = value.branches || [];
    if (branches.length) {
      const table = FTUI.table(["研究路径", "当前节点", "状态", "更新时间"], branches.map(item => [
        item.label || shortRef(item.branch_ref), item.current_node, statusTitle(item.status), FTUI.formatDate(item.updated_at),
      ]));
      [...table.body.rows].forEach((row, index) => {
        const branchID = String(branches[index].branch_ref || "").split(":").pop();
        row.dataset.href = "true";
        row.addEventListener("click", () => context.navigate(`/research/work/${encodeURIComponent(workPackageRef)}/branch/${encodeURIComponent(branchID)}`));
      });
      root.append(table.shell);
    } else root.append(FTUI.empty("暂无研究路径", "该研究工作包尚无可见分支"));
    if (!publications.length) {
      try {
        publications = (await context.api("/api/public-research")).reports || [];
      } catch (_) {
        publications = [];
      }
    }
    const publication = publications.find(item => item.report_id === value.report_lookup_ref);
    if (publication) {
      const open = document.createElement("button"); open.className = "primary"; open.textContent = "打开研究报告";
      open.onclick = () => context.navigate(publication.href); root.append(open);
    }
    context.content.replaceChildren(root);
  }

  async function branch(context, workPackageRef, branchID) {
    context.activeNav("research"); context.setHeading("研究路径", branchID);
    context.content.replaceChildren(FTUI.loading("正在读取研究路径…"));
    const path = `/api/profile-research/${encodeURIComponent(workPackageRef)}/branches/${encodeURIComponent(branchID)}`;
    const value = await context.api(context.servicePath(path));
    context.setHeading(value.label || "研究路径", value.current_node || branchID);
    context.toolbar.append(
      context.button("‹", () => context.navigate(`/research/work/${encodeURIComponent(workPackageRef)}`), "返回研究详情"),
      context.button("↻", () => branch(context, workPackageRef, branchID), "刷新"),
    );
    const root = document.createElement("div"); root.className = "detail-stack";
    root.append(FTUI.table(["字段", "值"], FTUI.fieldRows({
      branch_ref: value.branch_ref, current_node: value.current_node, status: value.status,
      trial_plan_ref: value.trial_plan_ref, latest_trace_ref: value.latest_trace_ref,
      current_owner_profile_ref: value.current_owner_profile_ref,
    })).shell);
    const obligations = value.research_cycle?.obligations || [];
    if (obligations.length) root.append(section("当前义务", FTUI.table(["义务", "状态", "重要性", "问题"], obligations.map(item => [
      item.title_zh || shortRef(item.obligation_ref), item.status, item.materiality, item.question_summary,
    ])).shell));
    const links = linkList(context, value); if (links.childElementCount) root.append(section("关联对象", links));
    const timeline = await context.api(context.servicePath(`${path}/timeline?limit=50`)).catch(() => null);
    if (timeline?.items?.length) root.append(timelineSection(timeline.items));
    context.content.replaceChildren(root);
  }

  function linkList(context, value) {
    const list = document.createElement("div"); list.className = "reference-list";
    (value.job_refs || []).forEach(ref => list.append(referenceButton(ref, () => context.navigate(`/jobs/${encodeURIComponent(ref.replace(/^job:/, ""))}`))));
    (value.run_refs || []).forEach(ref => list.append(referenceButton(ref)));
    (value.evidence_refs || []).forEach(ref => list.append(referenceButton(ref)));
    if (value.trial_plan_ref) list.append(referenceButton(value.trial_plan_ref));
    return list;
  }

  function referenceButton(label, action = null) {
    const button = document.createElement(action ? "button" : "span");
    button.className = "reference-item"; button.textContent = label;
    if (action) button.onclick = action; return button;
  }

  function timelineSection(items) {
    const table = FTUI.table(["时间", "来源节点", "目标节点", "状态", "Edge"], items.map(item => [
      FTUI.formatDate(item.created_at), item.from_node, item.to_node, item.status, item.edge_ref,
    ]));
    return section("研究时间线", table.shell);
  }

  async function graph(context, graphIDValue) {
    context.activeNav("research"); context.setHeading("研究图", graphIDValue);
    context.content.replaceChildren(FTUI.loading("正在读取研究图…"));
    const path = context.servicePath(`/api/research-graphs/${encodeURIComponent(graphIDValue)}/versions`);
    const values = (await context.api(path)).versions || [];
    if (!values.length) {
      context.content.replaceChildren(FTUI.empty("没有可用研究图", "当前服务未返回研究图版本")); return;
    }
    const picker = document.createElement("select");
    values.slice().sort((a, b) => b.version - a.version).forEach(item => {
      const option = document.createElement("option"); option.value = String(item.version);
      option.textContent = `${item.graph_id}@v${item.version}${item.lifecycle ? ` · ${item.lifecycle}` : ""}`;
      picker.append(option);
    });
    context.toolbar.append(picker, context.button("‹", () => context.navigate("/research"), "返回研究"));
    const render = () => renderGraph(context, values.find(item => String(item.version) === picker.value) || values[0]);
    picker.onchange = render; render();
  }

  function renderGraph(context, value) {
    context.setHeading("研究图", `${value.graph_id}@v${value.version}`);
    const root = document.createElement("div"); root.className = "graph-browser";
    const nodes = document.createElement("div"); nodes.className = "graph-node-list";
    const detail = document.createElement("aside"); detail.className = "graph-detail";
    (value.nodes || []).forEach((node, index) => {
      const card = document.createElement("button"); card.className = "graph-node";
      card.innerHTML = `<span class="graph-node-index"></span><span><b></b><small></small></span>`;
      card.querySelector(".graph-node-index").textContent = String(index + 1);
      card.querySelector("b").textContent = node.node_id;
      card.querySelector("small").textContent = node.purpose || node.kind || "";
      card.onclick = () => showGraphNode(detail, value, node); nodes.append(card);
    });
    root.append(nodes, detail); context.content.replaceChildren(root);
    if (value.nodes?.length) showGraphNode(detail, value, value.nodes[0]);
  }

  function showGraphNode(detail, graphValue, node) {
    detail.replaceChildren();
    const title = document.createElement("h2"); title.textContent = node.node_id; detail.append(title);
    if (node.purpose) detail.append(Object.assign(document.createElement("p"), {textContent: node.purpose}));
    const catalog = Object.fromEntries((graphValue.requirement_catalog?.requirements || []).map(item => [item.requirement_id, item]));
    const refs = [...(node.entry_requirement_refs || []), ...(node.entry_report_refs || []), ...(node.node_report_refs || [])];
    if (refs.length) detail.append(requirementList("节点要求", refs, catalog));
    const edges = (graphValue.edges || []).filter(item => item.from_node === node.node_id);
    edges.forEach(edge => {
      const block = document.createElement("section"); block.className = "graph-edge";
      const heading = document.createElement("h3"); heading.textContent = `${edge.to_node} · ${edge.edge_type || edge.edge_id}`; block.append(heading);
      const requirements = [...(edge.obligation_requirement_refs || []), ...(edge.report_requirement_refs || [])];
      if (requirements.length) block.append(requirementList("Edge 要求", requirements, catalog));
      detail.append(block);
    });
  }

  function requirementList(title, refs, catalog) {
    const root = document.createElement("section"); root.className = "requirement-list";
    const heading = document.createElement("h3"); heading.textContent = title; root.append(heading);
    refs.forEach(raw => {
      const ref = String(raw).replace(/^requirement:/, ""); const item = catalog[ref] || {};
      const row = document.createElement("div"); row.className = "requirement-row";
      const label = document.createElement("b"); label.textContent = item.title_zh || ref;
      const copy = document.createElement("small"); copy.textContent = item.description_zh || item.description || "";
      row.append(label, copy); root.append(row);
    });
    return root;
  }

  function section(title, child) {
    const root = document.createElement("section"); root.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = title; root.append(heading, child); return root;
  }
  function shortRef(value) { return String(value || "").split(":").pop() || ""; }
  function graphID(value) { return String(value || "factor-research").split("@", 1)[0] || "factor-research"; }
  function statusTitle(value) { return {running: "进行中", stopped: "已停止", paused: "已暂停", active: "活跃"}[value] || value || ""; }
  function visibilityTitle(value) { return {private: "仅自己", authorized: "授权用户", public: "公开"}[value] || value || ""; }

  window.FTResearch = {branch, graph, list, workPackage};
})();
