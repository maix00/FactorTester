(() => {
  const normalizeKind = value => String(value || "")
    .trim().toLowerCase().replaceAll("_", "-");

  const presentations = {
    evidence: {title: "证据", symbol: "doc.text.magnifyingglass", tone: "evidence"},
    task: {title: "任务", symbol: "checklist", tone: "link"},
    job: {title: "测试任务", symbol: "checklist", tone: "link"},
    report: {title: "研究报告", symbol: "doc.text", tone: "link"},
    trial_plan: {title: "试验计划", symbol: "list.bullet.clipboard", tone: "link"},
    run_spec: {title: "运行配置", symbol: "slider.horizontal.3", tone: "link"},
    run: {title: "运行", symbol: "play.circle", tone: "link"},
    factor: {title: "因子", symbol: "function", tone: "factor"},
    factor_family: {title: "因子家族", symbol: "function", tone: "factor"},
    factor_set: {title: "因子集合", symbol: "square.stack.3d.up", tone: "factor"},
    profile: {title: "Profile", symbol: "person.crop.rectangle.stack", tone: "profile"},
    profile_revision: {title: "Profile 版本", symbol: "person.crop.rectangle.stack", tone: "profile"},
    product: {title: "产品", symbol: "shippingbox", tone: "product"},
    product_group: {title: "产品组", symbol: "shippingbox.and.arrow.backward", tone: "product"},
    contract: {title: "合约", symbol: "doc.text", tone: "product"},
    continuous_contract: {title: "连续合约", symbol: "chart.line.uptrend.xyaxis", tone: "product"},
    file: {title: "研究文件", symbol: "doc.text", tone: "link"},
    url: {title: "网页链接", symbol: "safari", tone: "link"},
  };

  function presentationFor(kind) {
    const value = normalizeKind(kind).replaceAll("-", "_");
    return presentations[value] || {
      title: "引用对象", symbol: "link", tone: "link",
    };
  }

  function digestFor(kind, target) {
    const prefixes = {
      "trial-plan": ["trial-plan:sha256:"],
      "run-spec": [
        "runspec:sha256:", "run-spec:sha256:", "run_spec:sha256:",
      ],
    };
    const prefix = (prefixes[kind] || []).find(item =>
      String(target || "").startsWith(item)
    );
    if (!prefix || !String(target || "").startsWith(prefix)) return "";
    return String(target).slice(prefix.length);
  }

  function pathFor(kind, target, serverID = "") {
    kind = normalizeKind(kind);
    const value = String(target || "");
    if (kind === "evidence" && value.startsWith("evidence:")) {
      return `/api/research-evidence/${encodeURIComponent(value)}`;
    }
    if (kind === "trial-plan") {
      const digest = digestFor(kind, value);
      return digest ? `/api/trial-plans/direct/${encodeURIComponent(digest)}` : "";
    }
    if (kind === "run-spec") {
      const digest = digestFor(kind, value);
      if (!digest) return "";
      const endpoint = `/api/run-specs/${encodeURIComponent(digest)}`;
      return serverID
        ? `${endpoint}?server_id=${encodeURIComponent(serverID)}`
        : endpoint;
    }
    if (kind === "run" && value.startsWith("run:")) {
      return `/api/runs/${encodeURIComponent(value.slice("run:".length))}`;
    }
    return "";
  }

  function routeFor(kind, target, label = "", serverID = "") {
    const query = new URLSearchParams({
      kind: normalizeKind(kind), target: String(target || ""),
    });
    if (label) query.set("label", String(label));
    if (serverID) query.set("server_id", String(serverID));
    return `/reference?${query.toString()}`;
  }

  function jobRouteFor(identity) {
    const jobID = String(identity?.job_id || "")
      .replace(/^(?:job|research-job|task):/, "").trim();
    if (!jobID) return "";
    const port = Number(identity?.service_port);
    const prefix = Number.isInteger(port) && port > 0 && port <= 65_535
      ? `/jobs/${port}/` : "/jobs/";
    const serverID = String(identity?.server_id || "").trim();
    const query = serverID
      ? `?server_id=${encodeURIComponent(serverID)}` : "";
    return `${prefix}${encodeURIComponent(jobID)}${query}`;
  }

  function detailValue(fields, name) {
    return (Array.isArray(fields) ? fields : [])
      .find(item => item?.name === name)?.value || "";
  }

  function resourceEndpoint(input) {
    const resourceID = detailValue(input.detailFields, "resource_id");
    const publicationID = detailValue(input.detailFields, "publication_id");
    if (!/^[a-f0-9]{24}$/i.test(resourceID) || !publicationID) return null;
    if (publicationID.startsWith("local:") || publicationID.startsWith("server:")) {
      const server = publicationID.startsWith("server:");
      const prefix = server ? "server:" : "local:";
      const base = server ? "/api/server-research/" : "/api/client/research/";
      return `${base}${encodeURIComponent(publicationID.slice(prefix.length))}`
        + `/local-resources/${encodeURIComponent(resourceID)}?inline=1`;
    }
    return `/api/public-research/${encodeURIComponent(publicationID)}`
      + `/local-resources/${encodeURIComponent(resourceID)}?inline=1`;
  }

  function unwrap(kind, payload) {
    if (!payload || typeof payload !== "object") return payload;
    const keys = {
      evidence: "evidence",
      "trial-plan": "trial_plan",
      "run-spec": "run_spec",
      run: "run",
    };
    const key = keys[kind];
    return key && payload[key] && typeof payload[key] === "object"
      ? payload[key] : payload;
  }

  function scalarFields(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, item]) => (
      item == null || ["string", "number", "boolean"].includes(typeof item)
    )));
  }

  function fallbackFields(fields) {
    if (!Array.isArray(fields)) return {};
    return Object.fromEntries(fields
      .filter(item => item && item.name && typeof item.value === "string")
      .slice(0, 16)
      .map(item => [item.name, item.value]));
  }

  function objectTitle(kind, target, label, t) {
    if (normalizeKind(kind) === "run-spec") return t("运行配置");
    return label || target || t(kind || "引用对象");
  }

  function headerFor(kind, heading, t) {
    const presentation = presentationFor(kind);
    const header = document.createElement("div");
    header.className = "reference-detail-header";
    const icon = FTIcons.node(presentation.symbol, "reference-detail-icon");
    icon.dataset.referenceTone = presentation.tone;
    header.append(icon);
    const headerCopy = document.createElement("div");
    headerCopy.className = "reference-detail-header-copy";
    const title = document.createElement("h2");
    title.textContent = heading;
    headerCopy.append(title);
    const type = document.createElement("span");
    type.className = "reference-detail-type";
    type.textContent = t(presentation.title, presentation.title);
    headerCopy.append(type);
    header.append(headerCopy);
    return {presentation, header};
  }

  async function loadObject(kind, target, context, serverID = "") {
    const endpoint = pathFor(kind, target, serverID);
    if (!endpoint) return {value: null, endpoint: ""};
    try {
      return {value: unwrap(kind, await context.api(endpoint)), endpoint};
    } catch (_) {
      // A typed link may be valid in a report while its detail endpoint is
      // private or unavailable to this session.  Keep the reference page
      // useful by showing its stable identity instead of a JSON error.
      return {value: null, endpoint};
    }
  }

  async function render(context, input = {}) {
    const kind = normalizeKind(input.kind);
    const target = String(input.target || "");
    const label = String(input.label || "");
    const serverID = String(
      input.serverID || new URLSearchParams(location.search).get("server_id") || "",
    ).trim();
    const {content, t} = context;
    context.activeNav("");
    const heading = objectTitle(kind, target, label, t);
    context.setHeading(heading, t("引用详情"));
    context.updateActiveTab({title: heading});
    content.replaceChildren(FTUI.loading(t("正在读取引用详情…")));
    const loaded = await loadObject(kind, target, context, serverID);
    const value = loaded.value;
    const {presentation, header} = headerFor(kind, heading, t);
    const root = document.createElement("div");
    root.className = `detail-stack reference-web-page reference-tone-${presentation.tone}`;
    root.append(header);
    const scope = document.createElement("p");
    scope.className = "reference-detail-scope";
    scope.textContent = `${t("类型")}: ${kind || t("未知")}`
      + ` · ${t("对象引用")}: ${target || t("未提供")}`;
    root.append(scope);
    const routeFields = input.componentID
      ? [{name: "component_id", value: String(input.componentID)}, ...(input.detailFields || [])]
      : input.detailFields;
    const fileEndpoint = kind === "file" ? resourceEndpoint(input) : null;
    const specializedRunSpec = kind === "run-spec" && value
      && window.FTRunSpecView;
    const valueFields = scalarFields(value);
    const fields = Object.keys(valueFields).length
      ? valueFields : fallbackFields(routeFields);
    if (specializedRunSpec) {
      root.append(FTRunSpecView.render(context, value));
    } else if (Object.keys(fields).length) {
      root.append(FTUI.table(
        [t("字段"), t("值")],
        FTUI.fieldRows(fields),
      ).shell);
    }
    if (kind === "file" && fileEndpoint) {
      const section = document.createElement("section");
      section.className = "reference-file-download";
      const fileHeading = document.createElement("h3");
      fileHeading.textContent = t("研究文件");
      const download = document.createElement("button");
      download.type = "button";
      download.textContent = t("下载文件");
      download.addEventListener("click", async () => {
        try {
          const response = await fetch(fileEndpoint, {credentials: "same-origin"});
          if (!response.ok) throw new Error("download failed");
          const blob = await response.blob();
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement("a");
          anchor.href = url;
          anchor.download = detailValue(input.detailFields, "filename") || "resource";
          document.body.append(anchor);
          anchor.click();
          anchor.remove();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (_) {
          context.showNotice?.(t("研究文件下载失败"), true);
        }
      });
      section.append(fileHeading, download);
      root.append(section);
    }
    if (kind === "evidence" && Array.isArray(value?.fragments)) {
      const section = document.createElement("section");
      section.className = "reference-evidence-sources";
      const headingNode = document.createElement("h3");
      headingNode.textContent = t("来源测试任务");
      section.append(headingNode);
      const seen = new Set();
      for (const fragment of value.fragments) {
        const source = fragment?.source;
        if (source?.source_kind !== "job") continue;
        const identity = source.identity || {};
        const route = jobRouteFor(identity);
        if (!route || seen.has(route)) continue;
        seen.add(route);
        const link = document.createElement("a");
        link.href = route;
        link.textContent = fragment.title_zh || identity.job_id || route;
        link.addEventListener("click", event => {
          event.preventDefault();
          context.navigate(route);
        });
        section.append(link);
      }
      if (seen.size) root.append(section);
    }
    if (!specializedRunSpec && value && Object.keys(value).some(key => (
      value[key] && typeof value[key] === "object"
    ))) {
      const headingNode = document.createElement("h3");
      headingNode.textContent = t("冻结对象");
      root.append(headingNode, FTUI.code(value));
    } else if (!value) {
      const note = document.createElement("p");
      note.className = "reference-detail-empty";
      note.textContent = loaded.endpoint
        ? t("当前会话无法读取该对象的详细内容，已保留稳定引用")
        : t("该对象暂未提供独立详情接口，已保留稳定引用");
      root.append(note);
    }
    content.replaceChildren(root);
  }

  window.FTReferencePage = Object.freeze({
    pathFor, routeFor, jobRouteFor, presentationFor, headerFor,
    resourceEndpoint, render,
  });
})();
