(() => {
  const model = () => window.FTTestRunBatchModel;

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

  async function previewOne(context, state, group, refresh) {
    const item = model().itemFor(state, group);
    model().update(item, "freezing", refresh);
    try {
      await window.FTStaticLoader?.loadGroups?.(["workbench-factors", "workbench-products"]);
      await window.FTTests?.ensureProductsForExecution?.(context, state);
      await window.FTTests?.ensureRunSubmitCode?.(context, state);
      const configuration = await FTTestConfiguration.save(context, state, group);
      const value = await context.api(context.servicePath("/api/runs/preview"), {
        method: "POST",
        body: JSON.stringify({
          ...await runRequest(context, state),
          configuration_revision: configuration.revision,
        }),
      });
      model().recordPreview(item, value);
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
    model().update(item, "submitting", refresh);
    try {
      await window.FTStaticLoader?.loadGroups?.(["workbench-factors", "workbench-products"]);
      await window.FTTests?.ensureProductsForExecution?.(context, state);
      await window.FTTests?.ensureRunSubmitCode?.(context, state);
      const configuration = await FTTestConfiguration.save(context, state, group);
      const value = await context.api(context.servicePath("/api/runs"), {
        method: "POST",
        body: JSON.stringify({
          ...await runRequest(context, state),
          configuration_revision: configuration.revision,
        }),
      });
      model().recordSubmission(item, value);
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
    for (const group of FTTestProducts.selectedGroups(state)) {
      await previewOne(context, state, group, refresh);
    }
    return model().synchronize(state);
  }

  async function runAll(context, state, refresh) {
    for (const group of FTTestProducts.selectedGroups(state)) {
      await runOne(context, state, group, refresh);
    }
    return model().synchronize(state);
  }

  window.FTTestRunBatchActions = Object.freeze({previewAll, previewOne, runAll, runOne});
})();
