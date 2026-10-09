(() => {
  async function render(publicationID, context) {
    try { publicationID = decodeURIComponent(String(publicationID || "")); }
    catch (_) { publicationID = String(publicationID || ""); }
    const {state, api, t, content} = context;
    const isCurrent = () => context.isRouteCurrent?.() !== false;
    if (!isCurrent()) return;
    const source = FTReportSource.create(publicationID, api, {
      ownerRef: new URLSearchParams(location.search).get("owner_ref") || "",
      researchID: new URLSearchParams(location.search).get("research_id") || "",
      sourceKind: new URLSearchParams(location.search).get("report_source_kind") || "",
    });
    // The research feature tab owns the report list. A concrete report owns
    // its actual closable left-sidebar tab, so reading state must stay on
    // that tab instead of a publication-only alias shared by reports.
    const session = context.tabSession(
      context.tabID || `report:${publicationID}`,
    );
    session.durable ||= {};
    const renderGeneration = Math.max(
      0, Number(session.durable.reportRenderGeneration) || 0,
    ) + 1;
    session.durable.reportRenderGeneration = renderGeneration;
    const isRenderCurrent = () => isCurrent()
      && session.durable.reportRenderGeneration === renderGeneration;
    session.durable.reportReadingByBranch ||= {};
    if (!session.durable.reportReadingByBranch[publicationID]) {
      const isFirstBranch = Object.keys(
        session.durable.reportReadingByBranch,
      ).length === 0;
      session.durable.reportReadingByBranch[publicationID] = isFirstBranch
        ? (session.durable.reportReading || {disclosures: {}})
        : {disclosures: {}};
    }
    const reading = session.durable.reportReadingByBranch[publicationID];
    session.durable.reportReading = reading;
    reading.disclosures ||= {};
    // Reader state — which sections the reader expanded, and the chapter — is
    // persisted per publication and applied synchronously below, so a refresh
    // restores the same expansion level before the first paint.  The tab
    // session checkpoint alone is not authoritative (it may be missing on
    // reload), so a durable store keeps the level across a refresh.
    const durableReadingKey = `ft-report-reading:${encodeURIComponent(publicationID)}`;
    const readDurableReading = () => {
      try {
        const raw = localStorage.getItem(durableReadingKey);
        return raw ? JSON.parse(raw) : null;
      } catch (_) { return null; }
    };
    const persistReading = () => {
      try {
        localStorage.setItem(durableReadingKey, JSON.stringify({
          disclosures: reading.disclosures,
          selected_chapter_id: reading.selectedChapterID || "",
        }));
      } catch (_) {}
    };
    if (Object.keys(reading.disclosures).length === 0) {
      const durable = readDurableReading();
      if (durable?.disclosures && typeof durable.disclosures === "object") {
        reading.disclosures = durable.disclosures;
      }
      if (!reading.selectedChapterID && durable?.selected_chapter_id) {
        reading.selectedChapterID = durable.selected_chapter_id;
      }
    }
    context.pageState?.register?.("research-report", {
      capture: () => ({
        selected_chapter_id: reading.selectedChapterID || "",
        disclosures: reading.disclosures,
      }),
      restore: value => {
        reading.selectedChapterID = value?.selected_chapter_id || reading.selectedChapterID || "";
        // Mutate in place: the renderer captured this object's reference.
        if (value?.disclosures && typeof value.disclosures === "object") {
          Object.assign(reading.disclosures, value.disclosures);
        }
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
    let value = await source.load();
    if (!isRenderCurrent()) return;
    state.report = value;
    state.activePublicationID = publicationID;
    context.setHeading(value.title, t("研究报告"));
    session.durable.heading = {
      title: value.title,
      eyebrow: t("研究报告"),
    };
    context.updateActiveTab({title: value.title});
    const transferContext = {api, t};
    const researchID = String(
      value.research_id
      || new URLSearchParams(location.search).get("research_id")
      || "",
    ).trim();
    let branches = Array.isArray(value.branches) ? value.branches : [];
    const branchDirectoryPromise = researchID
      ? Promise.resolve()
          .then(() => api(
            `/api/research/${encodeURIComponent(researchID)}/reports`,
          ))
          .then(catalog => {
            const report = (catalog.reports || []).find(item => (
              String(item.report_id || "") === String(value.report_id || "")
            ));
            return Array.isArray(report?.branches) && report.branches.length
              ? report.branches : null;
          })
          .catch(() => null)
      : Promise.resolve(null);
    const reportControls = document.createElement("div");
    reportControls.className = "research-report-actions";
    let branchPicker = null;
    const renderBranchPicker = nextBranches => {
      branches = Array.isArray(nextBranches) ? nextBranches : [];
      if (!branches.length) {
        branchPicker?.remove();
        branchPicker = null;
        return;
      }
      const priorPublicationID = branchPicker?.value || publicationID;
      const picker = document.createElement("select");
      picker.className = "branch-picker";
      const currentBranch = branches.find(branch => (
        branch.publication_id === priorPublicationID
      ))
        || branches.find(branch => branch.selected) || branches[0];
      branches.forEach(branch => {
        const option = document.createElement("option");
        option.value = branch.publication_id || "";
        option.textContent = FTUI.reportBranchLabel(branch, value);
        option.title = branch.principal_ref || branch.owner_ref || value.owner_ref || "";
        option.selected = branch === currentBranch;
        picker.append(option);
      });
      picker.setAttribute("aria-label", t("研究路径"));
      picker.addEventListener("change", () => {
        const targetPublicationID = picker.value;
        if (!targetPublicationID || targetPublicationID === publicationID) return;
        const target = branches.find(branch => (
          branch.publication_id === targetPublicationID
        ));
        if (target?.href) {
          context.updateActiveTab({path: target.href});
          history.replaceState(history.state, "", target.href);
        }
        render(targetPublicationID, context);
      });
      if (branchPicker) branchPicker.replaceWith(picker);
      else reportControls.prepend(picker);
      branchPicker = picker;
    };
    renderBranchPicker(branches);
    FTResearchReportSettings.applyReading(context);
    const infoActions = document.createElement("span");
    infoActions.className = "research-report-actions";
    infoActions.append(FTUI.iconButton(
      context, "arrow.clockwise", "刷新", () => render(publicationID, context),
    ));
    {
      infoActions.append(FTUI.iconButton(
        context, "gearshape", "研究报告设置",
        () => FTResearchReportSettings.open(
          context, {...value, publication_id: publicationID},
          () => render(publicationID, context),
        ),
      ));
    }
    if (window.FTReportExport?.menu) {
      infoActions.append(window.FTReportExport.menu(
        context, {...value, publication_id: publicationID},
      ));
    }
    reportControls.append(infoActions);
    context.toolbar.replaceChildren(reportControls);
    void branchDirectoryPromise.then(nextBranches => {
      if (!isRenderCurrent() || !nextBranches) return;
      renderBranchPicker(nextBranches);
    });
    const boundProfileID = String(
      value.profile_ref || value.profile_id || value.generation?.profile_id || "",
    ).trim();
    const assistantAllowed = value.access?.can_manage === true
      || value.access?.access_basis === "membership"
      || value.access?.access_basis === "research"
      || value.access?.access_basis === "owner";
    // A Report shared on its own is a read-only publication and must not
    // expose an Agent. Research collaboration (owner/member access) does.
    if ((boundProfileID || researchID) && context.session && assistantAllowed) {
      let profileListPromise = null;
      const resolveProfiles = researchID ? () => {
        profileListPromise ||= FTPageAgentProfiles.forResearch(context, researchID);
        return profileListPromise;
      } : null;
      FTPageAssistance.register(context, {
        navigation: () => ({
          schema_version: 1, root_id: "page", nodes: {
            page: {
              id: "page", kind: "report", label: value.title || "研究报告",
              summary: "研究报告正文通过研究工作流修改",
              children: ["field:selected_chapter", "workflow:report-cli"],
            },
            "workflow:report-cli": {
              id: "workflow:report-cli", kind: "field", label: "报告 CLI 编辑与测试绑定",
              summary: "先读取 CLI --help，再按当前报告范围添加章节、小节或绑定测试；不要通过页面文档替换正文。",
              value: {
                scope: {publication_id: publicationID, research_id: researchID,
                  profile_ref: boundProfileID, report_workspace_id: value.report_workspace_id || value.generation?.report_workspace_id || "",
                  branch_id: value.branch_id || value.generation?.branch_id || ""},
                help: ["factortester research reports --help",
                  "factortester research reports show --help",
                  "factortester research reports add --help",
                  "factortester research run submit --help",
                  "factortester research job watch-report --help"],
                rule: "先 show 检查报告树及作用域。缺少身份时先用 CLI 查询，不能猜测 ID。章节/小节使用 add；测试绑定和结果收集遵循 submit/watch-report 帮助与既有研究工作流。",
              }, children: [],
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
        ...(boundProfileID ? {boundProfileID} : {}),
        ...(!boundProfileID && resolveProfiles ? {
          resolveProfile: async () => (
            (await resolveProfiles())[0] || FTPageAgentProfiles.self(context)
          ),
        } : {}),
        researchID,
        ...(resolveProfiles ? {resolveProfiles} : {}),
        pageKind: "research-report",
        profileKey: value.profile_key || "",
        view: () => ({selected_chapter_id: reading.selectedChapterID || ""}),
      });
    }
    const layout = document.createElement("div"); layout.className = "report-layout";
    const rail = document.createElement("nav"); rail.className = "chapter-rail";
    const mount = document.createElement("div"); mount.className = "report-mount";
    layout.append(mount); content.replaceChildren(layout, rail);
    let refreshScrollY = null;
    const renderContent = () => FTReportRenderer.render(value, mount, {
      chapterRail: rail,
      // The reused Job surfaces of a report's result sections read through the
      // same page context a Job route provides (api/session/notices).
      api,
      session: context.session,
      button: context.button,
      showNotice: context.showNotice,
      navigate: context.navigate,
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
      restoreScrollY: refreshScrollY ?? restoreScrollY,
      selectedChapterID: reading.selectedChapterID || "",
      setSelectedChapter: chapterID => {
        reading.selectedChapterID = chapterID;
        persistReading();
      },
      disclosureState: reading.disclosures,
      setDisclosureState: (componentID, open) => {
        reading.disclosures[componentID] = Boolean(open);
        persistReading();
      },
      onInitialChapterReady: () => {
        // Restore the reader's position only once the first chapter's content
        // is actually rendered.  Scrolling before the lazy chapter loads would
        // move again when the content grows — the visible jump on refresh.
        const target = refreshScrollY ?? restoreScrollY;
        if (target != null) {
          if (isCurrent()) window.scrollTo({top: target, behavior: "auto"});
          return;
        }
        if (!isCurrent()) return;
        requestAnimationFrame(() => {
          if (isCurrent()) window.scrollTo({top: document.body.scrollHeight, behavior: "auto"});
        });
      },
      suppressAutoScroll: true,
      t,
    });
    const renderer = renderContent();
    const stopWatching = source.watch({
      isCurrent,
      onChange: next => {
        if (!isCurrent()) return;

        value = next;
        state.report = next;
        context.setHeading(next.title, t("研究报告"));
        context.updateActiveTab({title: next.title});
        return renderer.update(next);
      },
    });
    context.pageState?.register?.("research-report-updates", {dispose: stopWatching});
    session.publicationID = publicationID;
  }

  function openReference(target, context, labelOverride = "") {
    const {state, t, navigate, showNotice} = context;
    try {
      const reference = new URL(target);
      // Callers outside rich text can also open a reference directly. Never
      // interpret a website hostname as a FactorTester object kind.
      if (["http:", "https:"].includes(reference.protocol)) {
        window.open(reference.href, "_blank", "noopener,noreferrer");
        return;
      }
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
      const heading = document.createElement("h3"); heading.textContent = t("LaTeX 公式");
      const formula = document.createElement("div"); formula.className = "factor-family-formula display-math";
      window.FTUI?.renderMath?.(formula, String(latex), {display: true});
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
