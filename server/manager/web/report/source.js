(() => {
  function indexItems(items, keySelector) {
    const index = new Map();
    (items || []).forEach(item => {
      keySelector(item).filter(Boolean).forEach(key => index.set(key, item));
    });
    return index;
  }

  function dataURL(item) {
    return item?.content_base64
      ? `data:${item.media_type || "application/octet-stream"};base64,${item.content_base64}`
      : "";
  }

  function basePath(publicationID) {
    let decoded = String(publicationID || "");
    try { decoded = decodeURIComponent(decoded); } catch (_) {}
    const isLocal = decoded.startsWith("local:");
    const isServer = decoded.startsWith("server:");
    const localRef = isLocal ? decoded.slice("local:".length) : "";
    const serverRef = isServer ? decoded.slice("server:".length) : "";
    return {
      publicationID: decoded,
      isLocal,
      isServer,
      isOwnerLocal: isLocal || isServer,
      localRef,
      serverRef,
      path: isLocal
        ? `/api/client/research/${encodeURIComponent(localRef)}`
        : isServer
        ? `/api/server-research/${encodeURIComponent(serverRef)}`
        : `/api/public-research/${encodeURIComponent(decoded)}`,
    };
  }

  function normalize(value) {
    value.assets ||= [];
    value.local_resources ||= [];
    value.related_objects ||= [];
    value.attachments ||= [];
    return value;
  }

  function create(publicationID, api, options = {}) {
    let source = basePath(publicationID);
    let targetRef = String(options.ownerRef || "");
    const sourceKind = String(options.sourceKind || "").trim();
    const sourceKindMatches = (sourceKind === "publication" && !source.isLocal && !source.isServer)
      || (sourceKind === "client" && source.isLocal)
      || (sourceKind === "server_agent" && source.isServer);
    function addressed(path) {
      if (!source.isServer || !targetRef) return path;
      return `${path}${path.includes("?") ? "&" : "?"}target_ref=${encodeURIComponent(targetRef)}`;
    }
    const request = (path, options) => api(addressed(path), options);
    let value = null;
    let chapterLazy = true;
    let componentLazy = true;
    let assetIndex = new Map();
    let localResourceIndex = new Map();
    let assetIDs = new Map();
    let indexSignature = "";

    function rebuildIndexes() {
      assetIndex = indexItems(value?.assets, item => [
        item.asset_id, item.asset_ref, item.external_ref, item.filename,
      ]);
      localResourceIndex = indexItems(
        value?.local_resources,
        item => [item.resource_id],
      );
      assetIDs = new Map();
      (value?.assets || []).forEach(item => {
        const assetID = item.asset_id || item.asset_ref;
        [item.asset_ref, item.asset_id, item.external_ref, item.filename]
          .filter(Boolean)
          .forEach(key => assetIDs.set(key, assetID));
      });
    }

    function setChapterMetadata(chapter) {
      componentLazy = Boolean(chapter?.content_lazy);
      // Chapter sidecars are the active metadata window.  Keeping every
      // visited chapter's assets and related objects in the report root made
      // the JS model grow without bound even though the renderer's chapter
      // cache is bounded.
      ["assets", "local_resources", "related_objects", "attachments"]
        .forEach(key => { value[key] = Array.isArray(chapter?.[key]) ? chapter[key] : []; });
      rebuildIndexes();
    }

    async function load() {
      // Restore old independent report tabs from their existing research scope.
      if (options.researchID && !sourceKindMatches && (source.isServer
          || (!source.isOwnerLocal && /^[^:]+:[^:]+:[^:]+$/.test(source.publicationID)))) {
        const catalog = await api(`/api/research/${encodeURIComponent(options.researchID)}/reports`);
        const report = (catalog.reports || []).find(item => (
          item.source_ref === source.serverRef || item.source_ref === source.publicationID
        ));
        if (report?.build_source === "server_agent" && !source.isOwnerLocal
            && report.source_ref === source.publicationID
            && report.selected_branch?.source_kind !== "publication"
            && report.source_kind !== "publication") {
          source = basePath(`server:${report.source_ref}`);
        }
        targetRef ||= String(report?.owner_ref || "");
        const branchRef = (source.serverRef || source.publicationID).split(":").at(-1);
        const publication = (report?.branches || []).find(branch =>
          branch.source_kind === "publication" && branch.branch_ref === branchRef);
        if (publication?.publication_id) source = basePath(publication.publication_id);
      }
      const indexPath = `${source.path}/index`;
      try {
        value = normalize(await request(indexPath));
      } catch (error) {
        // A 404 is the only supported signal for an older Manager that has
        // not published the bounded index/chapter endpoints.  Do not turn
        // auth or malformed-response failures into a second full read.
        if (error?.status !== 404) throw error;
        value = normalize(await request(source.path));
        chapterLazy = false;
      }
      indexSignature = JSON.stringify(value);
      rebuildIndexes();
      return value;
    }

    function watch({isCurrent, onChange, interval = 5000}) {
      let disposed = false;
      let timer = null;
      let pending = false;
      const check = async () => {
        if (disposed || pending || !isCurrent() || document.hidden) return;
        pending = true;
        try {
          // Read the bounded index; never prefetch report bodies or chapters.
          const next = normalize(await request(`${source.path}/index`));
          const signature = JSON.stringify(next);
          if (!disposed && isCurrent() && signature !== indexSignature) {
            value = next;
            rebuildIndexes();
            await onChange(next);
            indexSignature = signature;
          }
        } catch (_) { /* Retry a temporary failure on the next visible check. */ }
        finally { pending = false; }
      };
      const schedule = () => {
        if (disposed) return;
        timer = setTimeout(async () => { await check(); schedule(); }, interval);
      };
      window.addEventListener?.("focus", check);
      document.addEventListener?.("visibilitychange", check);
      schedule();
      return () => {
        disposed = true;
        clearTimeout(timer);
        window.removeEventListener?.("focus", check);
        document.removeEventListener?.("visibilitychange", check);
      };
    }

    async function loadChapter(chapterID, options = {}) {
      const chapterPath = `${source.path}/chapters/${encodeURIComponent(chapterID)}`;
      let chapter;
      try {
        const separator = chapterPath.includes("?") ? "&" : "?";
        chapter = await request(options.full ? chapterPath : `${chapterPath}${separator}metadata=1`, options);
      } catch (error) {
        // A 404 means this manager predates component-level lazy loading. The
        // existing chapter endpoint remains the compatibility boundary.
        if (error?.status !== 404) throw error;
        chapter = await request(chapterPath, options);
      }
      if (options.applyMetadata !== false) setChapterMetadata(chapter);
      return chapter;
    }

    async function loadComponent(chapterID, componentID, options = {}) {
      const componentPath = `${source.path}/chapters/${encodeURIComponent(chapterID)}`
        + `/components/${encodeURIComponent(componentID)}`;
      let value;
      try {
        value = await request(componentPath, options);
      } catch (error) {
        // A mixed-version manager may expose metadata but not the component
        // route yet. Use the old chapter response only for that 404 boundary;
        // auth and server errors must remain visible to the report.
        if (error?.status !== 404) throw error;
        value = await request(
          `${source.path}/chapters/${encodeURIComponent(chapterID)}`,
          options,
        );
      }
      return value?.components?.find(item =>
        String(item?.component_id || "") === String(componentID),
      ) || value?.component || null;
    }

    function localResourcePath(resourceID) {
      if (source.isLocal) {
        return addressed(`${source.path}/local-resources/${encodeURIComponent(resourceID)}?inline=1`);
      }
      return addressed(`${source.path}/local-resources/${encodeURIComponent(resourceID)}?inline=1`);
    }

    function reportAssetPath(assetRef) {
      const assetID = assetIDFor(assetRef);
      return addressed(`${source.path}/assets/${encodeURIComponent(assetID)}`);
    }

    function assetIDFor(assetRef) {
      return assetIDs.get(assetRef) || assetRef;
    }

    return Object.freeze({
      get publicationID() { return source.publicationID; },
      get isLocal() { return source.isLocal; },
      get isServer() { return source.isServer; },
      get isOwnerLocal() { return source.isOwnerLocal; },
      get localRef() { return source.localRef; },
      get serverRef() { return source.serverRef; },
      get path() { return source.path; },
      load,
      watch,
      loadChapter,
      loadComponent,
      setChapterMetadata,
      localResourcePath,
      reportAssetPath,
      assetID: assetIDFor,
      get value() { return value; },
      get chapterLazy() { return chapterLazy; },
      get componentLazy() { return componentLazy; },
      get assetIndex() { return assetIndex; },
      get localResourceIndex() { return localResourceIndex; },
    });
  }

  window.FTReportSource = Object.freeze({create, indexItems, dataURL});
})();
