(() => {
  async function render(publicationID, context) {
    try { publicationID = decodeURIComponent(String(publicationID || "")); }
    catch (_) { publicationID = String(publicationID || ""); }
    const {state, api, t, content, toolbar} = context;
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    const source = FTReportSource.create(publicationID, api);
    // The research feature tab owns the report list. A concrete report owns
    // its actual closable left-sidebar tab, so reading state must stay on
    // that tab instead of a publication-only alias shared by reports.
    const session = context.tabSession(
      context.tabID || `report:${publicationID}`,
    );
    session.durable ||= {};
    const reading = session.durable.reportReading ||= {disclosures: {}};
    reading.disclosures ||= {};
    context.pageState?.register?.("research-report", {
      capture: () => ({
        selected_chapter_id: reading.selectedChapterID || "",
        disclosures: reading.disclosures,
      }),
      restore: value => {
        reading.selectedChapterID = value?.selected_chapter_id || reading.selectedChapterID || "";
        reading.disclosures = value?.disclosures || reading.disclosures;
      },
      describe: () => ({
        page: "research-report",
        section: reading.selectedChapterID || "",
        fields: [],
      }),
    });
    const hadPriorReading = Boolean(reading.visited)
      || (session.publicationID === publicationID && Number.isFinite(session.scrollY));
    const restoreScrollY = hadPriorReading && session.publicationID === publicationID
      && Number.isFinite(session.scrollY) ? session.scrollY : null;
    reading.visited = true;
    document.querySelector(".report-mount")?.__ftLazyCleanup?.();
    context.activeNav("research");
    content.innerHTML = '<div class="empty"><p></p></div>';
    content.querySelector("p").textContent = t("正在读取研究报告…");
    const value = await source.load();
    if (!isCurrent()) return;
    state.report = value;
    state.activePublicationID = publicationID;
    context.setHeading(value.title, t("研究报告"));
    session.durable.heading = {
      title: value.title,
      eyebrow: t("研究报告"),
    };
    context.updateActiveTab({title: value.title});
    const transferContext = {api, t};
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
    const boundProfileID = String(
      value.profile_ref || value.profile_id || value.generation?.profile_id || "",
    ).trim();
    if (boundProfileID && context.session) {
      FTPageAssistance.register(context, {
        navigation: () => ({
          schema_version: 1, root_id: "page", nodes: {
            page: {
              id: "page", kind: "report", label: value.title || "研究报告",
              summary: "研究报告正文通过研究工作流修改",
              children: ["field:selected_chapter"],
            },
            "field:selected_chapter": {
              id: "field:selected_chapter", kind: "field", label: "当前章节",
              value: reading.selectedChapterID || "", children: [],
            },
          },
        }),
        schema: () => ({type: "object", readOnly: true}),
        exportDocument: () => ({
          schema_version: 1, document_kind: "research_report_context",
          publication_id: publicationID,
          selected_chapter_id: reading.selectedChapterID || "",
        }),
        validate: () => {},
        importDocument: () => {
          throw new Error(context.t("研究报告正文通过研究工作流修改"));
        },
      }, {
        boundProfileID,
        pageKind: "research-report",
        profileKey: value.profile_key || "",
        view: () => ({selected_chapter_id: reading.selectedChapterID || ""}),
      });
    }
    const layout = document.createElement("div"); layout.className = "report-layout";
    const rail = document.createElement("nav"); rail.className = "chapter-rail";
    const mount = document.createElement("div"); mount.className = "report-mount";
    layout.append(mount); content.replaceChildren(layout, rail);
    FTReportRenderer.render(value, mount, {
      chapterRail: rail,
      loadChapter: source.chapterLazy ? source.loadChapter : null,
      loadComponent: source.loadComponent,
      componentContentLazy: () => source.componentLazy,
      setChapterMetadata: source.setChapterMetadata,
      openLocalResource: (resourceID, label) =>
        openLocal(publicationID, resourceID, label, value.access, context, source.localResourceIndex),
      localResourcePath: source.localResourcePath,
      openReference: (target, label) => openReference(target, context, label),
      // In the Swift client every report hyperlink is offered to the native
      // tab router first.  Standalone Web keeps its ordinary in-page routing.
      nativeReference: Boolean(window.webkit?.messageHandlers?.researchReference),
      publicationID,
      reportAssetPath: source.isOwnerLocal ? source.reportAssetPath : null,
      loadReportAsset: source.isOwnerLocal ? null : assetRef =>
        FTResearchObjectTransfer.blob(
          transferContext,
          publicationID,
          "research_asset",
          source.assetID(assetRef),
        ),
      loadLocalResource: source.isOwnerLocal ? null : resourceID =>
        FTResearchObjectTransfer.blob(
          transferContext,
          publicationID,
          "research_local_resource",
          resourceID,
        ),
      captureScrollPosition: context.captureScrollPosition,
      restoreScrollY,
      selectedChapterID: reading.selectedChapterID || "",
      setSelectedChapter: chapterID => { reading.selectedChapterID = chapterID; },
      disclosureState: reading.disclosures,
      setDisclosureState: (componentID, open) => {
        reading.disclosures[componentID] = Boolean(open);
      },
      onInitialChapterReady: () => {
        if (restoreScrollY != null || !isCurrent()) return;
        requestAnimationFrame(() => {
          if (isCurrent()) window.scrollTo({top: document.body.scrollHeight, behavior: "auto"});
        });
      },
      suppressAutoScroll: true,
      t,
    });
    session.publicationID = publicationID;
    requestAnimationFrame(() => {
      if (!isCurrent()) return;
      if (restoreScrollY != null) {
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

  function openReference(target, context, labelOverride = "") {
    const {state, t, navigate, showNotice} = context;
    try {
      const reference = new URL(target);
      const type = reference.hostname.replaceAll("_", "-");
      const value = decodeURIComponent(reference.pathname.replace(/^\//, ""));
      // Bindings store the typed target (for example ``job:<id>``), while
      // the URL path is percent-encoded. Resolve against both forms so the
      // binding metadata remains available for federated Job routing.
      const binding = (state.report?.bindings || []).find(item => (
        item?.target_ref === value || item?.target_ref === target
      ));
      const port = Number(binding?.data?.port);
      const serverID = String(
        binding?.data?.server_id || binding?.data?.execution_server_id || "",
      ).trim();
      const jobPrefix = Number.isInteger(port) && port > 0 && port <= 65_535
        ? `${port}/` : "";
      // When the Web renderer is hosted inside FTClient, typed-object links
      // stay in the native tab stack. Standalone Web uses its own route tabs.
      const nativeHandler = window.webkit?.messageHandlers?.researchReference;
      if (nativeHandler) {
        const detailFields = {};
        if (binding?.data && typeof binding.data === "object") {
          if (Object.prototype.hasOwnProperty.call(binding.data, "port")) {
            detailFields.port = binding.data.port;
          }
          if (serverID) detailFields.server_id = serverID;
        }
        if (type === "file") {
          detailFields.publication_id = state.activePublicationID || "";
          detailFields.resource_id = value;
        }
        nativeHandler.postMessage({
          href: target,
          label: labelOverride || binding?.label || value || target,
          component_id: binding?.component_id || "",
          detail_fields: detailFields,
        });
        return;
      }
      if (!state.session && showPublicReference(target, type, value, context)) return;
      if (["job", "task"].includes(type) && value) {
        const jobID = value.replace(/^(?:job|research-job|task):/, "");
        const query = serverID
          ? `?server_id=${encodeURIComponent(serverID)}` : "";
        return navigate(
          `/jobs/${jobPrefix}${encodeURIComponent(jobID)}${query}`,
        );
      }
      if (type === "evidence" && value) {
        const route = window.FTReferencePage?.routeFor?.(
          "evidence", value, binding?.label || labelOverride || value, serverID,
        ) || `/reference?kind=evidence&target=${encodeURIComponent(value)}`;
        return navigate(route);
      }
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
      if (type === "profile" && value) {
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
    const heading = object.title || type || t("引用对象");
    context.setHeading(heading, t("引用详情"));
    context.updateActiveTab({title: heading});
    const kind = object.object_kind || type || "reference";
    const sharedHeader = window.FTReferencePage?.headerFor?.(kind, heading, t);
    const presentation = sharedHeader?.presentation || {tone: "link"};
    const root = document.createElement("div");
    root.className = `detail-stack reference-detail-page reference-tone-${presentation.tone}`;
    if (sharedHeader?.header) root.append(sharedHeader.header);
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
        link.href = "#";
        link.textContent = metadata?.filename || ref;
        link.download = metadata?.filename || "attachment";
        link.addEventListener("click", async event => {
          event.preventDefault();
          try {
            const blob = await FTResearchObjectTransfer.blob(
              {api: context.api, t},
              publicationID,
              "research_attachment",
              hash,
            );
            downloadBlob(blob, metadata?.filename || "attachment");
          } catch (error) {
            context.showNotice?.(
              error?.message || t("研究附件下载失败"),
              true,
            );
          }
        });
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
    const nativeHandler = window.webkit?.messageHandlers?.researchReference;
    if (nativeHandler && /^[a-f0-9]{24}$/i.test(String(resourceID || ""))) {
      nativeHandler.postMessage({
        href: `factortester://file/${encodeURIComponent(resourceID)}`,
        label: filename,
        component_id: "",
        detail_fields: {
          publication_id: publicationID,
          resource_id: resourceID,
          filename,
          media_type: metadata.media_type || "",
          size: metadata.size || "",
        },
      });
      return;
    }
    if (!window.confirm(`${t("是否下载本地文件")}: ${filename}?`)) return;
    let blob;
    if (publicationID.startsWith("local:") || publicationID.startsWith("server:")) {
      const isServer = publicationID.startsWith("server:");
      const prefix = isServer ? "server:" : "local:";
      const localRef = publicationID.slice(prefix.length);
      const base = isServer ? "/api/server-research/" : "/api/client/research/";
      const endpoint = `${base}${encodeURIComponent(localRef)}`
        + `/local-resources/${encodeURIComponent(resourceID)}`;
      try {
        const response = await fetch(endpoint, {credentials: "same-origin"});
        if (!response.ok) throw new Error(`local resource ${response.status}`);
        blob = await response.blob();
      }
      catch (_) { return showNotice(t("本地文件下载失败"), true); }
      if (!blob.size) return showNotice(t("本地文件下载失败"), true);
    } else {
      try {
        blob = await FTResearchObjectTransfer.blob(
          {api: context.api, t},
          publicationID,
          "research_local_resource",
          resourceID,
        );
      } catch (error) {
        return showNotice(error?.message || t("本地文件下载失败"), true);
      }
    }
    downloadBlob(blob, filename);
  }

  function downloadBlob(blob, filename) {
    if (!blob) throw new Error("empty research object");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = filename;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  window.FTReportEntry = {render, openReference, publicReference, openLocal};
})();
