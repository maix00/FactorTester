(() => {
  function clone(value) {
    return value === undefined ? undefined : structuredClone(value);
  }

  function register(context, adapter, options = {}) {
    for (const name of ["schema", "exportDocument", "importDocument"]) {
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
        lastSerialized = JSON.stringify(adapter.exportDocument());
        context.checkpointTabSession?.();
        return revision;
      },
    });
    void (async () => {
      const profile = options.boundProfileID
        ? await window.FTPageAgentProfiles.bound(context, options.boundProfileID)
        : await window.FTPageAgentProfiles.self(context);
      if (context.isRouteCurrent?.() === false) return;
      window.FTPageAgentDrawer.attach(context, {...options, profile, assistance: controller});
    })().catch(error => context.showNotice?.(String(error?.message || error)));
    return controller;
  }

  window.FTPageAssistance = Object.freeze({register});
})();
