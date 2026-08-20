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
      title: "因子候选",
      load: "catalog",
      render: (context, ref) => FTFactors.setDetail(context, ref),
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

  function editorContext(context, mount, closeOverlay, onSaved, options = {}) {
    const toolbar = document.createElement("div");
    return {
      ...context,
      content: mount,
      toolbar,
      setHeading: () => {},
      updateActiveTab: () => {},
      activeNav: () => {},
      navigate: () => closeOverlay(),
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
    heading.append(copy, closeButton);
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
    const proxy = editorContext(context, mount, () => finish(null), saved, options);
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
    try {
      await window.FTStaticLoader?.loadGroups?.([definition.load]);
      if (state.closed) return promise;
      await definition.render(proxy, options.ref || "new", mode, options);
    } catch (error) {
      if (!state.closed) {
        mount.replaceChildren(FTUI.empty(
          context.t("读取失败"), error.message || context.t("请稍后重试"),
        ));
      }
    }
    return promise;
  }

  window.FTTestObjectEditorOverlay = Object.freeze({open});
})();
