(() => {
  function selectedExecutionGroup(context, state) {
    if (state.kind === "ic") {
      const groups = window.FTICConfigurationGroupModel?.selected?.(state) || [];
      if (groups.length !== 1) {
        throw new Error(context.t("IC 只能选择一个配置组"));
      }
      return groups[0];
    }
    const groups = window.FTTestProducts?.selectedGroups?.(state) || [];
    if (!groups.length) throw new Error(context.t("请选择产品组"));
    const requested = [state.groupRef];
    if (groups.length !== requested.filter(Boolean).length) {
      throw new Error(context.t("所选产品组已不可用，请重新选择"));
    }
    return groups[0];
  }

  function create(context, state, options = {}) {
    const render = options.render || (() => {});
    const ensureRunCode = options.ensureRunCode || (() => Promise.resolve());
    const ensureRunSubmitCode = options.ensureRunSubmitCode
      || (() => Promise.resolve());

    async function save() {
      const name = prompt(context.t("模板名称"));
      if (!name?.trim()) return;
      await ensureRunCode();
      await ensureRunSubmitCode();
      await FTTestLazyCode.loadGroup("workbench-factors");
      await FTTestLazyCode.loadGroup("workbench-products");
      const group = selectedExecutionGroup(context, state);
      await window.FTTestConfiguration.save(context, state, group);
      const value = await context.api(
        `/api/workspaces/${encodeURIComponent(state.workspace.workspace_id)}/configuration/templates`,
        {method: "POST", body: JSON.stringify({name: name.trim()})},
      );
      state.templates.unshift(value.template);
      render();
    }

    async function load(template) {
      await ensureRunCode();
      await ensureRunSubmitCode();
      await FTTestLazyCode.loadGroup("workbench-factors");
      await FTTestLazyCode.loadGroup("workbench-products");
      if (!state.workspace) {
        state.factorRef = template.payload?.shared?.factors?.[0]?.ref || state.factorRef;
        await window.FTTestConfiguration.ensureWorkspace(context, state);
      }
      const value = await context.api(
        `/api/workspaces/${encodeURIComponent(state.workspace.workspace_id)}/configuration/load-template`,
        {
          method: "POST",
          body: JSON.stringify({
            configuration_id: template.configuration_id,
            expected_revision: state.workspace.configuration.revision,
          }),
        },
      );
      state.workspace.configuration = value.configuration;
      const listed = state.workspaces.findIndex(item => (
        item.workspace_id === state.workspace.workspace_id
      ));
      if (listed >= 0) state.workspaces[listed] = state.workspace;
      FTTestState.applyWorkspaceConfiguration(state);
      state.settingsMountedTabs = FTTestSettings.initialMountedTabs(
        state.manifest, FTTestState.savedMountedTabs(state),
      );
      state.settingsExplicitMountedTabs = [
        ...(state.workspace?.configuration?.payload?.ui?.[state.kind]
          ?.explicit_mounted_tabs || []),
      ];
      state.values = FTTestSettings.initialValues(
        state.manifest, FTTestState.savedSettings(state), state.settingsMountedTabs,
      );
      FTTestState.restoreTemporaryObjects?.(state);
      state.settingsTabKey = null;
      state.lazy = FTTestState.lazyState();
      state.lazy.templates.status = "ready";
      FTTestState.seedSavedCatalogs(state);
      state.factorCatalog = null;
      FTTestFactors.prepare(state);
      FTTestProducts.synchronize(state);
      render();
    }

    async function overwrite(template) {
      if (!confirm(`${context.t("用当前设置覆盖模板")}「${template.name}」？`)) return;
      try {
        await ensureRunCode();
        await ensureRunSubmitCode();
        await FTTestLazyCode.loadGroup("workbench-factors");
        await FTTestLazyCode.loadGroup("workbench-products");
        const group = selectedExecutionGroup(context, state);
        await window.FTTestConfiguration.save(context, state, group);
        const value = await context.api(
          `/api/configuration-templates/${encodeURIComponent(template.configuration_id)}`,
          {
            method: "PUT",
            body: JSON.stringify({workspace_id: state.workspace.workspace_id}),
          },
        );
        const index = state.templates.findIndex(item => (
          item.configuration_id === template.configuration_id
        ));
        if (index >= 0) state.templates[index] = value.template;
        render();
      } catch (error) {
        alert(error.message);
      }
    }

    async function remove(template) {
      if (!confirm(`${context.t("确定删除模板")}「${template.name}」？`)) return;
      try {
        await context.api(
          `/api/configuration-templates/${encodeURIComponent(template.configuration_id)}`,
          {method: "DELETE"},
        );
        state.templates = state.templates.filter(item => (
          item.configuration_id !== template.configuration_id
        ));
        render();
      } catch (error) {
        alert(error.message);
      }
    }

    return Object.freeze({save, load, overwrite, delete: remove});
  }

  window.FTTestTemplateActions = Object.freeze({create});
})();
