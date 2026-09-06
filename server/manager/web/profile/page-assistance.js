(() => {
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
    const session = typeof context.tabSession === "function"
      ? context.tabSession(context.tabID) : (context.tabSession || {});
    session.durable = session.durable || {};
    let revision = Math.max(0, Number(session.durable.assistanceRevision) || 0);
    let prepared = false;
    let lastSerialized = null;
    let bridge = null;
    let connection = null;
    let connectionGeneration = 0;
    let profilePromise = null;
    let selectedProfile = null;
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
        return {
          schema_version: 1,
          page_kind: String(options.pageKind || ""),
          view: clone(options.view?.() || {}),
          navigation: clone(adapter.navigation()),
          document_schema: clone(adapter.schema()),
          document,
          revision,
        };
      },
      apply: async value => {
        await controller.prepare();
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
        context.checkpointTabSession?.();
        return revision;
      },
      afterAcknowledge: async value => {
        if (value?.result?.success === true) {
          await adapter.afterApply?.(clone(value));
        }
      },
      connect: async () => {
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
    context.pageState?.register?.("page-assistance-connection", {
      restore: () => { void controller.connect().catch(() => {}); },
      dispose: controller.disconnect,
    });
    if (context.isRouteCurrent?.() !== false) {
      void controller.connect().catch(() => {});
      window.FTPageAgentDrawer.attach(
        context, {
          ...options,
          resolveProfile,
          onProfileChange: controller.selectProfile,
          assistance: controller,
        },
      );
    }
    return controller;
  }

  window.FTPageAssistance = Object.freeze({register});
})();
