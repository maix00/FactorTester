(() => {
  const definitions = {
    factor: {
      title: "因子",
      load: "factor-catalog-detail-rendering",
      // The embedded editor is deliberately the catalog component itself.
      // The overlay context supplies its mount and onSaved callback, so the
      // catalog create/edit/view behavior is identical to the left-nav tab.
      render: (context, ref, mode, options) => (
        window.FTFactors.factorDetail(context, ref, mode, options)
      ),
    },
    factor_family: {
      title: "因子家族",
      load: "factor-catalog-detail-rendering",
      render: (context, ref, mode, options) => (
        window.FTFactors.familyDetail(context, ref, mode, {
          ...options, familyMode: true,
        })
      ),
    },
    // A nested FactorParam factor is configuration-local: it has no catalog
    // round-trip.  Render its dedicated page straight from the frozen row the
    // opener carried (factor + resolved family), exactly like the nested view
    // of the parameter tree but as a full page inside this nested overlay.
    nested_factor: {
      title: "因子",
      load: "factor-catalog-detail-rendering",
      render: async (context, ref, mode, options) => {
        const initial = {...(options.initialValue || {})};
        const factor = {...initial, ref, factor_ref: ref};
        const family = initial.family || initial.__factor_family || null;
        const families = family ? [family] : [];
        // The frozen nested record may lack typed parameter definitions (the
        // types live on the family template).  Resolve them through the same
        // family-template source the rest of the factor pages use — the
        // catalog library cache — and enrich before rendering, so nested rows
        // keep their real types instead of falling back to Parameter.
        try {
          const catalog = window.FTFactorCatalog;
          if (catalog?.load && typeof catalog.load === "function") {
            const cached = await catalog.load(context, {});
            const cachedFamilies = Array.isArray(cached?.families)
              ? cached.families : [];
            if (cachedFamilies.length) {
              const merged = [...families, ...cachedFamilies];
              const enriched = window.FTFactorDisplayEnrichment
                ?.enrichFactorForDisplay
                ? window.FTFactorDisplayEnrichment.enrichFactorForDisplay(
                  {factors: [factor], families: merged}, factor,
                )
                : null;
              if (enriched && window.FTFactorDetails?.factorDetail) {
                return window.FTFactorDetails.factorDetail(
                  context, {factors: [enriched], families: merged}, ref, "view",
                );
              }
            }
          }
        } catch (_) {
          // Keep the frozen record as-is when no family template is available.
        }
        return window.FTFactorDetails?.factorDetail
          ? window.FTFactorDetails.factorDetail(
            context, {factors: [factor], families}, ref, "view",
          )
          : null;
      },
    },
    factor_set: {
      title: "因子集合",
      load: "factor-catalog-detail",
      render: (context, ref, mode, options) => (
        window.FTFactors.setDetail(context, ref, mode, options)
      ),
    },
    product_group: {
      title: "产品组",
      load: "catalog",
      render: (context, ref, mode) => window.FTProducts.groupDetail(context, ref, mode),
    },
    category: {
      title: "产品分类",
      load: "catalog",
      render: (context, ref, mode) => window.FTProducts.categoryDetail(context, ref, mode),
    },
    strategy: {
      title: "策略",
      load: "strategy-library-editor-core",
      render: (context, ref, mode, options) => {
        if (!window.FTStrategyLibraryEditor?.create) {
          throw new Error("策略编辑器不可用");
        }
        let submitButton = null;
        const editor = window.FTStrategyLibraryEditor.create(
          context,
          options.initialValue || {},
          {
            mode,
            storageMode: options.storageMode || "configuration-inline",
            onSubmit: async (draft, status) => {
              if (submitButton) submitButton.disabled = true;
              try {
                const value = options.onSubmit
                  ? await options.onSubmit(draft, status)
                  : draft;
                if (value !== undefined && value !== null && value !== false) {
                  context.onSaved?.(value);
                  return;
                }
                if (submitButton) submitButton.disabled = false;
              } catch (error) {
                status.textContent = error.message || context.t("策略保存失败");
                if (submitButton) submitButton.disabled = false;
              }
            },
          },
        );
        if (mode !== "view") {
          const actions = document.createElement("div");
          actions.className = "dialog-actions";
          submitButton = window.FTUI.actionButton(
            context.t(options.submitLabel || "保存"), null, {variant: "primary"},
          );
          submitButton.type = "submit";
          actions.append(submitButton);
          editor.form.append(actions);
        }
        context.content.append(editor.form);
      },
    },
  };

  function close(dialog, state, value = null) {
    if (state.closed) return;
    state.closed = true;
    state.cleanup?.();
    state.resolve?.(value);
    if (dialog.open) dialog.close(); else dialog.remove();
  }

  function editorContext(
    context, mount, closeOverlay, onSaved, options = {}, callbacks = {},
  ) {
    const toolbar = callbacks.toolbar || document.createElement("div");
    return {
      ...context,
      content: mount,
      toolbar,
      setHeading: callbacks.setHeading || (() => {}),
      updateActiveTab: () => {},
      activeNav: () => {},
      navigate: callbacks.navigate || (() => closeOverlay()),
      openFactor: callbacks.openFactor,
      openObject: callbacks.openObject,
      closeTab: callbacks.closeFrame || (() => closeOverlay()),
      onSaved,
      pageState: callbacks.pageState || context.pageState,
      testState: options.testState || null,
      testObjectTemporary: options.temporary === true,
      testObjectSnapshot: options.snapshot === true,
      testObjectInitialValue: options.initialValue || null,
      // A temporary object belongs to the current test session: its detail
      // view may offer authoring through the shared mode actions (the page
      // decides), while a plain read-only view (library objects opened as
      // view) stays quiet.
      testObjectViewOnly: options.mode === "view" && options.temporary !== true,
      testObjectOverlay: true,
      openInlineEdit: callbacks.openInlineEdit,
      isRouteCurrent: () => context.isRouteCurrent?.() !== false,
    };
  }

  async function open(context, options = {}) {
    const definition = definitions[options.kind];
    if (!definition) throw new Error(`unsupported test object: ${options.kind}`);
    const mode = ["create", "edit", "view"].includes(options.mode)
      ? options.mode : "create";
    const durable = context.tabSession?.durable;
    const drafts = durable ? (durable.objectOverlays ||= {}) : {};
    const draftKey = options.draftKey || `${options.kind}:${mode}:${options.ref || "new"}`;
    const draft = drafts[draftKey] ||= {frames: {}};
    const checkpoint = () => {
      for (const frame of frames) frame.pageState?.capture?.();
      context.checkpointTabSession?.();
    };
    window.addEventListener?.("pagehide", checkpoint);
    const dialog = document.createElement("dialog");
    dialog.className = "ft-object-overlay-dialog";
    dialog.dataset.ftTabID = context.tabID || "";
    const card = document.createElement("section");
    card.className = "dialog-card wide object-overlay-card";
    const heading = document.createElement("div");
    heading.className = "ft-page-header ft-object-overlay-header";
    const copy = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = context.t(
      mode === "edit" ? "编辑" : mode === "view" ? "查看" : "新建",
    )
      + context.t(definition.title);
    copy.append(title);
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "dialog-close icon-action-button ft-object-overlay-close";
    closeButton.replaceChildren?.(window.FTIcons?.node?.("xmark") || "×");
    closeButton.title = context.t("关闭");
    closeButton.setAttribute("aria-label", closeButton.title);
    // The shared .dialog-close rule pins top:10px for absolute positioning;
    // this close lives in the header row, so neutralize top inline and keep
    // it as a normal header part (workbench.css also forces relative flow).
    closeButton.style.setProperty("top", "auto", "important");
    const frameActions = document.createElement("div");
    frameActions.className = "toolbar ft-object-overlay-frame-actions";
    heading.append(copy, frameActions, closeButton);
    const body = document.createElement("div");
    body.className = "ft-object-overlay-body";
    const tree = document.createElement("nav");
    tree.className = "ft-object-overlay-tree";
    tree.setAttribute?.("aria-label", context.t("已打开页面"));
    const mount = document.createElement("div");
    mount.className = "ft-object-overlay-mount";
    body.append(tree, mount);
    card.append(heading, body);
    dialog.append(card);
    const state = {
      closed: false,
      resolve: null,
      cleanup: () => {
        for (const frame of frames || []) {
          frame.pageState?.dispose?.();
          frame.mount?.__ftProductGroupCleanup?.();
          frame.mount?.__ftProductCategoryCleanup?.();
        }
        window.removeEventListener?.("pagehide", checkpoint);
        delete drafts[draftKey];
        context.checkpointTabSession?.();
      },
    };
    const finish = value => close(dialog, state, value);
    closeButton.addEventListener("click", () => finish(null));
    dialog.addEventListener("close", () => {
      if (!state.closed) {
        state.closed = true;
        state.cleanup?.();
        state.resolve?.(null);
      }
      dialog.remove();
    }, {once: true});
    document.body.append(dialog);
    dialog.showModal();
    const promise = new Promise(resolve => { state.resolve = resolve; });
    const frames = [{
      id: crypto.randomUUID(),
      kind: options.kind,
      ref: options.ref || "new",
      mode,
      initialValue: options.initialValue || null,
      temporary: options.temporary === true,
    }];
    let renderToken = 0;
    let activeFrame = frames[0];
    const loadedGroups = new Set();
    const expandedFrames = new Set([frames[0].id]);

    const normalizedValue = (frame, value) => frame.temporary === true && value
      ? {...value, temporary: true, source_origin: value.source_origin || "test_inline"}
      : value;

    const childrenOf = parent => frames.filter(frame => frame.parent === parent);
    const isDescendantOf = (candidate, ancestor) => {
      for (let current = candidate?.parent; current; current = current.parent) {
        if (current === ancestor) return true;
      }
      return false;
    };

    const renderTree = () => {
      const renderNode = (frame, depth) => {
        const item = document.createElement("div");
        item.className = "ft-object-overlay-tree-item";
        item.style?.setProperty?.("--tree-depth", String(depth));
        item.classList.toggle("active", frame === activeFrame);
        const children = childrenOf(frame);
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "icon-action-button ft-object-overlay-tree-toggle";
        toggle.hidden = children.length === 0;
        toggle.replaceChildren?.(window.FTIcons?.node?.(
          expandedFrames.has(frame.id) ? "triangle.down" : "triangle.right",
        ) || (expandedFrames.has(frame.id) ? "▾" : "▸"));
        toggle.title = context.t(expandedFrames.has(frame.id) ? "收起" : "展开");
        toggle.addEventListener("click", event => {
          event.preventDefault?.();
          event.stopPropagation?.();
          if (expandedFrames.has(frame.id)) expandedFrames.delete(frame.id);
          else expandedFrames.add(frame.id);
          renderTree();
        });
        const label = document.createElement("button");
        label.type = "button";
        label.className = "ft-object-overlay-tree-label";
        const frameDefinition = definitions[frame.kind];
        label.textContent = frame.label || context.t(frameDefinition.title);
        label.title = label.textContent;
        label.addEventListener("click", () => { void renderFrame(frame); });
        item.append(toggle, label);
        if (frame !== frames[0]) {
          const cancel = document.createElement("button");
          cancel.type = "button";
          cancel.className = "icon-action-button ft-object-overlay-tree-cancel";
          cancel.replaceChildren?.(window.FTIcons?.node?.("xmark") || "×");
          cancel.title = context.t("取消这一层");
          cancel.setAttribute?.("aria-label", context.t("取消这一层"));
          cancel.addEventListener("click", event => {
            event.preventDefault?.();
            event.stopPropagation?.();
            closeFrame(frame);
          });
          item.append(cancel);
        }
        const nodes = [item];
        if (expandedFrames.has(frame.id)) {
          for (const child of children) nodes.push(...renderNode(child, depth + 1));
        }
        return nodes;
      };
      tree.replaceChildren(...renderNode(frames[0], 0));
      tree.hidden = frames.length < 2;
      body.classList.toggle("has-tree", frames.length > 1);
    };

    const closeFrame = frame => {
      if (frame === frames[0]) {
        finish(null);
        return;
      }
      const index = frames.indexOf(frame);
      const removed = frames.filter(candidate => (
        candidate === frame || isDescendantOf(candidate, frame)
      ));
      const removesActive = removed.includes(activeFrame);
      for (const candidate of removed) candidate.resolve?.(null);
      for (const candidate of removed) {
        candidate.pageState?.dispose?.();
        delete draft.frames[candidate.draftKey];
      }
      for (let cursor = frames.length - 1; cursor >= 0; cursor -= 1) {
        if (removed.includes(frames[cursor])) frames.splice(cursor, 1);
      }
      if (removesActive) {
        void renderFrame(frame.parent && frames.includes(frame.parent)
          ? frame.parent : frames[Math.max(0, index - 1)] || frames[0]);
      } else {
        renderTree();
      }
    };

    const saveFrame = (frame, value) => {
      const normalized = normalizedValue(frame, value);
      if (frame === frames[0]) {
        options.onSaved?.(normalized);
        finish(normalized);
        return;
      }
      frame.onSaved?.(normalized);
      frame.resolve?.(normalized);
      frame.pageState?.dispose?.();
      delete draft.frames[frame.draftKey];
      const index = frames.indexOf(frame);
      if (index >= 0) frames.splice(index, 1);
      void renderFrame(frame.parent || frames.at(-1) || frames[0]);
    };

    const updateFrameHeading = (frame, name = "", scope = "") => {
      const frameDefinition = definitions[frame.kind] || definition;
      const prefix = frame.mode === "edit"
        ? context.t("编辑") : frame.mode === "view" ? context.t("查看") : context.t("新建");
      const typeTitle = context.t(frameDefinition.title);
      // Mirror the regular tab header: title + eyebrow (object kind / mode).
      copy.replaceChildren();
      const titleElement = document.createElement("h1");
      titleElement.className = "ft-object-overlay-title";
      const eyebrow = document.createElement("small");
      eyebrow.className = "eyebrow";
      const modeText = `${prefix}${typeTitle}${scope ? ` · ${scope}` : ""}`;
      if (name) {
        titleElement.textContent = String(name);
        eyebrow.textContent = modeText;
      } else {
        titleElement.textContent = modeText;
      }
      heading.dataset.pageMode = frame.mode;
      const eyebrowRow = document.createElement("div");
      eyebrowRow.className = "eyebrow-row";
      eyebrowRow.append(eyebrow);
      if (frame.mode === "edit" || frame.mode === "create") {
        const badge = document.createElement("span");
        badge.className = "page-mode-badge";
        badge.textContent = context.t(frame.mode === "edit" ? "编辑中" : "新建");
        eyebrowRow.append(badge);
      }
      copy.append(eyebrowRow, titleElement);
      frame.label = name || modeText;
      renderTree();
    };

    const renderFrame = async frame => {
      const token = ++renderToken;
      activeFrame = frame;
      const frameDefinition = definitions[frame.kind];
      if (!frameDefinition) return;
      updateFrameHeading(frame);
      frame.mount ||= document.createElement("div");
      frame.mount.className = "ft-object-overlay-frame";
      frame.toolbar ||= document.createElement("div");
      frame.draftKey ||= `${frame.parent?.draftKey || "root"}/${frame.kind}:${frame.mode}:${frame.ref}`;
      frame.pageState ||= window.FTPageState?.create?.({
        durable: draft.frames[frame.draftKey] ||= {},
      });
      frame.toolbar.className = "toolbar ft-object-overlay-frame-toolbar";
      frameActions.replaceChildren(frame.toolbar);
      mount.replaceChildren(frame.mount);
      if (frame.rendered) return;
      const frameOptions = {
        ...options,
        ...frame,
        mode: frame.mode,
        initialValue: frame.initialValue,
        temporary: frame.temporary,
      };
      const proxy = editorContext(
        context, frame.mount, () => closeFrame(frame), value => saveFrame(frame, value), frameOptions, {
          navigate: path => {
            if (frame.kind === "factor_set" && isFactorPath(path)) {
              const targetRef = factorRefFromPath(path);
              if (targetRef) {
                openFactor({ref: targetRef, alias: targetRef});
                return;
              }
            }
            finish(null);
          },
          openFactor,
          openObject,
          closeFrame: () => closeFrame(frame),
          toolbar: frame.toolbar,
          pageState: frame.pageState,
          setHeading: (name, scope) => {
            updateFrameHeading(frame, name, scope);
          },
          // The page's shared edit action (object-mode-actions) raises the
          // request here; the overlay opens the editor as a nested frame
          // seeded with the temporary value, and the save lands back on the
          // same in-place object through options.onSaved.  The overlay keeps
          // only frame management — it never fabricates its own actions.
          openInlineEdit: () => {
            if (frame.mode !== "view" || frame.temporary !== true) return;
            openObject({
              kind: frame.kind,
              ref: frame.ref,
              mode: "edit",
              initialValue: frame.initialValue || null,
              temporary: true,
              onSaved: value => {
                const next = normalizedValue(frame, value);
                frame.initialValue = next;
                frame.rendered = false;
                frame.mount.replaceChildren();
                frame.label = undefined;
                options.onSaved?.(next);
              },
            });
          },
        },
      );
      try {
        if (!loadedGroups.has(frameDefinition.load)) {
          await window.FTStaticLoader?.loadGroups?.([frameDefinition.load]);
          loadedGroups.add(frameDefinition.load);
        }
        if (state.closed || token !== renderToken) return;
        frame.rendered = true;
        await frameDefinition.render(proxy, frame.ref, frame.mode, frameOptions);
      } catch (error) {
        if (!state.closed && token === renderToken) {
          frame.mount.replaceChildren(window.FTUI.empty(
            context.t("读取失败"), error.message || context.t("请稍后重试"),
          ));
        }
      }
    };

    const openFactor = item => {
      const targetRef = String(item?.ref || "").trim();
      if (!targetRef) return;
      const initialValue = factorInitialValue(item, targetRef);
      frames.push({
        id: crypto.randomUUID(), parent: activeFrame,
        kind: "factor", ref: targetRef, mode: "view",
        initialValue, temporary: Boolean(initialValue),
      });
      expandedFrames.add(activeFrame.id);
      void renderFrame(frames.at(-1));
    };

    const openObject = childOptions => {
      const childDefinition = definitions[childOptions?.kind];
      if (!childDefinition) {
        return Promise.reject(new Error(`unsupported test object: ${childOptions?.kind}`));
      }
      let resolve;
      const promise = new Promise(done => { resolve = done; });
      const child = {
        id: crypto.randomUUID(), parent: activeFrame,
        kind: childOptions.kind,
        ref: childOptions.ref || "new",
        mode: childOptions.mode || "create",
        initialValue: childOptions.initialValue || null,
        temporary: childOptions.temporary === true,
        onSaved: childOptions.onSaved,
        resolve,
      };
      frames.push(child);
      expandedFrames.add(activeFrame.id);
      void renderFrame(child);
      return promise;
    };

    await renderFrame(frames[0]);
    return promise;
  }

  function isFactorPath(path) {
    return /^\/factors\/factor\//.test(String(path || ""));
  }

  function factorRefFromPath(path) {
    const match = /^\/factors\/factor\/(.+?)(?:\?|$)/.exec(String(path || ""));
    if (!match) return "";
    try { return decodeURIComponent(match[1]); } catch (_) { return match[1]; }
  }

  function factorInitialValue(item, targetRef) {
    if (!item || typeof item !== "object") return null;
    const frozen = String(targetRef).startsWith("factor:v2:");
    const hasSource = [
      "family_formula_fingerprint", "self_formula_fingerprint",
      "source_code", "math_expr",
      "formula", "latex", "factor_params", "params",
    ].some(key => item[key] !== undefined && item[key] !== null);
    if (!hasSource) return null;
    const identity = frozen
      ? window.FTFactorModel?.frozenFactorIdentity?.(item)
      : null;
    return {
      ...item,
      ref: targetRef,
      ...(identity ? {
        alias: identity.alias,
        factor_family_alias: item.factor_family_alias || identity.family,
        factor_owner_ref: item.factor_owner_ref || identity.ownerRef,
        factor_params: item.factor_params || identity.params,
      } : {}),
    };
  }

  window.FTObjectOverlay = Object.freeze({open});
})();
