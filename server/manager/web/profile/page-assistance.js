(() => {
  const registrations = new Map();
  const restoringTabs = new Set();

  function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
  }

  function register(context, adapter, options = {}) {
    for (const name of [
      "schema", "exportDocument", "importDocument", "navigation",
    ]) {
      if (typeof adapter?.[name] !== "function") {
        throw new Error(`page assistance adapter requires ${name}`);
      }
    }
    const independent = context.testObjectOverlay !== true;
    const session = !independent ? {} : typeof context.tabSession === "function"
      ? context.tabSession(context.tabID) : (context.tabSession || {});
    session.durable = session.durable || {};
    let revision = Math.max(0, Number(session.durable.assistanceRevision) || 0);
    let prepared = false;
    let lastSerialized = session.durable.assistanceSnapshot
      ? JSON.stringify(session.durable.assistanceSnapshot.document) : null;
    let bridge = null;
    let connection = null;
    let connectionGeneration = 0;
    let profilePromise = null;
    let selectedProfile = null;
    const resolveProfiles = options.resolveProfiles || (context.parentResearchID
      ? () => window.FTPageAgentProfiles.forPage(context) : null);
    const resolveProfile = () => {
      if (!profilePromise) {
        profilePromise = Promise.resolve(selectedProfile || (options.resolveProfile
          ? options.resolveProfile()
          : (options.boundProfileID
            ? window.FTPageAgentProfiles.bound(context, options.boundProfileID)
            : window.FTPageAgentProfiles.self(context))));
      }
      return profilePromise;
    };
    const controller = Object.freeze({
      prepare: async () => {
        if (prepared) return;
        await adapter.prepare?.();
        prepared = true;
      },
      snapshot: () => {
        const document = clone(adapter.exportDocument());
        const serialized = JSON.stringify(document);
        if (lastSerialized === null) {
          lastSerialized = serialized;
        } else if (serialized !== lastSerialized) {
          revision += 1;
          session.durable.assistanceRevision = revision;
          lastSerialized = serialized;
        }
        const snapshot = {
          schema_version: 1,
          page_kind: String(options.pageKind || ""),
          view: clone(options.view?.() || {}),
          navigation: clone(adapter.navigation()),
          document_schema: clone(adapter.schema()),
          document,
          revision,
        };
        session.durable.assistanceSnapshot = clone(snapshot);
        return snapshot;
      },
      apply: async value => {
        await controller.prepare();
        controller.snapshot(); // Catch user edits made since the last publish.
        const expected = Number(value?.expected_revision);
        if (!Number.isInteger(expected) || expected !== revision) {
          throw new Error(`page assistance revision conflict: expected ${revision}`);
        }
        const document = clone(value?.document);
        if (!document || typeof document !== "object" || Array.isArray(document)) {
          throw new Error("page assistance document must be an object");
        }
        await adapter.validate?.(document);
        await adapter.importDocument(document);
        revision += 1;
        session.durable.assistanceRevision = revision;
        // The imported document is the authoritative atomic replacement. Some
        // pages rebuild their view model only after the server acknowledges the
        // application; exporting during that interval would read a deliberately
        // transient state and can fail or manufacture a different document.
        lastSerialized = JSON.stringify(document);
        session.durable.assistanceSnapshot = {
          ...session.durable.assistanceSnapshot, document: clone(document), revision,
        };
        context.checkpointTabSession?.();
        return revision;
      },
      afterAcknowledge: async value => {
        if (value?.result?.success === true) {
          await adapter.afterApply?.(clone(value));
          context.pageState?.capture?.();
          context.persistAssistanceTab?.(context.tabID);
        }
      },
      connect: async () => {
        if (bridge?.isDisposed?.()) bridge = null;
        if (bridge) {
          await bridge.activate?.();
          return bridge;
        }
        if (!connection) {
          const generation = connectionGeneration;
          connection = (async () => {
            await controller.prepare();
            const profile = await resolveProfile();
            const profileID = String(profile?.profile_id || "").trim();
            if (!profileID) throw new Error("页面 Agent 缺少 Profile");
            const value = window.FTPageAgentContext.create(
              context, profileID, controller,
            );
            try {
              await value.start();
            } catch (error) {
              value.dispose();
              throw error;
            }
            if (generation !== connectionGeneration) {
              value.dispose();
              return null;
            }
            bridge = value;
            return value;
          })().finally(() => { connection = null; });
        }
        return connection;
      },
      disconnect: () => {
        connectionGeneration += 1;
        bridge?.dispose();
        bridge = null;
      },
      selectProfile: profile => {
        controller.disconnect();
        selectedProfile = profile;
        profilePromise = Promise.resolve(profile);
      },
    });
    if (independent) registrations.set(context.tabID, {controller, context});
    // Snapshot the page contract while mounted, before its DOM can be evicted.
    // This loads only the page adapter, never the Agent/chat runtime.
    let disposed = false;
    void controller.prepare().then(() => {
      if (disposed) return;
      controller.snapshot();
      if (independent) context.persistAssistanceTab?.(context.tabID);
    }).catch(() => {});
    context.pageState?.register?.("page-assistance-connection", {
      capture: () => {
        if (prepared) {
          try { controller.snapshot(); }
          catch (_) { /* Keep the last stable contract during view rebuilding. */ }
        }
        return null;
      },
      // The global trigger owns activation. Restoring a parked tab must not
      // load the assistance bridge until the user opens the drawer.
      restore: () => {},
      dispose: () => {
        disposed = true;
        controller.disconnect();
        if (registrations.get(context.tabID)?.controller === controller) {
          registrations.delete(context.tabID);
        }
      },
    });
    if (independent && context.isRouteCurrent?.() !== false) {
      window.FTPageAgentDrawer.attach(
        context, {
          ...options,
          ...(resolveProfiles ? {resolveProfiles} : {}),
          resolveProfile,
          onProfileChange: controller.selectProfile,
          assistance: controller,
        },
      );
    }
    return controller;
  }

  async function workspace(context) {
    const workspace = context.assistanceWorkspace?.();
    if (!workspace) return null;
    const tabs = [];
    for (const item of workspace.tabs) {
      const registration = registrations.get(item.tab_id);
      let snapshot = item.session?.durable?.assistanceSnapshot || null;
      if (registration) {
        try {
          await registration.controller.prepare();
          snapshot = registration.controller.snapshot();
        } catch (_) { /* A page still loading publishes metadata only. */ }
      }
      const {session, ...metadata} = item;
      tabs.push({...metadata, assistance: snapshot});
    }
    return {active_tab_id: workspace.active_tab_id, tabs};
  }

  async function stage(context, profileID, item) {
    const tab = context.assistanceWorkspace?.().tabs.find(tab => tab.tab_id === item.tab_id);
    if (!tab) throw new Error("目标页面已关闭");
    if (tab.tab_id === context.assistanceWorkspace().active_tab_id) {
      const target = registrations.get(tab.tab_id)?.controller;
      if (!target) throw new Error("目标页面尚未声明可填写配置");
      const revision = await target.apply(item);
      return {revision, target};
    }
    const durable = tab.session.durable ||= {};
    if (durable.pendingAssistance && durable.pendingAssistance.item.sequence !== item.sequence) {
      throw new Error("目标页面已有待恢复的填写修改");
    }
    const snapshot = durable.assistanceSnapshot;
    if (!snapshot || snapshot.revision !== item.expected_revision) {
      throw new Error("目标页面配置版本冲突");
    }
    durable.pendingAssistance = {profile_id: profileID, item: clone(item)};
    context.persistAssistanceTab(item.tab_id);
    // Keep the server receipt queued until the owning page validates/imports.
    return {deferred: true};
  }

  async function resume(context) {
    const registration = registrations.get(context.tabID);
    const session = typeof context.tabSession === "function"
      ? context.tabSession(context.tabID) : context.tabSession;
    const pending = session?.durable?.pendingAssistance;
    if (!pending || !registration || restoringTabs.has(context.tabID)) return;
    restoringTabs.add(context.tabID);
    try {
      if (!pending.result) {
        // Network failures leave the durable application intact for retry.
        const receipt = await context.api(`/api/client/profile-agent/assistance?profile_id=${encodeURIComponent(pending.profile_id)}&tab_id=${encodeURIComponent(context.tabID)}`);
        if (context.isRouteCurrent?.() === false) return;
        try {
          if (!receipt.page || Number(pending.item.expires_at || 0) * 1000 < Date.now()) {
            throw new Error("填写目标已失效或权限已改变，请重新提交");
          }
          const revision = await registration.controller.apply(pending.item);
          pending.result = {success: true, revision};
          await registration.controller.afterAcknowledge({result: pending.result});
        } catch (error) {
          pending.result = {success: false, error: String(error.message || error)};
          context.showNotice?.(pending.result.error);
        }
        context.persistAssistanceTab(context.tabID);
      }
      await context.api("/api/client/profile-agent/assistance/acknowledge", {
        method: "POST", body: JSON.stringify({profile_id: pending.profile_id,
          sequence: pending.item.sequence, ...pending.result}),
      });
      delete session.durable.pendingAssistance;
      context.persistAssistanceTab(context.tabID);
    } catch (error) {
      context.showNotice?.(String(error.message || error));
    } finally {
      restoringTabs.delete(context.tabID);
    }
  }

  window.FTPageAssistance = Object.freeze({register, workspace, stage, resume});
})();
