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
    const decoded = decodeURIComponent(publicationID);
    const isLocal = decoded.startsWith("local:");
    const localRef = isLocal ? decoded.slice("local:".length) : "";
    return {
      publicationID: decoded,
      isLocal,
      localRef,
      path: isLocal
        ? `/api/client/research/${encodeURIComponent(localRef)}`
        : `/api/public-research/${decoded}`,
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
      const chapter = await api(chapterPath, options);
      setChapterMetadata(chapter);
      return chapter;
    }

    function localResourcePath(resourceID) {
      if (source.isLocal) {
        return `${source.path}/local-resources/${encodeURIComponent(resourceID)}?inline=1`;
      }
      return `${source.path}/local-resources/${encodeURIComponent(resourceID)}?inline=1`;
    }

    function reportAssetPath(assetRef) {
      const assetID = assetIDs.get(assetRef) || assetRef;
      if (source.isLocal) return dataURL(assetIndex.get(assetID));
      return `${source.path}/assets/${encodeURIComponent(assetID)}`;
    }

    return Object.freeze({
      ...source,
      load,
      loadChapter,
      setChapterMetadata,
      localResourcePath,
      reportAssetPath,
      get value() { return value; },
      get chapterLazy() { return chapterLazy; },
      get assetIndex() { return assetIndex; },
      get localResourceIndex() { return localResourceIndex; },
    });
  }

  window.FTReportSource = Object.freeze({create, indexItems, dataURL});
})();
