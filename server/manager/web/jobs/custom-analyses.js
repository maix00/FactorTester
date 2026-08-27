(() => {
  const PREFIX = "custom-analysis:";

  function path(options, suffix = "") {
    const query = options.artifactQuery || "";
    return `/api/jobs/${encodeURIComponent(options.jobID)}/custom-analyses${suffix}${query}`;
  }

  function supplementalPath(options, suffix = "") {
    const query = options.artifactQuery || "";
    return `/api/jobs/${encodeURIComponent(options.jobID)}/supplementals${suffix}${query}`;
  }

  const keyFor = tabID => `${PREFIX}${tabID}`;
  const tabIDFor = key => String(key || "").startsWith(PREFIX)
    ? String(key).slice(PREFIX.length) : "";

  function create(context, options) {
    const state = {
      analyses: [], latest: new Map(), loaded: false, requestedKey: "",
    };

    function request(tabID) { state.requestedKey = keyFor(tabID); }

    async function load() {
      const [tabs, jobs] = await Promise.all([
        context.api(path(options)),
        context.api(`${supplementalPath(options)}${options.artifactQuery ? "&" : "?"}`
          + "search=custom_python_analysis&limit=100"),
      ]);
      state.analyses = tabs.analyses || [];
      state.latest.clear();
      for (const job of jobs.jobs || []) {
        const tabID = String(job.target?.tab_id || "");
        if (tabID && !state.latest.has(tabID)) state.latest.set(tabID, job);
      }
      state.loaded = true;
      return state.analyses;
    }

    function tabs(callbacks = {}) {
      const values = [
        ...state.analyses.map(item => ({
          key: keyFor(item.tab_id), label: item.title, renamable: true,
          onRename: title => rename(item.tab_id, title),
          closable: true,
          onClose: async () => {
            if (!confirm(context.t(
              "确定删除此分析 Tab、全部代码快照和结果生成物吗？",
            ))) return;
            await remove(item);
            callbacks.onDeleted?.(item.tab_id);
          },
        })),
      ];
      if (context.session) {
        values.push({key: `${PREFIX}new`, label: "＋ 自定义分析"});
      }
      return values;
    }

    async function add() {
      const payload = await context.api(path(options), {
        method: "POST",
        body: JSON.stringify({
          title: context.t("自定义分析"),
          source: "result = {'artifacts': artifacts.list()}",
        }),
      });
      state.analyses.push(payload.analysis);
      return payload.analysis;
    }

    async function rename(tabID, title) {
      const current = state.analyses.find(item => item.tab_id === tabID);
      if (!current) throw new Error(context.t("自定义分析不存在"));
      const payload = await context.api(path(
        options, `/${encodeURIComponent(tabID)}`,
      ), {
        method: "PATCH",
        body: JSON.stringify({title, source: current.source}),
      });
      Object.assign(current, payload.analysis);
      return current;
    }

    async function save(analysis, title, source) {
      const payload = await context.api(path(
        options, `/${encodeURIComponent(analysis.tab_id)}`,
      ), {
        method: "PATCH", body: JSON.stringify({title, source}),
      });
      Object.assign(analysis, payload.analysis);
      return analysis;
    }

    async function remove(analysis) {
      await context.api(path(options, `/${encodeURIComponent(analysis.tab_id)}`), {
        method: "DELETE",
      });
      state.analyses = state.analyses.filter(item => item.tab_id !== analysis.tab_id);
      state.latest.delete(analysis.tab_id);
    }

    async function wait(job, status) {
      let current = job;
      for (;;) {
        status.replaceChildren(FTJobListFormat.statusPill(current.status, context));
        if (["succeeded", "failed", "cancelled"].includes(current.status)) return current;
        await new Promise(resolve => setTimeout(resolve, 500));
        const payload = await context.api(supplementalPath(
          options, `/${encodeURIComponent(current.job_id)}`,
        ));
        current = {...payload.job, result_summary: payload.result_summary, error: payload.error};
      }
    }

    async function loadResult(job, output) {
      const name = String(job?.result_summary?.artifact_name || "");
      if (!name) {
        output.replaceChildren(FTUI.empty(
          context.t("暂无分析结果"), context.t("该补充任务尚未生成可展示的结果"),
        ));
        return;
      }
      try {
        const response = await FTJobArtifacts.fetch(
          context,
          `/api/jobs/${encodeURIComponent(options.jobID)}/artifacts/`
            + `${encodeURIComponent(name)}${options.artifactQuery || ""}`,
        );
        const payload = JSON.parse(await response.text());
        output.replaceChildren(FTUI.code(payload.result ?? payload));
      } catch (error) {
        output.replaceChildren(FTUI.empty(
          context.t("分析结果不可用"), error.message || String(error),
        ));
      }
    }

    function render(tabID, target, callbacks = {}) {
      const analysis = state.analyses.find(item => item.tab_id === tabID);
      if (!analysis) {
        target.replaceChildren(FTUI.empty(
          context.t("提交物已删除，无法恢复"),
          context.t("补充任务历史仍保留，但对应的自定义分析 Tab 与代码快照已被删除"),
        ));
        return;
      }
      const root = document.createElement("section");
      root.className = "custom-analysis-editor";
      const toolbar = document.createElement("div");
      toolbar.className = "custom-analysis-toolbar";
      const title = document.createElement("input");
      title.value = analysis.title;
      title.setAttribute("aria-label", context.t("分析名称"));
      const saveButton = FTUI.actionButton(context.t("保存"), async () => {
        saveButton.disabled = true;
        try {
          await save(analysis, title.value, source.value);
          callbacks.onTabsChanged?.(keyFor(analysis.tab_id));
        } catch (error) { context.showNotice?.(error.message || String(error), true); }
        finally { saveButton.disabled = false; }
      }, {variant: "secondary"});
      const prior = state.latest.get(analysis.tab_id);
      const runButton = FTUI.actionButton(
        context.t(prior ? "重新运行" : "运行"), async () => {
        runButton.disabled = true;
        try {
          await save(analysis, title.value, source.value);
          callbacks.onTabsChanged?.(keyFor(analysis.tab_id));
          const created = await context.api(supplementalPath(options), {
            method: "POST",
            body: JSON.stringify({
              kind: "custom_python_analysis",
              params: {tab_id: analysis.tab_id},
            }),
          });
          if (created.artifact) {
            await loadResult({result_summary: {artifact_name: created.artifact.name}}, output);
          } else {
            const completed = await wait(created.job, status);
            state.latest.set(analysis.tab_id, completed);
            if (completed.status === "succeeded") await loadResult(completed, output);
            else throw new Error(completed.error?.message || context.t("自定义分析失败"));
          }
        } catch (error) { output.replaceChildren(FTUI.empty(
          context.t("自定义分析失败"), error.message || String(error),
        )); }
        finally { runButton.disabled = false; }
        }, {variant: "primary"},
      );
      const status = document.createElement("div"); status.className = "custom-analysis-status";
      toolbar.append(title, saveButton, runButton, status);
      const workspace = document.createElement("div");
      workspace.className = "custom-analysis-workspace";
      const editor = document.createElement("div"); editor.className = "custom-analysis-source";
      const source = document.createElement("textarea"); source.value = analysis.source || "";
      source.spellcheck = false; source.setAttribute("aria-label", context.t("Python 分析代码"));
      context.pageState?.register?.(`custom-analysis:${tabID}`, {
        capture: () => ({title: title.value, source: source.value}),
        restore: value => {
          title.value = value?.title ?? title.value;
          source.value = value?.source ?? source.value;
        },
      });
      FTCustomAnalysisAssistance.register(context, {tabID, title, source});
      editor.append(source);
      const output = document.createElement("div"); output.className = "custom-analysis-output";
      output.append(FTUI.empty(context.t("结构化输出"), context.t("运行后在这里显示结果")));
      if (context.session && analysis.source != null) {
        workspace.append(editor, output); root.append(toolbar, workspace);
      } else {
        workspace.append(output); root.replaceChildren(workspace);
      }
      target.replaceChildren(root);
      const latest = state.latest.get(tabID);
      if (latest) {
        status.append(FTJobListFormat.statusPill(latest.status, context));
        if (["queued", "planning", "running", "paused"].includes(latest.status)) {
          runButton.disabled = true;
        }
        if (latest.status === "succeeded" && latest.recoverable !== false) {
          context.api(supplementalPath(options, `/${encodeURIComponent(latest.job_id)}`))
            .then(payload => loadResult({...latest, result_summary: payload.result_summary}, output))
            .catch(() => {});
        }
      }
    }

    return Object.freeze({
      add, keyFor, load, render, request, state, tabIDFor, tabs,
    });
  }

  window.FTJobCustomAnalyses = Object.freeze({create, keyFor, tabIDFor});
})();
