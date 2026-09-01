(() => {
  const definitions = {
    factor: {
      title: "因子",
      load: "factor-catalog-detail-rendering",
      // The embedded editor is deliberately the catalog component itself.
      // The overlay context supplies its mount and onSaved callback, so the
      // catalog create/edit/view behavior is identical to the left-nav tab.
      render: (context, ref, mode) => FTFactors.factorDetail(context, ref, mode),
    },
    factor_set: {
      title: "因子集合",
      load: "factor-catalog-detail",
      render: (context, ref, mode, options) => (
        FTFactors.setDetail(context, ref, mode, options)
      ),
    },
    product_group: {
      title: "产品组",
      load: "catalog",
      render: (context, ref, mode) => FTProducts.groupDetail(context, ref, mode),
    },
    category: {
      title: "产品分类",
      load: "catalog",
      render: (context, ref, mode) => FTProducts.categoryDetail(context, ref, mode),
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
    const toolbar = document.createElement("div");
    return {
      ...context,
      content: mount,
      toolbar,
      setHeading: callbacks.setHeading || (() => {}),
      updateActiveTab: () => {},
      activeNav: () => {},
      navigate: callbacks.navigate || (() => closeOverlay()),
      openFactor: callbacks.openFactor,
      openTestObject: callbacks.openTestObject,
      closeTab: callbacks.closeFrame || (() => closeOverlay()),
      onSaved,
      testState: options.testState || null,
      testObjectTemporary: options.temporary === true,
      testObjectSnapshot: options.snapshot === true,
      testObjectInitialValue: options.initialValue || null,
      testObjectViewOnly: options.mode === "view",
      isRouteCurrent: () => context.isRouteCurrent?.() !== false,
    };
  }

  async function open(context, options = {}) {
    const definition = definitions[options.kind];
    if (!definition) throw new Error(`unsupported test object: ${options.kind}`);
    const mode = ["create", "edit", "view"].includes(options.mode)
      ? options.mode : "create";
    const dialog = document.createElement("dialog");
    dialog.className = "test-object-editor-dialog";
    dialog.dataset.ftTabID = context.tabID || "";
    const card = document.createElement("section");
    card.className = "dialog-card wide test-object-editor-overlay";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = context.t(
      mode === "edit" ? "编辑" : mode === "view" ? "查看" : "新建",
    )
      + context.t(definition.title);
    copy.append(title);
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "dialog-close icon-action-button test-object-editor-close";
    closeButton.replaceChildren?.(window.FTIcons?.node?.("xmark") || "×");
    closeButton.title = context.t("关闭");
    const backButton = document.createElement("button");
    backButton.type = "button";
    backButton.className = "icon-action-button test-object-editor-back";
    backButton.replaceChildren?.(window.FTIcons?.node?.("chevron.left") || "‹");
    backButton.title = context.t("返回上一层");
    backButton.setAttribute?.("aria-label", context.t("返回上一层"));
    backButton.hidden = true;
    const tabBar = document.createElement("div");
    tabBar.className = "test-object-editor-tabs";
    heading.append(backButton, copy, tabBar, closeButton);
    const mount = document.createElement("div");
    mount.className = "test-object-editor-overlay-mount";
    card.append(heading, mount);
    dialog.append(card);
    const state = {
      closed: false,
      resolve: null,
      cleanup: () => {
        for (const frame of frames || []) {
          frame.mount?.__ftProductGroupCleanup?.();
          frame.mount?.__ftProductCategoryCleanup?.();
        }
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

    const normalizedValue = (frame, value) => frame.temporary === true && value
      ? {...value, temporary: true, source_origin: value.source_origin || "test_inline"}
      : value;

    const renderTabs = () => {
      tabBar.replaceChildren(...frames.map((frame, index) => {
        const item = document.createElement("span");
        item.className = "test-object-editor-tab";
        item.classList.toggle("active", frame === activeFrame);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "test-object-editor-tab-label";
        const definition = definitions[frame.kind];
        button.textContent = frame.label || `${context.t(definition.title)} ${index + 1}`;
        button.addEventListener("click", () => { void renderFrame(frame); });
        item.append(button);
        if (frame !== frames[0]) {
          const cancel = document.createElement("button");
          cancel.type = "button";
          cancel.className = "icon-action-button test-object-editor-tab-cancel";
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
        return item;
      }));
      tabBar.hidden = frames.length < 2;
    };

    const closeFrame = frame => {
      if (frame === frames[0]) {
        finish(null);
        return;
      }
      const index = frames.indexOf(frame);
      const wasActive = frame === activeFrame;
      if (index >= 0) frames.splice(index, 1);
      frame.resolve?.(null);
      if (wasActive) {
        void renderFrame(frame.parent && frames.includes(frame.parent)
          ? frame.parent : frames[Math.max(0, index - 1)] || frames[0]);
      } else {
        renderTabs();
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
      const index = frames.indexOf(frame);
      if (index >= 0) frames.splice(index, 1);
      void renderFrame(frame.parent || frames.at(-1) || frames[0]);
    };

    const updateFrameHeading = (frame, name = "") => {
      const frameDefinition = definitions[frame.kind] || definition;
      const prefix = frame.mode === "edit"
        ? context.t("编辑") : frame.mode === "view" ? context.t("查看") : context.t("新建");
      title.textContent = prefix + context.t(frameDefinition.title);
      frame.label = name || `${prefix}${context.t(frameDefinition.title)}`;
      if (name && frame.kind === "factor") title.title = name;
      backButton.hidden = frame === frames[0];
      renderTabs();
    };

    const renderFrame = async frame => {
      const token = ++renderToken;
      activeFrame = frame;
      const frameDefinition = definitions[frame.kind];
      if (!frameDefinition) return;
      updateFrameHeading(frame);
      frame.mount ||= document.createElement("div");
      frame.mount.className = "test-object-editor-frame";
      mount.replaceChildren(frame.mount);
      if (frame.rendered) return;
      frame.rendered = true;
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
          openTestObject,
          closeFrame: () => closeFrame(frame),
          setHeading: (name, scope) => {
            updateFrameHeading(frame, name);
          },
        },
      );
      try {
        if (!loadedGroups.has(frameDefinition.load)) {
          await window.FTStaticLoader?.loadGroups?.([frameDefinition.load]);
          loadedGroups.add(frameDefinition.load);
        }
        if (state.closed || token !== renderToken) return;
        await frameDefinition.render(proxy, frame.ref, frame.mode, frameOptions);
      } catch (error) {
        if (!state.closed && token === renderToken) {
          frame.mount.replaceChildren(FTUI.empty(
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
      void renderFrame(frames.at(-1));
    };

    const openTestObject = childOptions => {
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
      void renderFrame(child);
      return promise;
    };

    backButton.addEventListener("click", () => {
      if (activeFrame === frames[0]) return;
      void renderFrame(activeFrame.parent || frames[0]);
    });
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

  window.FTTestObjectEditorOverlay = Object.freeze({open});
})();
