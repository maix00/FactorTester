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

  function create(publicationID, api) {
    const source = basePath(publicationID);
    let value = null;
    let chapterLazy = true;
    let componentLazy = true;
    let assetIndex = new Map();
    let localResourceIndex = new Map();
    let assetIDs = new Map();

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
      // Chapter sidecars are the active metadata window.  Keeping every
      // visited chapter's assets and related objects in the report root made
      // the JS model grow without bound even though the renderer's chapter
      // cache is bounded.
      ["assets", "local_resources", "related_objects", "attachments"]
        .forEach(key => { value[key] = Array.isArray(chapter?.[key]) ? chapter[key] : []; });
      rebuildIndexes();
    }

    async function load() {
      const indexPath = `${source.path}/index`;
      try {
        value = normalize(await api(indexPath));
      } catch (error) {
        // A 404 is the only supported signal for an older Manager that has
        // not published the bounded index/chapter endpoints.  Do not turn
        // auth or malformed-response failures into a second full read.
        if (error?.status !== 404) throw error;
        value = normalize(await api(source.path));
        chapterLazy = false;
      }
      rebuildIndexes();
      return value;
    }

    async function loadChapter(chapterID, options = {}) {
      const chapterPath = `${source.path}/chapters/${encodeURIComponent(chapterID)}`;
      let chapter;
      try {
        const separator = chapterPath.includes("?") ? "&" : "?";
        chapter = await api(`${chapterPath}${separator}metadata=1`, options);
      } catch (error) {
        // A 404 means this manager predates component-level lazy loading. The
        // existing chapter endpoint remains the compatibility boundary.
        if (error?.status !== 404) throw error;
        chapter = await api(chapterPath, options);
      }
      componentLazy = Boolean(chapter?.content_lazy);
      setChapterMetadata(chapter);
      return chapter;
    }

    async function loadComponent(chapterID, componentID, options = {}) {
      const componentPath = `${source.path}/chapters/${encodeURIComponent(chapterID)}`
        + `/components/${encodeURIComponent(componentID)}`;
      let value;
      try {
        value = await api(componentPath, options);
      } catch (error) {
        // A mixed-version manager may expose metadata but not the component
        // route yet. Use the old chapter response only for that 404 boundary;
        // auth and server errors must remain visible to the report.
        if (error?.status !== 404) throw error;
        value = await api(
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
        return `${source.path}/local-resources/${encodeURIComponent(resourceID)}?inline=1`;
      }
      return `${source.path}/local-resources/${encodeURIComponent(resourceID)}?inline=1`;
    }

    function reportAssetPath(assetRef) {
      const assetID = assetIDFor(assetRef);
      return `${source.path}/assets/${encodeURIComponent(assetID)}`;
    }

    function assetIDFor(assetRef) {
      return assetIDs.get(assetRef) || assetRef;
    }

    return Object.freeze({
      ...source,
      load,
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
