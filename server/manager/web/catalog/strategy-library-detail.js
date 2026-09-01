(() => {
  async function render(context, strategyRef = "", mode = "view", route = {}) {
    const creating = mode === "create" || !strategyRef;
    context.activeNav("strategies");
    context.setHeading(creating ? context.t("新建策略") : context.t("策略详情"), context.t("策略库"));
    context.content.replaceChildren(FTUI.loading(context.t("正在读取策略…")));
    let value = {};
    if (!creating) {
      const response = await FTStrategyLibraryRuntime.get(context, strategyRef);
      value = response.strategy || response;
    }
    if (context.isRouteCurrent?.() === false) return;
    if (mode === "view" && !creating) return renderView(context, value);
    return renderEditor(context, value, creating ? "create" : "edit", route);
  }

  function renderView(context, strategy) {
    const revision = strategy.current_revision || {};
    context.setHeading(strategy.name || context.t("策略详情"), context.t("策略库"));
    context.updateActiveTab?.({title: strategy.name || context.t("策略详情")});
    if (strategy.access?.can_edit) context.toolbar.append(FTUI.actionButton(
      context.t("编辑"), () => context.navigate(
        `/strategies/${encodeURIComponent(strategy.strategy_ref)}?mode=edit`,
      ), {variant: "secondary"},
    ));
    if (strategy.access?.can_share) context.toolbar.append(FTUI.iconButton(
      context, "person.2", "共享", () => share(context, strategy),
      {className: "strategy-library-toolbar-action"},
    ));
    if (strategy.access?.can_delete) context.toolbar.append(FTUI.iconButton(
      context, "trash", "删除", () => remove(context, strategy),
      {className: "strategy-library-toolbar-action danger-action"},
    ));
    const root = document.createElement("section");
    root.className = "strategy-library-detail strategy-library-page";
    const tabs = FTObjectDetailTabs.create(context, {
      objectKind: "strategy", mode: "view",
      stateKey: `strategy-detail-tabs:${strategy.strategy_ref}`,
      panels: {
        overview: details(context, strategy, revision),
        source: FTUI.code(revision.source_code || "", {language: "python", className: "strategy-source-viewer"}),
        revisions: revisions(context, strategy.revisions || []),
      },
      overrides: {hooks: {hidden: true}},
    });
    root.append(tabs.root);
    context.content.replaceChildren(root);
  }

  function details(context, strategy, revision) {
    return FTUI.table([context.t("字段"), context.t("值")], [
      [context.t("策略引用"), strategy.strategy_ref],
      [context.t("所有者"), strategy.owner_ref],
      [context.t("说明"), strategy.description || "—"],
      [context.t("入口类"), revision.entrypoint || "—"],
      [context.t("可见性"), visibility(context, strategy.visibility)],
      [context.t("源码哈希"), revision.source_sha256 || "—"],
      [context.t("Hooks"), hookTable(context, revision.hooks || [])],
      [context.t("更新时间"), FTUI.formatDate(strategy.updated_at)],
    ]).shell;
  }

  function hookTable(context, values) {
    const rows = (Array.isArray(values) ? values : []).map(item => {
      const body = FTUI.code(item.source || "", {language: "python"});
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${item.name || "Hook"} · ${item.lineno || "—"}-${item.end_lineno || "—"}`;
      details.append(summary, body);
      return [item.name || "—", `${item.lineno || "—"}-${item.end_lineno || "—"}`, details];
    });
    return rows.length ? FTUI.table(
      [context.t("Hook"), context.t("行号"), context.t("源码")], rows,
    ).shell : context.t("暂无 Hook");
  }

  function revisions(context, values) {
    return values.length ? FTUI.pagedTable([
      context.t("版本"), context.t("入口类"), context.t("源码哈希"), context.t("创建时间"),
    ], values.map(item => [
      `r${item.revision_number || "—"}`, item.entrypoint || "—",
      item.source_sha256 || "—", FTUI.formatDate(item.created_at),
    ]), {pageSize: 10}).shell : FTUI.empty(
      context.t("暂无历史版本"), context.t("当前策略只有一个版本"),
    );
  }

  function renderEditor(context, value, mode, route) {
    context.setHeading(mode === "create" ? context.t("新建策略") : context.t("编辑策略"), context.t("策略库"));
    const editor = FTStrategyLibraryEditor.create(context, value, {mode, storageMode: "library"});
    const save = FTUI.actionButton(
      context.t(mode === "create" ? "提交" : "保存"),
      () => editor.form.requestSubmit(), {variant: "primary"},
    );
    context.toolbar.append(save);
    if (mode === "edit") context.toolbar.append(FTUI.actionButton(
      context.t("取消"), () => context.navigate(
        `/strategies/${encodeURIComponent(value.strategy_ref)}`,
      ), {variant: "secondary"},
    ));
    context.content.replaceChildren(editor.form);
    FTStrategyLibraryAssistance.register(context, editor, {
      mode, boundProfileID: route?.researchProfileID || "",
    });
    editor.form.addEventListener("submit", async event => {
      event.preventDefault();
      save.disabled = true;
      try {
        const payload = {
          name: editor.state.name,
          description: editor.state.description,
          entrypoint: editor.state.entrypoint,
          source_code: editor.state.source_code,
          visibility: editor.state.visibility,
          requirements: editor.state.requirements,
        };
        const response = mode === "create"
          ? await FTStrategyLibraryRuntime.create(context, payload)
          : await FTStrategyLibraryRuntime.update(context, value.strategy_ref, payload);
        const saved = response.strategy || response;
        const path = `/strategies/${encodeURIComponent(saved.strategy_ref)}`;
        if (mode === "create") {
          context.closeTab?.(context.tabID);
        }
        context.navigate(path);
      } catch (error) {
        editor.status.textContent = error.message || context.t("保存失败");
        save.disabled = false;
      }
    }, {once: false});
  }

  function visibility(context, value) {
    return context.t({private: "仅自己", shared: "指定共享", public: "公开"}[value] || value || "—");
  }

  async function share(context, strategy) {
    const target = window.prompt(context.t("请输入共享用户标识"));
    if (!target?.trim()) return;
    try {
      await FTStrategyLibraryRuntime.grant(context, strategy.strategy_ref, target.trim());
      context.showNotice?.(context.t("已共享策略"));
    } catch (error) {
      context.showNotice?.(error.message || context.t("共享失败"), true);
    }
  }

  async function remove(context, strategy) {
    if (!window.confirm(context.t("确认归档该策略？"))) return;
    try {
      await FTStrategyLibraryRuntime.remove(context, strategy.strategy_ref);
      context.closeTab?.(context.tabID);
      context.navigate("/strategies?scope=mine");
    } catch (error) {
      context.showNotice?.(error.message || context.t("删除失败"), true);
    }
  }

  window.FTStrategyLibraryDetail = Object.freeze({render});
})();
