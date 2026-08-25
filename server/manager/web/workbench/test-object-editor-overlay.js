(() => {
  const definitions = {
    factor: {
      title: "因子",
      load: "catalog",
      // The embedded editor is deliberately the catalog component itself.
      // The overlay context supplies its mount and onSaved callback, so the
      // catalog create/edit/view behavior is identical to the left-nav tab.
      render: (context, ref, mode) => FTFactors.factorDetail(context, ref, mode),
    },
    factor_set: {
      title: "因子集合",
      load: "catalog",
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
      closeTab: () => closeOverlay(),
      onSaved,
      testState: options.testState || null,
      testObjectTemporary: options.temporary === true,
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
    if (mode !== "view") {
      const note = document.createElement("p");
      note.textContent = context.t("保存后返回当前测试，并立即更新候选列表");
      copy.append(title, note);
    } else {
      copy.append(title);
    }
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "dialog-close";
    closeButton.textContent = "×";
    closeButton.title = context.t("关闭");
    const backButton = document.createElement("button");
    backButton.type = "button";
    backButton.className = "secondary test-object-editor-back";
    backButton.textContent = context.t("返回");
    backButton.title = context.t("返回因子集合");
    backButton.hidden = true;
    heading.append(backButton, copy, closeButton);
    const mount = document.createElement("div");
    mount.className = "test-object-editor-overlay-mount";
    card.append(heading, mount);
    dialog.append(card);
    const state = {
      closed: false,
      resolve: null,
      cleanup: () => {
        mount.__ftProductGroupCleanup?.();
        mount.__ftProductCategoryCleanup?.();
      },
    };
    const finish = value => close(dialog, state, value);
    const saved = value => {
      const normalized = options.temporary === true && value
        ? {...value, temporary: true, source_origin: value.source_origin || "test_inline"}
        : value;
      options.onSaved?.(normalized);
      finish(normalized);
    };
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
      kind: options.kind,
      ref: options.ref || "new",
      mode,
      initialValue: options.initialValue || null,
      temporary: options.temporary === true,
    }];
    let renderToken = 0;
    let loadedGroups = false;

    const updateFrameHeading = (frame, name = "") => {
      const frameDefinition = definitions[frame.kind] || definition;
      const prefix = frame.mode === "edit"
        ? context.t("编辑") : frame.mode === "view" ? context.t("查看") : context.t("新建");
      title.textContent = prefix + context.t(frameDefinition.title);
      if (name && frame.kind === "factor") title.title = name;
      backButton.hidden = frames.length < 2;
    };

    const renderFrame = async frame => {
      const token = ++renderToken;
      const frameDefinition = definitions[frame.kind];
      if (!frameDefinition) return;
      updateFrameHeading(frame);
      mount.replaceChildren();
      const frameOptions = {
        ...options,
        ...frame,
        mode: frame.mode,
        initialValue: frame.initialValue,
        temporary: frame.temporary,
      };
      const proxy = editorContext(
        context, mount, () => finish(null), saved, frameOptions, {
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
          setHeading: (name, scope) => {
            updateFrameHeading(frame, name);
          },
        },
      );
      try {
        if (!loadedGroups) {
          await window.FTStaticLoader?.loadGroups?.([frameDefinition.load]);
          loadedGroups = true;
        }
        if (state.closed || token !== renderToken) return;
        await frameDefinition.render(proxy, frame.ref, frame.mode, frameOptions);
      } catch (error) {
        if (!state.closed && token === renderToken) {
          mount.replaceChildren(FTUI.empty(
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
        kind: "factor", ref: targetRef, mode: "view",
        initialValue, temporary: Boolean(initialValue),
      });
      void renderFrame(frames.at(-1));
    };

    backButton.addEventListener("click", () => {
      if (frames.length < 2) return;
      frames.pop();
      void renderFrame(frames.at(-1));
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
