(() => {
  const graphID = "factor-research";
  const pageSize = 20;
  const sourceDefinitions = [
    {value: "mine", label: "本人"},
    {value: "subordinates", label: "下级用户"},
    {value: "server", label: "服务器提供"},
  ];

  function current(context) {
    return context.isRouteCurrent?.() !== false;
  }

  function path(value) {
    return `/api/catalog/research-graphs${value}`;
  }

  function locale() {
    return String(document.documentElement.lang || "zh-Hans").toLowerCase().startsWith("en")
      ? "en" : "zh-Hans";
  }

  function graphRow(graph, active, context) {
    return {
      ...graph,
      rowID: `server:${graph.graph_id}@v${graph.version}`,
      source: "server",
      sourceLabel: "服务器提供",
      title: graph.presentation?.title || graph.graph_id,
      owner: context.t("服务器"),
      status: graph.lifecycle || (graph.version === active?.version ? "active" : "released"),
      href: `/research-graphs/${encodeURIComponent(`server:${graph.graph_id}@v${graph.version}`)}`,
      downloadURL: path(`/${encodeURIComponent(graph.graph_id)}/versions/${graph.version}/yaml?locale=${encodeURIComponent(locale())}`),
    };
  }

  function userRow(file, source, context) {
    const owner = String(file.owner_ref || context.session?.username || "");
    return {
      ...file,
      rowID: `${source}:${owner}:${file.graph_file_id}`,
      source,
      sourceLabel: source === "subordinates" ? "下级用户" : "本人",
      title: file.name || file.filename || context.t("未命名研究图"),
      owner: file.owner_alias ? `${file.owner_alias}（${owner}）` : owner,
      status: file.is_default ? "default" : "saved",
      href: `/research-graphs/${encodeURIComponent(`user:${owner}:${file.graph_file_id}`)}`,
      downloadURL: `${path(`/user-library/${encodeURIComponent(file.graph_file_id)}`)}?download=1&owner=${encodeURIComponent(owner)}`,
    };
  }

  async function loadData(context) {
    const localeQuery = `?locale=${encodeURIComponent(locale())}`;
    const [versionsResult, activeResult, mineResult, subordinateResult] = await Promise.allSettled([
      context.api(path(`/${graphID}/versions${localeQuery}`)),
      context.api(path(`/${graphID}/active${localeQuery}`)),
      context.api(path("/user-library")),
      context.session ? context.api(path("/user-library/subordinates")) : Promise.reject(new Error("login required")),
    ]);
    if (versionsResult.status !== "fulfilled") throw versionsResult.reason;
    const active = activeResult.status === "fulfilled" ? activeResult.value.graph : null;
    const rows = [];
    (versionsResult.value.versions || []).forEach(item => rows.push(graphRow(item, active, context)));
    if (mineResult.status === "fulfilled") {
      (mineResult.value.files || []).forEach(item => rows.push(userRow(item, "mine", context)));
    }
    if (subordinateResult.status === "fulfilled") {
      (subordinateResult.value.files || []).forEach(item => rows.push(userRow(item, "subordinates", context)));
    }
    return {
      rows,
      active,
      defaultGraph: mineResult.status === "fulfilled" ? mineResult.value.default : null,
    };
  }

  function sourceFilter(context, state, rows, renderTable) {
    // Keep the source vocabulary stable for authenticated users even when a
    // source currently has no rows.  Hiding an option based on the current
    // result set makes the filter appear to change meaning as uploads or
    // subordinate data arrive.  Visitors only get the server-owned source.
    const available = context.session
      ? sourceDefinitions
      : sourceDefinitions.filter(item => item.value === "server");
    const selected = state.sources?.length
      ? state.sources.filter(value => available.some(item => item.value === value))
      : available.map(item => item.value);
    if (!selected.length && available.length) selected.push(available[0].value);
    state.sources = selected;
    return FTMultiSelectFilter.create(context, {
      title: context.t("来源"),
      compact: true,
      className: "research-graph-source-filter",
      items: available,
      selected,
      onApply: values => {
        state.sources = values;
        renderTable();
      },
    }).element;
  }

  function rowActions(context, row, refresh) {
    const actions = document.createElement("span");
    actions.className = "research-graph-row-actions";
    const download = document.createElement("a");
    download.className = "icon-action-button";
    download.href = row.downloadURL;
    download.download = row.filename || `${row.graph_id || "research-graph"}.yaml`;
    download.title = context.t("下载 YAML");
    download.setAttribute("aria-label", download.title);
    download.append(window.FTIcons.node("arrow.down.circle"));
    download.addEventListener("click", event => event.stopPropagation());
    actions.append(download);
    if (row.source === "mine") {
      if (!row.is_default) {
        const makeDefault = FTUI.iconButton(context, "checkmark.circle", "设为默认", async event => {
          event.stopPropagation();
          try {
            await context.api(path("/user-library/default"), {
              method: "POST",
              body: JSON.stringify({kind: "user", graph_file_id: row.graph_file_id}),
            });
            await refresh();
          } catch (error) {
            context.showNotice(error.message || String(error), true);
          }
        });

        actions.append(makeDefault);
      }
      const remove = FTUI.iconButton(context, "trash", "删除研究图", async event => {
        event.stopPropagation();
        if (!window.confirm(context.t("确定删除这个研究图吗？"))) return;
        try {
          await context.api(path(`/user-library/${encodeURIComponent(row.graph_file_id)}`), {method: "DELETE"});
          await refresh();
        } catch (error) {
          context.showNotice(error.message || String(error), true);
        }
      });

      actions.append(remove);
    }
    return actions;
  }

  function table(context, state, rows, refresh) {
    const filtered = rows.filter(row => state.sources.includes(row.source));
    const values = filtered.map(row => [
      row.title,
      row.version ? `v${row.version}` : "—",
      context.t(row.sourceLabel),
      row.owner || "—",
      context.t(row.status || "saved"),
      FTUI.formatDate(row.updated_at || row.created_at),
      rowActions(context, row, refresh),
    ]);
    const view = FTUI.pagedTable(
      [context.t("研究图"), context.t("版本"), context.t("来源"), context.t("所有者"), context.t("状态"), context.t("更新时间"), context.t("操作")],
      values,
      {
        page: state.page || 1,
        pageSize,
        totalLabel: total => context.t("共 %lld 个").replace("%lld", String(total)),
        onPageChange: page => { state.page = page; refresh(false); },
      },
    );
    const pageRows = filtered.slice(view.start, view.start + view.pageSize);
    [...view.body.rows].forEach((row, index) => {
      row.dataset.href = "true";
      row.addEventListener("click", () => context.navigate(pageRows[index].href));
    });
    view.shell.classList.add("research-graph-table");
    return view.shell;
  }

  async function upload(context, input, refresh) {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const yaml = await file.text();
      await context.api(path("/user-library"), {
        method: "POST",
        body: JSON.stringify({filename: file.name, yaml}),
      });
      context.showNotice(context.t("研究图已上传"));
      await refresh();
    } catch (error) {
      context.showNotice(error.message || String(error), true);
    } finally {
      input.value = "";
    }
  }

  async function render(context, mount) {
    if (!current(context)) return;
    const state = context.tabSession.researchGraphs || {sources: [], page: 1};
    state.sources ||= [];
    state.page ||= 1;
    context.tabSession.researchGraphs = state;
    context.pageState?.register?.("research-graph-list", {
      capture: () => ({sources: state.sources, page: state.page}),
      restore: value => {
        if (Array.isArray(value?.sources)) state.sources = value.sources;
        if (Number(value?.page) > 0) state.page = Number(value.page);
      },
      describe: () => ({page: "research-graphs", section: "list", fields: []}),
    });
    mount.replaceChildren(FTUI.loading(context.t("正在读取研究图…")));
    const data = await loadData(context);
    if (!current(context)) return;
    const root = document.createElement("section");
    root.className = "research-graph-list-page";
    const header = document.createElement("div");
    header.className = "research-graph-list-header";
    const title = document.createElement("div");
    const heading = document.createElement("h2");
    heading.textContent = context.t("研究图");
    const note = document.createElement("p");
    note.className = "secondary research-graph-list-note";
    note.textContent = context.t("服务器版本与用户上传的 YAML 统一列出；点击行进入研究图详情");
    title.append(heading, note);
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".yaml,.yml,application/yaml,text/yaml";
    input.hidden = true;
    const uploadButton = context.button(context.t("上传 YAML"), () => input.click(), context.t("上传个人研究图 YAML"));
    uploadButton.className = "primary";
    input.addEventListener("change", () => void upload(context, input, refresh));
    header.append(title, uploadButton, input);
    root.append(header);
    const filterHost = document.createElement("div");
    filterHost.className = "research-graph-filters";
    root.append(filterHost);
    const tableHost = document.createElement("div");
    root.append(tableHost);
    mount.replaceChildren(root);

    function renderTable(reload = false) {
      if (reload) {
        state.page = 1;
        void refresh();
        return;
      }
      filterHost.replaceChildren(sourceFilter(context, state, data.rows, () => renderTable(false)));
      tableHost.replaceChildren(table(context, state, data.rows, () => refresh(false)));
    }
    async function refresh(reload = true) {
      if (reload) {
        await render(context, mount);
      } else if (current(context)) {
        renderTable(false);
      }
    }
    renderTable(false);
  }

  async function detail(context, mount, ref) {
    const value = decodeURIComponent(String(ref || ""));
    const localeQuery = `?locale=${encodeURIComponent(locale())}`;
    if (value.startsWith("server:")) {
      const match = /^server:([^@]+)@v(\d+)$/.exec(value);
      if (!match) throw new Error(context.t("研究图引用无效"));
      const result = await context.api(path(`/${encodeURIComponent(match[1])}/versions${localeQuery}`));
      const graph = (result.versions || []).find(item => item.version === Number(match[2]));
      if (!graph) throw new Error(context.t("研究图版本不存在"));
      FTResearchGraph.renderGraph(context, mount, graph, {
        downloadURL: path(`/${encodeURIComponent(match[1])}/versions/${match[2]}/yaml${localeQuery}`),
      });
      return;
    }
    if (value.startsWith("user:")) {
      const parts = value.split(":");
      const owner = parts[1];
      const fileID = parts.slice(2).join(":");
      const result = await context.api(
        `${path(`/user-library/${encodeURIComponent(fileID)}`)}?view=1&owner=${encodeURIComponent(owner)}`,
      );
      const file = result.file;
      if (!file?.graph) throw new Error(context.t("个人研究图内容不可用"));
      FTResearchGraph.renderGraph(context, mount, file.graph, {
        title: file.name || file.filename,
        downloadURL: `${path(`/user-library/${encodeURIComponent(fileID)}`)}?download=1&owner=${encodeURIComponent(owner)}`,
        userFile: true,
      });
      return;
    }
    throw new Error(context.t("研究图引用无效"));
  }

  window.FTResearchGraphList = Object.freeze({render, detail});
})();
