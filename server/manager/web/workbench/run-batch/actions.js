(() => {
  const model = () => window.FTTestRunBatchModel;

  function usesLocalRuntime(state) {
    return String(state.runValues?.execution_target || "server") === "local";
  }

  function serviceRunPath(context, state, path) {
    const requestedPort = String(state.runValues?.service_port || "").trim();
    if (!requestedPort) return context.servicePath(path);
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}port=${encodeURIComponent(requestedPort)}`;
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

  async function submitServerRun(context, state, request) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      return await context.api(serviceRunPath(context, state, "/api/runs"), {
        method: "POST", body: JSON.stringify(request), signal: controller.signal,
      });
    } catch (error) {
      if (controller.signal.aborted) {
        throw new Error("任务提交响应超时；请检查任务列表确认服务端是否已接收");
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function runRequest(context, state) {
    // Report/reference code and uploaded-source serializers are only needed
    // once an explicit preview/run action starts.  Rendering the batch matrix
    // must not pull this execution graph into the page.
    await window.FTTests?.ensureFactorsForExecution?.(context, state);
    await window.FTTests?.ensureProductsForExecution?.(context, state);
    const factorSets = window.FTTestFactorSets;
    const descriptors = factorSets?.selections?.(state)?.length
      ? await factorSets.descriptors(
        context, state, window.FTTestConfiguration.executionFactors(state),
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
    if (!window.FTTestConfiguration) throw new Error("运行配置提交模块不可用");
    const configuration = await window.FTTestConfiguration.save(context, state, group);
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
      const request = await requestForPreview(context, state, group);
      // Bind the immutable request to the page inputs that produced it.  Do
      // not recompute this after the network round trip: the user may edit the
      // draft while preview generation is in flight, in which case the next
      // click must detect that this response is already stale.
      const fingerprint = model().inputFingerprint(state, group);
      const value = usesLocalRuntime(state)
        ? await localRequest("preview", request)
        : await context.api(serviceRunPath(context, state, "/api/runs/preview"), {
          method: "POST", body: JSON.stringify(request),
        });
      model().recordPreview(item, value, request, fingerprint);
      refresh?.();
      // A content refresh can replace state.testRunBatch while this async
      // preview still owns the original item. Mirror the frozen contract into
      // the current model so the persistent header enables Run and submission
      // reuses the exact request/hash shown in the overlay.
      const mirrorPreview = () => {
        const current = model().itemFor(state, group);
        if (current && current !== item) {
          model().recordPreview(current, value, request, fingerprint);
        }
        return current;
      };
      mirrorPreview();
      // The first refresh may have replaced the persistent header while the
      // item still read “freezing”. Render once more after mirroring so the
      // visible Run button reflects the frozen state, then restore the model
      // again for refresh implementations that rebuild the batch array.
      refresh?.();
      mirrorPreview();
      // Return the exact frozen record. A page refresh may rebuild
      // state.testRunBatch while this asynchronous action is still active;
      // callers must not have to rediscover this result from mutable UI state.
      return item;
    } catch (error) {
      item.phase = "failed";
      item.error = model().errorDetail(error);
      refresh?.();
      // A refresh may rebuild state.testRunBatch before the caller resumes.
      // Return the failed item itself so the exact backend diagnostic is not
      // replaced by the generic "RunSpec was not generated" fallback.
      return item;
    }
  }

  async function runOne(context, state, group, refresh) {
    let item = model().itemFor(state, group);
    state.activeRunGroupID = item.groupID;
    try {
      if (!model().previewMatches(item, state, group)) {
        model().invalidatePreview(item);
        await previewOne(context, state, group, refresh);
        item = model().itemFor(state, group);
        if (!item || !model().previewMatches(item, state, group)) return false;
      }
      model().update(item, "submitting", refresh);
      // Submission always reuses the exact immutable request that produced
      // the RunSpec shown by “查看运行配置”. This prevents a second save or a
      // late UI mutation from making the displayed and executed specs drift.
      const request = model().clone(item.previewRequest);
      const value = usesLocalRuntime(state)
        ? await localRequest("run", request)
        : await submitServerRun(context, state, request);
      const record = target => {
        if (usesLocalRuntime(state)) model().recordLocalSubmission(target, value);
        else model().recordSubmission(target, value);
        return target;
      };
      record(item);
      // The jobs page keeps a per-tab cache for pagination.  Invalidate it
      // only after a server submission is accepted so a later visit shows the
      // new Job without turning every navigation into a federation fan-out.
      if (!usesLocalRuntime(state)) window.FTJobs?.invalidate?.();
      // update(..., "submitting") repaints the workbench before the request
      // resolves. synchronize() deliberately clones batch entries, so the
      // item captured above may no longer be the object rendered by the page.
      // Publish the durable Job identity into the current model before and
      // after repainting; otherwise the API succeeds but no Job link,
      // progress, or result panel can ever appear.
      const mirrorSubmission = () => {
        const current = model().itemFor(state, group);
        if (current && current !== item) record(current);
        return current;
      };
      mirrorSubmission();
      refresh?.();
      mirrorSubmission();
      return true;
    } catch (error) {
      const detail = model().errorDetail(error);
      item.phase = "failed";
      item.error = detail;
      const current = model().itemFor(state, group);
      if (current && current !== item) {
        current.phase = "failed";
        current.error = detail;
      }
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
