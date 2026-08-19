(() => {
  const model = () => window.FTTestRunBatchModel;

  function usesLocalRuntime(state) {
    return String(state.runValues?.execution_target || "server") === "local";
  }

  async function localRequest(action, request) {
    const handler = window.webkit?.messageHandlers?.factorTesterLocalRun;
    if (!handler?.postMessage) {
      throw new Error("本地运行仅能从 Swift 客户端发起");
    }
    const value = await handler.postMessage({action, request});
    if (!value || value.success === false) {
      throw new Error(value?.error || "Swift 本地运行没有返回有效结果");
    }
    return value;
  }

  async function runRequest(context, state) {
    // Report/reference code and uploaded-source serializers are only needed
    // once an explicit preview/run action starts.  Rendering the batch matrix
    // must not pull this execution graph into the page.
    await window.FTStaticLoader?.loadGroups?.(["research"]);
    await window.FTTests?.ensureFactorsForExecution?.(context, state);
    await window.FTTests?.ensureProductsForExecution?.(context, state);
    const factorSets = window.FTTestFactorSets;
    const descriptors = factorSets?.selections?.(state)?.length
      ? await factorSets.descriptors(
        context, state, FTTestConfiguration.executionFactors(state),
      )
      : [];
    return {
      workspace_id: state.workspace.workspace_id,
      configuration_revision: state.workspace.configuration?.revision,
      analyses: [state.kind],
      ...FTTestRunFields.requestBody(state),
      ...FTTestInputState.requestBody(state),
      ...(descriptors.length ? {factor_subject_descriptors: descriptors} : {}),
    };
  }

  function previewName(state, group) {
    const raw = `${state?.kind || "test"}-${group?.id || "task"}`
      .replace(/[^a-zA-Z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 72) || "task";
    const random = Math.random().toString(36).slice(2, 10);
    return `run-preview-${raw}-${Date.now()}-${random}`;
  }

  async function createConfigurationSnapshot(context, state, group, configuration) {
    const workspaceID = String(state.workspace?.workspace_id || "");
    const configurationID = String(configuration?.configuration_id || "");
    const revision = Number(configuration?.revision);
    if (!workspaceID || !configurationID || !Number.isInteger(revision)) {
      throw new Error("无法为运行配置创建不可变快照");
    }
    const value = await context.api(
      `/api/workspaces/${encodeURIComponent(workspaceID)}/configuration-snapshots`,
      {
        method: "POST",
        body: JSON.stringify({
          source_workspace_id: workspaceID,
          source_configuration_id: configurationID,
          source_configuration_revision: revision,
          name: previewName(state, group),
        }),
      },
    );
    const snapshot = value?.snapshot || value;
    if (!snapshot?.snapshot_id || !Number.isInteger(Number(snapshot.snapshot_revision))) {
      throw new Error("运行配置快照响应不完整");
    }
    return {
      configuration_snapshot_id: String(snapshot.snapshot_id),
      configuration_snapshot_revision: Number(snapshot.snapshot_revision),
    };
  }

  async function requestForPreview(context, state, group) {
    const configuration = await FTTestConfiguration.save(context, state, group);
    const request = {
      ...await runRequest(context, state),
      configuration_revision: configuration.revision,
    };
    if (usesLocalRuntime(state)) return request;
    const snapshot = await createConfigurationSnapshot(
      context, state, group, configuration,
    );
    delete request.configuration_revision;
    return {...request, ...snapshot};
  }

  async function previewOne(context, state, group, refresh) {
    const item = model().itemFor(state, group);
    model().update(item, "freezing", refresh);
    try {
      await window.FTStaticLoader?.loadGroups?.(["workbench-factors", "workbench-products"]);
      await window.FTTests?.ensureProductsForExecution?.(context, state);
      await window.FTTests?.ensureRunSubmitCode?.(context, state);
      const request = await requestForPreview(context, state, group);
      const value = usesLocalRuntime(state)
        ? await localRequest("preview", request)
        : await context.api(context.servicePath("/api/runs/preview"), {
          method: "POST", body: JSON.stringify(request),
        });
      model().recordPreview(
        item, value, request, model().inputFingerprint(state, group),
      );
      refresh?.();
      return true;
    } catch (error) {
      item.phase = "failed";
      item.error = error.message || String(error);
      refresh?.();
      return false;
    }
  }

  async function runOne(context, state, group, refresh) {
    const item = model().itemFor(state, group);
    state.activeRunGroupID = item.groupID;
    const reusePreview = model().previewMatches(item, state, group);
    if (!reusePreview) model().invalidatePreview(item);
    model().update(item, "submitting", refresh);
    try {
      await window.FTStaticLoader?.loadGroups?.(["workbench-factors", "workbench-products"]);
      await window.FTTests?.ensureProductsForExecution?.(context, state);
      await window.FTTests?.ensureRunSubmitCode?.(context, state);
      const request = reusePreview
        ? model().clone(item.previewRequest)
        : {
          ...await runRequest(context, state),
          configuration_revision: (
            await FTTestConfiguration.save(context, state, group)
          ).revision,
        };
      const value = usesLocalRuntime(state)
        ? await localRequest("run", request)
        : await context.api(context.servicePath("/api/runs"), {
          method: "POST", body: JSON.stringify(request),
        });
      if (usesLocalRuntime(state)) {
        model().recordLocalSubmission(item, value);
      } else {
        model().recordSubmission(item, value);
      }
      refresh?.();
      return true;
    } catch (error) {
      item.phase = "failed";
      item.error = error.message || String(error);
      refresh?.();
      return false;
    }
  }

  async function previewAll(context, state, refresh) {
    for (const group of model().taskGroups(state)) {
      await previewOne(context, state, group, refresh);
    }
    return model().synchronize(state);
  }

  async function runAll(context, state, refresh) {
    for (const group of model().taskGroups(state)) {
      await runOne(context, state, group, refresh);
    }
    return model().synchronize(state);
  }

  window.FTTestRunBatchActions = Object.freeze({previewAll, previewOne, runAll, runOne});
})();
