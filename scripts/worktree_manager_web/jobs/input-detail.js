(() => {
  const FACTOR_PREFIX = "factor_source__";

  async function show(context, port, jobID, inputName) {
    context.activeNav("jobs");
    context.setHeading(context.t("运行输入详情"));
    if (!context.session) return context.openLogin(context.t("登录后才能查看运行输入"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取运行输入…")));
    const loaded = await FTJobs.loadDetail(context, port, jobID);
    if (context.isRouteCurrent?.() === false) return;
    const inputs = loaded.taskDetail.input_artifacts || [];
    const artifact = inputs.find(item => item.name === inputName && item.state === "active");
    if (!artifact) throw new Error(context.t("运行输入不存在或已经清除"));
    const path = artifactPath(jobID, artifact.name, loaded.portQuery);
    const previewPath = artifactPath(jobID, artifact.name, loaded.portQuery, true);
    const response = await context.raw(previewPath);
    const source = await response.text();
    if (context.isRouteCurrent?.() === false) return;

    const title = artifact.description || artifact.title_zh
      || artifact.file_name || artifact.name;
    context.setHeading(title, context.t("运行输入详情"));
    context.updateActiveTab?.({title});
    context.toolbar.append(context.button("⇩", () => FTJobArtifacts.saveBlob(
      context, path, artifact.file_name || artifact.name,
    ), context.t("下载运行输入")));

    const root = document.createElement("div");
    root.className = "job-input-detail detail-stack";
    root.append(metadata(context, artifact, jobID, loaded.resolvedPort || port));
    try {
      root.append(await semanticPreview(
        context, artifact, source, loaded.taskDetail, loaded.portQuery,
      ));
    } catch (error) {
      root.append(message(context.t("无法解析输入语义"), error.message));
    }
    root.append(sourcePreview(context, artifact, source));
    context.content.replaceChildren(root);
  }

  function artifactPath(jobID, name, portQuery, preview = false) {
    return `/api/jobs/${encodeURIComponent(jobID)}`
      + `/artifacts/${encodeURIComponent(name)}${preview ? "/preview" : ""}${portQuery}`;
  }

  function metadata(context, artifact, jobID, port) {
    const section = document.createElement("section");
    section.className = "job-section job-input-metadata";
    const heading = document.createElement("h2");
    heading.textContent = context.t("冻结输入身份");
    const rows = [
      [context.t("任务"), jobID],
      [context.t("端口"), port],
      [context.t("输入类型"), context.t(kindLabel(artifact.artifact_kind))],
      [context.t("原文件名"), artifact.file_name || artifact.name],
      [context.t("逻辑路径"), artifact.logical_path || ""],
      [context.t("内容哈希"), artifact.content_hash || ""],
      [context.t("文件大小"), `${artifact.size_bytes || 0} B`],
    ];
    section.append(heading, FTUI.table(
      [context.t("字段"), context.t("值")], rows,
    ).shell);
    return section;
  }

  async function semanticPreview(context, artifact, source, taskDetail, portQuery) {
    const kind = String(artifact.artifact_kind || "");
    if (kind === "factor_source") {
      const factorID = String(artifact.name || "").replace(FACTOR_PREFIX, "");
      const configurations = factorConfigurations(taskDetail, factorID);
      const values = await Promise.all(
        (configurations.length ? configurations : [{}]).map(item => context.api(
          withPort("/custom-factors/api/validate", portQuery),
          {method: "POST", body: JSON.stringify({
            source_code: source, params: item.params || {},
          })},
        )),
      );
      const invalid = values.find(item => !item.valid);
      if (invalid) throw new Error(
        invalid.error || context.t("因子源码无法通过检查"),
      );
      return factorPreview(context, factorID, values);
    }
    if (kind === "strategy_source") {
      const logicalPath = String(artifact.logical_path || artifact.file_name || "");
      const strategySpec = (taskDetail.strategy_specs || []).find(item => (
        String(item.source || "").replace(/^profile:/, "") === logicalPath
      ));
      const value = await context.api(
        withPort("/api/run-inputs/strategy/inspect", portQuery),
        {method: "POST", body: JSON.stringify({
          path: logicalPath, source_code: source,
          entrypoint: strategySpec?.entrypoint || "",
          strategy_spec: strategySpec || undefined,
        })},
      );
      if (!value.valid) throw new Error(value.error || context.t("策略源码无法通过检查"));
      return strategyPreview(context, value);
    }
    if (kind === "strategy_spec") return specPreview(context, JSON.parse(source));
    return message(context.t("通用任务输入"), context.t("该输入按冻结文件展示"));
  }

  function withPort(path, portQuery) {
    if (!portQuery) return path;
    return `${path}${path.includes("?") ? "&" : "?"}${portQuery.slice(1)}`;
  }

  function factorConfigurations(taskDetail, factorID) {
    const factors = taskDetail?.configuration?.shared?.factors;
    if (!Array.isArray(factors)) return [];
    return factors.filter(item => (
      item?.transient_factor_id === factorID
      || (item?.source_kind === "transient"
        && item?.factor_family_alias === factorID)
    ));
  }

  function factorPreview(context, factorID, values) {
    const section = document.createElement("section");
    section.className = "job-section job-input-semantic";
    const heading = document.createElement("h2"); heading.textContent = context.t("因子信息");
    const first = values[0] || {};
    section.append(heading, FTUI.table(
      [context.t("字段"), context.t("值")], [
        [context.t("原类名"), first.factor_name || factorID],
        [context.t("说明"), first.desc || first.description || ""],
      ],
    ).shell);
    values.forEach(value => {
      const instance = document.createElement("div");
      instance.className = "job-input-factor-instance";
      const alias = document.createElement("h3");
      alias.textContent = value.factor_alias || factorID;
      instance.append(alias);
      if (Object.keys(value.normalized_params || {}).length) {
        const params = document.createElement("small");
        params.textContent = Object.entries(value.normalized_params)
          .map(([key, item]) => `${key}: ${item}`).join(" · ");
        instance.append(params);
      }
      if (!value.math_expr || !window.katex) {
        section.append(instance); return;
      }
      const formula = document.createElement("div");
      formula.className = "job-input-formula display-math";
      katex.render(value.math_expr, formula, {displayMode: true, throwOnError: false});
      instance.append(formula); section.append(instance);
    });
    return section;
  }

  function strategyPreview(context, value) {
    const section = document.createElement("section");
    section.className = "job-section job-input-semantic";
    const heading = document.createElement("h2"); heading.textContent = context.t("策略 Hook 信息");
    section.append(heading, FTUI.table(
      [context.t("字段"), context.t("值")], [
        [context.t("入口类"), value.entrypoint || ""],
        [context.t("回调"), (value.callbacks || []).join(", ")],
        [context.t("策略标识"), value.strategy_spec?.strategy_id || ""],
      ],
    ).shell);
    if (value.strategy_spec) section.append(FTUI.code(value.strategy_spec));
    return section;
  }

  function specPreview(context, value) {
    const section = document.createElement("section");
    section.className = "job-section job-input-semantic";
    const heading = document.createElement("h2"); heading.textContent = context.t("规范化策略配置");
    const fields = FTUI.fieldRows(value);
    if (fields.length) section.append(heading, FTUI.table(
      [context.t("字段"), context.t("值")], fields,
    ).shell);
    else section.append(heading);
    section.append(FTUI.code(value));
    return section;
  }

  function sourcePreview(context, artifact, source) {
    const section = document.createElement("section"); section.className = "job-section";
    const heading = document.createElement("h2");
    heading.textContent = artifact.artifact_kind === "strategy_spec"
      ? context.t("冻结 JSON") : context.t("冻结源码");
    const code = FTUI.code(source); code.classList.add("job-input-code");
    section.append(heading, code); return section;
  }

  function message(title, body) {
    const section = document.createElement("section"); section.className = "job-section";
    const heading = document.createElement("h2"); heading.textContent = title;
    const copy = document.createElement("p"); copy.textContent = body;
    section.append(heading, copy); return section;
  }

  function kindLabel(kind) {
    return {
      factor_source: "临时因子源码",
      strategy_source: "临时策略源码",
      strategy_spec: "运行策略配置",
    }[kind] || "任务输入";
  }

  window.FTJobInputDetail = Object.freeze({artifactPath, factorConfigurations, show});
})();
