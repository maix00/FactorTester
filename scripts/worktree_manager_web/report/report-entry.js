(() => {
  function indexItems(items, keySelector) {
    const index = new Map();
    (items || []).forEach(item => {
      keySelector(item).filter(Boolean).forEach(key => index.set(key, item));
    });
    return index;
  }

  function assetDataURL(index, assetID) {
    const item = index?.get(assetID);
    return item?.content_base64
      ? `data:${item.media_type || "application/octet-stream"};base64,${item.content_base64}`
      : "";
  }

  function localResourceDataURL(index, resourceID) {
    const item = index?.get(resourceID);
    return item?.content_base64
      ? `data:${item.media_type || "application/octet-stream"};base64,${item.content_base64}`
      : "";
  }

  async function render(publicationID, context) {
    publicationID = decodeURIComponent(publicationID);
    const {state, api, t, content, toolbar} = context;
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    const isLocal = publicationID.startsWith("local:");
    const localRef = isLocal ? publicationID.slice("local:".length) : "";
    const session = context.tabSession(`report:${publicationID}`);
    const restoreScrollY = session.publicationID === publicationID
      && Number.isFinite(session.scrollY) ? session.scrollY : null;
    document.querySelector(".report-mount")?.__ftLazyCleanup?.();
    document.querySelector(".chapter-rail")?.__ftChapterRailCleanup?.();
    context.activeNav("research");
    content.innerHTML = '<div class="empty"><p></p></div>';
    content.querySelector("p").textContent = t("正在读取研究报告…");
    const fullReportPath = isLocal
      ? `/api/client/research/${encodeURIComponent(localRef)}`
      : `/api/public-research/${publicationID}`;
    const indexPath = `${fullReportPath}/index`;
    let value;
    let chapterLazy = true;
    try {
      value = await api(indexPath);
    } catch (_) {
      // Older Manager instances expose only the complete projection. Keep a
      // safe read-only fallback while the index/chapter endpoints roll out.
      value = await api(fullReportPath);
      chapterLazy = false;
    }
    if (!isCurrent()) return;
    value.assets ||= [];
    value.local_resources ||= [];
    value.related_objects ||= [];
    value.attachments ||= [];
    const assetIndex = indexItems(value.assets, item => [
      item.asset_id, item.asset_ref, item.external_ref, item.filename,
    ]);
    const localResourceIndex = indexItems(value.local_resources, item => [item.resource_id]);
    state.report = value;
    state.activePublicationID = publicationID;
    context.setHeading(value.title, t("研究报告"));
    context.updateActiveTab({title: value.title});
    const branches = Array.isArray(value.branches) ? value.branches : [];
    if (branches.length > 1) {
      const branchPicker = document.createElement("select");
      branchPicker.className = "branch-picker";
      branches.forEach(branch => {
        const option = document.createElement("option");
        option.value = branch.href || branch.branch_ref || "";
        option.textContent = branch.title || branch.branch_ref || t("研究路径");
        branchPicker.append(option);
      });
      toolbar.append(branchPicker);
    }
    toolbar.append(context.button("↻", () => render(publicationID, context), t("刷新")));
    if (value.access?.can_manage) {
      toolbar.append(context.button("⚙", context.openReportSettings, t("研究报告设置")));
    }
    const layout = document.createElement("div"); layout.className = "report-layout";
    const rail = document.createElement("nav"); rail.className = "chapter-rail";
    const mount = document.createElement("div"); mount.className = "report-mount";
    layout.append(mount); content.replaceChildren(layout, rail);
    const assetIDs = new Map();
    for (const item of value.assets || []) {
      const assetID = item.asset_id || item.asset_ref;
      for (const key of [item.asset_ref, item.asset_id, item.external_ref, item.filename]) {
        if (key) assetIDs.set(key, assetID);
      }
    }
    FTReportRenderer.render(value, mount, {
      chapterRail: rail,
      loadChapter: chapterLazy ? async (chapterID, options = {}) => {
        const chapterPath = `${fullReportPath}/chapters/${encodeURIComponent(chapterID)}`;
        const chapter = await api(chapterPath, options);
        const merge = (key, idKey) => {
          const current = new Map((value[key] || []).map(item => [item[idKey], item]));
          (chapter[key] || []).forEach(item => current.set(item[idKey], item));
          value[key] = [...current.values()];
        };
        merge("assets", "asset_id");
        merge("local_resources", "resource_id");
        merge("related_objects", "object_ref");
        merge("attachments", "attachment_ref");
        (chapter.assets || []).forEach(item => {
          [item.asset_id, item.asset_ref, item.external_ref, item.filename]
            .filter(Boolean).forEach(key => assetIndex.set(key, item));
        });
        (chapter.local_resources || []).forEach(item => {
          if (item.resource_id) localResourceIndex.set(item.resource_id, item);
        });
        return chapter;
      } : null,
      openLocalResource: (resourceID, label) =>
        openLocal(publicationID, resourceID, label, value.access, context, localResourceIndex),
      localResourcePath: resourceID => isLocal
        ? localResourceDataURL(localResourceIndex, resourceID)
        : `/api/public-research/${encodeURIComponent(publicationID)}/local-resources/${encodeURIComponent(resourceID)}?inline=1`,
      openReference: target => openReference(target, context),
      reportAssetPath: assetRef => {
        const assetID = assetIDs.get(assetRef) || assetRef;
        if (isLocal) return assetDataURL(assetIndex, assetID);
        return `/api/public-research/${encodeURIComponent(publicationID)}/assets/${encodeURIComponent(assetID)}`;
      },
      captureScrollPosition: context.captureScrollPosition,
      restoreScrollY,
      suppressAutoScroll: true,
      t,
    });
    session.publicationID = publicationID;
    requestAnimationFrame(() => {
      if (!isCurrent()) return;
      if (restoreScrollY == null) {
        window.scrollTo({top: document.body.scrollHeight, behavior: "auto"});
      } else {
        // Rendering replaces the document body. Restore after a second layout
        // pass so the rail and lazy content cannot overwrite the saved view.
        requestAnimationFrame(() => {
          if (isCurrent()) window.scrollTo({top: restoreScrollY, behavior: "auto"});
        });
        setTimeout(() => {
          if (isCurrent()) window.scrollTo({top: restoreScrollY, behavior: "auto"});
        }, 0);
      }
    });
  }

  function openReference(target, context) {
    const {state, t, navigate, showNotice} = context;
    try {
      const reference = new URL(target);
      const type = reference.hostname.replaceAll("_", "-");
      const value = decodeURIComponent(reference.pathname.replace(/^\//, ""));
      // When the Web renderer is hosted inside FTClient, typed-object links
      // stay in the native tab stack. Standalone Web uses its own route tabs.
      const nativeHandler = window.webkit?.messageHandlers?.researchReference;
      if (nativeHandler) {
        const binding = (state.report?.bindings || []).find(item => item?.target_ref === target);
        nativeHandler.postMessage({href: target, label: binding?.label || value || target});
        return;
      }
      if (!state.session && showPublicReference(target, type, value, context)) return;
      if (type === "job" && value) return navigate(`/jobs/${encodeURIComponent(value.replace(/^job:/, ""))}`);
      if (type === "factor-family" && value) return navigate(`/factors/family/${encodeURIComponent(value)}`);
      if (type === "factor-set" && value) return navigate(`/factors/set/${encodeURIComponent(value)}`);
      if (type === "factor" && value) {
        const page = value.startsWith("factor-family:") ? "family" : "factor";
        return navigate(`/factors/${page}/${encodeURIComponent(value)}`);
      }
      if (type === "product-group" && value) return navigate(`/products/group/${encodeURIComponent(value)}`);
      if (["product", "contract", "continuous-contract"].includes(type) && value) {
        return navigate(`/products/${type}/${encodeURIComponent(value)}`);
      }
      if ((type === "profile" || type === "profile-revision") && value) {
        return navigate(`/profiles/${encodeURIComponent(value.split(":").pop())}`);
      }
      if (showPublicReference(target, type, value, context)) return;
    } catch (_) {}
    showNotice(t("该引用的 Web 详情页尚未接入统一路由"), true);
  }

  function showPublicReference(target, type, value, context) {
    const {state} = context;
    const report = state.report;
    if (!report || !Array.isArray(report.related_objects)) return false;
    const object = report.related_objects.find(item =>
      item.object_ref === target || item.object_ref === value
    );
    if (!object) return false;
    context.saveActiveTabSession();
    const id = `public-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
    state.referenceSnapshots.set(id, {object, type, publicationID: state.activePublicationID});
    context.openTab(`/reference/${encodeURIComponent(id)}`, {
      title: object.title || type || context.t("引用对象"),
      icon: FTIcons.reference(type, target),
    });
    return true;
  }

  function publicReference(id, context) {
    const {state, t, content} = context;
    const snapshot = state.referenceSnapshots.get(id);
    if (!snapshot) throw new Error(t("引用快照不存在"));
    const {object, type, publicationID} = snapshot;
    context.activeNav("");
    context.setHeading(object.title || type || t("引用对象"), t("引用详情"));
    const root = document.createElement("div");
    root.className = "detail-stack reference-detail-page";
    const scope = document.createElement("p");
    scope.className = "reference-detail-scope";
    scope.textContent = `${t("类型")}: ${object.object_kind || type} · ${t("解析方式")}: ${object.resolution || t("报告快照")}`;
    root.append(scope);
    const fields = FTUI.fieldRows({[t("对象引用")]: object.object_ref, ...(object.snapshot || {})});
    if (fields.length) root.append(FTUI.table([t("字段"), t("值")], fields).shell);
    const snapshotValue = object.snapshot || {};
    const latex = snapshotValue.math_expr || snapshotValue.formula || snapshotValue.latex;
    if (latex && window.katex) {
      const section = document.createElement("section");
      section.className = "factor-family-summary";
      const heading = document.createElement("h3"); heading.textContent = t("FactorExpr 公式");
      const formula = document.createElement("div"); formula.className = "factor-family-formula display-math";
      katex.render(String(latex), formula, {displayMode: true, throwOnError: false});
      section.append(heading, formula); root.append(section);
    }
    const refs = Array.isArray(object.attachment_refs) ? object.attachment_refs : [];
    if (refs.length && publicationID) {
      const section = document.createElement("section");
      section.className = "reference-attachments";
      const heading = document.createElement("h3"); heading.textContent = t("随附快照");
      section.append(heading);
      for (const ref of refs) {
        const metadata = (state.report?.attachments || []).find(item => item.attachment_ref === ref);
        const hash = /^attachment:sha256:([a-f0-9]{64})$/i.exec(ref || "")?.[1];
        if (!hash) continue;
        const link = document.createElement("a");
        link.href = `/api/public-research/${encodeURIComponent(publicationID)}/attachments/${hash}`;
        link.textContent = metadata?.filename || ref;
        link.download = metadata?.filename || "attachment";
        section.append(link);
      }
      if (section.querySelector("a")) root.append(section);
    }
    content.replaceChildren(root);
  }

  async function openLocal(publicationID, resourceID, label, access, context, resourceIndex) {
    const {state, t, showNotice} = context;
    const metadata = resourceIndex?.get(resourceID)
      || (state.report?.local_resources || []).find(item => item?.resource_id === resourceID);
    if (!metadata || metadata.available === false) {
      return showNotice(t("该本地文件未随研究报告上传"), true);
    }
    const filename = metadata.filename || label || t("本地文件");
    if (!window.confirm(`${t("是否下载本地文件")}: ${filename}?`)) return;
    let blob;
    if (publicationID.startsWith("local:")) {
      const dataURL = localResourceDataURL(
        resourceIndex || indexItems(state.report?.local_resources, item => [item.resource_id]),
        resourceID,
      );
      if (!dataURL) return showNotice(t("本地文件下载失败"), true);
      try { blob = await (await fetch(dataURL)).blob(); }
      catch (_) { return showNotice(t("本地文件下载失败"), true); }
    } else {
      const response = await fetch(
        `/api/public-research/${encodeURIComponent(publicationID)}/local-resources/${encodeURIComponent(resourceID)}`,
        {credentials: "same-origin"},
      );
      if (!response.ok) return showNotice(t("本地文件下载失败"), true);
      blob = await response.blob();
    }
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = filename;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  window.FTReportEntry = {render, openReference, publicReference, openLocal};
})();
