(() => {
  const normalizeKind = value => String(value || "")
    .trim().toLowerCase().replaceAll("_", "-");

  function digestFor(kind, target) {
    const prefixes = {
      "trial-plan": "trial-plan:sha256:",
      "run-spec": "runspec:sha256:",
    };
    const prefix = prefixes[kind];
    if (!prefix || !String(target || "").startsWith(prefix)) return "";
    return String(target).slice(prefix.length);
  }

  function pathFor(kind, target) {
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
      return digest ? `/api/run-specs/${encodeURIComponent(digest)}` : "";
    }
    if (kind === "run" && value.startsWith("run:")) {
      return `/api/runs/${encodeURIComponent(value.slice("run:".length))}`;
    }
    return "";
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

  function objectTitle(kind, target, label, t) {
    return label || target || t(kind || "引用对象");
  }

  async function loadObject(kind, target, context) {
    const endpoint = pathFor(kind, target);
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
    const {content, t} = context;
    context.activeNav("");
    const heading = objectTitle(kind, target, label, t);
    context.setHeading(heading, t("引用详情"));
    context.updateActiveTab({title: heading});
    content.replaceChildren(FTUI.loading(t("正在读取引用详情…")));
    const loaded = await loadObject(kind, target, context);
    const value = loaded.value;
    const root = document.createElement("div");
    root.className = "detail-stack reference-web-page";
    const title = document.createElement("h2");
    title.textContent = heading;
    root.append(title);
    const scope = document.createElement("p");
    scope.className = "reference-detail-scope";
    scope.textContent = `${t("类型")}: ${kind || t("未知")}`
      + ` · ${t("对象引用")}: ${target || t("未提供")}`;
    root.append(scope);
    const fields = scalarFields(value);
    if (Object.keys(fields).length) {
      root.append(FTUI.table(
        [t("字段"), t("值")],
        FTUI.fieldRows(fields),
      ).shell);
    }
    if (value && Object.keys(value).some(key => (
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

  window.FTReferencePage = Object.freeze({pathFor, render});
})();
