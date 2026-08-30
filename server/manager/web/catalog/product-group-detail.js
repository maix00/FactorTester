(() => {
  function current(context) {
    return context.isCurrent?.() !== false;
  }

  function modeOf(target, requestedMode = "") {
    const requested = requestedMode || new URLSearchParams(location.search).get("mode");
    if (target === "new") return "create";
    return requested === "edit" ? "edit" : "view";
  }

  function endpoint(source, target = "") {
    const base = source === "local"
      ? "/api/client/product-groups" : "/api/catalog/product-groups";
    return target ? `${base}/${encodeURIComponent(target)}` : base;
  }

  function groupPath(group) {
    return group?.group_ref || group?.id || group?.name || "";
  }

  function categoryTitle(category, context) {
    return String(
      category?.title_zh || category?.alias || category?.id || context.t("分类"),
    );
  }

  function categoryPicker(context, categories, selected, editable, onChange) {
    const section = document.createElement("section");
    section.className = "product-group-category-picker";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("绑定的产品分类"),
    }));
    const note = document.createElement("p");
    note.className = "product-group-category-note";
    note.textContent = editable
      ? context.t("请选择一个或多个产品分类；正路径和负路径将在这些分类下解析")
      : context.t("产品组的路径在绑定的产品分类下解析");
    section.append(note);
    const picker = FTMultiSelectFilter.create(context, {
      title: context.t("绑定的产品分类"),
      items: (categories || []).map(category => ({
        value: category.id,
        label: categoryTitle(category, context),
        description: category.id,
      })),
      selected: [...selected],
      multi: true,
      disabled: !editable,
      onChange: values => {
        selected.clear(); values.forEach(value => selected.add(value)); onChange?.();
      },
    });
    if (!(categories || []).length) {
      section.append(FTUI.empty(context.t("暂无可用产品分类"), ""));
    } else {
      section.append(picker.element);
    }
    return section;
  }

  function metadata(context, group, categories) {
    const bindings = Array.isArray(group?.category_bindings)
      ? group.category_bindings : (group?.category_ids || []).map(id => ({id}));
    const rows = [
      [context.t("稳定引用"), group?.group_ref || group?.id || "—"],
      [context.t("创建者"), group?.creator_title || group?.creator_ref || "—"],
      [context.t("分类"), bindings.map(item => categoryTitle(
        categories.find(category => category.id === item.id) || item, context,
      )).join("、") || context.t("未绑定分类")],
      [context.t("产品数量"), String(group?.product_count ?? group?.products?.length ?? 0)],
      [context.t("路径数量"), String(group?.path_count ?? group?.paths?.length ?? 0)],
    ];
    const section = document.createElement("section");
    section.className = "product-group-metadata";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("产品组信息"),
    }), FTUI.table([context.t("字段"), context.t("值")], rows).shell);
    return section;
  }

  function productsSection(context, group) {
    const section = document.createElement("section");
    section.className = "product-group-resolved-products";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("解析后的产品"),
    }));
    const products = Array.isArray(group?.products) && group.products.length
      ? group.products
      : (group?.product_names || []).map(name => ({
          product_ref: name, display_name: name, available: true,
        }));
    const limit = 50;
    let page = 1;
    const mount = document.createElement("div");
    const renderPage = () => {
      const totalPages = Math.max(1, Math.ceil(products.length / limit));
      page = Math.min(page, totalPages);
      const rows = products.slice((page - 1) * limit, page * limit);
      mount.replaceChildren(rows.length
        ? FTUI.table(
            [context.t("产品"), context.t("说明"), context.t("可用性"), context.t("数据源")],
            rows.map(item => [
              item.display_name || item.name || item.product_ref || "—",
              item.desc || item.description || "—",
              item.available === false ? context.t("不可用") : context.t("可用"),
              Array.isArray(item.source_ids) ? item.source_ids.join("、") : "—",
            ]),
          ).shell
        : FTUI.empty(context.t("暂无解析产品"), context.t("请先配置正路径")));
      if (products.length > limit) {
        const pager = document.createElement("div");
        pager.className = "product-group-products-pager";
        const previous = FTUI.actionButton(context.t("上一页"), () => {
          page -= 1; renderPage();
        }, {variant: "secondary"});
        const next = FTUI.actionButton(context.t("下一页"), () => {
          page += 1; renderPage();
        }, {variant: "secondary"});
        previous.disabled = page <= 1;
        next.disabled = page >= totalPages;
        pager.append(previous, Object.assign(document.createElement("span"), {
          textContent: `${page} / ${totalPages}`,
        }), next);
        mount.append(pager);
      }
    };
    renderPage();
    section.append(mount);
    return section;
  }

  function actionButton(context, label, handler, variant = "secondary") {
    return FTCatalogDetailUI.action(context, label, handler, variant);
  }

  async function render(context, target, helpers, requestedMode = "") {
    context.content.__ftProductGroupCleanup?.();
    delete context.content.__ftProductGroupCleanup;
    const source = helpers.sourceOf();
    const mode = modeOf(target, requestedMode);
    context.activeNav("products");
    helpers.catalogSwitch(context, "groups", source);
    context.content.replaceChildren(FTUI.loading(context.t("正在读取产品组…")));
    if (mode === "create" && !context.session) {
      throw new Error(context.t("访客模式只能查看产品组"));
    }
    let group = null;
    if (mode !== "create") {
      if (context.testObjectTemporary && context.testObjectInitialValue) {
        group = context.testObjectInitialValue;
      } else {
        const value = await context.api(endpoint(source, target));
        if (!current(context)) return;
        group = value.group;
      }
      if (!group) throw new Error(context.t("产品组不存在"));
    }
    const inlineView = mode === "view"
      && context.testObjectTemporary
      && context.testObjectInitialValue;
    const categoryPayload = inlineView
      ? {categories: []}
      : await helpers.loadCategories(context, source);
    if (!current(context)) return;
    const categories = [...(Array.isArray(categoryPayload.categories)
      ? categoryPayload.categories : [])];
    // A test editor may create a category in its mounted Category tab before
    // opening this overlay.  Keep that temporary catalog available to the
    // product-tree picker without writing it a second time or hiding it
    // behind the server catalog cache.
    const transientCategories = context.testState?.values?.category_candidates;
    for (const category of transientCategories || []) {
      const id = String(category?.id || category?.category_id || "").trim();
      if (!id || categories.some(item => String(item?.id || "") === id)) continue;
      categories.push({...category, id});
    }
    const title = group?.name || (mode === "create"
      ? context.t("新增产品组") : target);
    context.setHeading(title, context.t("产品组"));
    context.updateActiveTab?.({title});
    const editable = !context.testObjectViewOnly
      && Boolean(context.session) && source === "server";
    if (mode === "edit" && !editable) {
      throw new Error(context.t("当前产品组不可编辑"));
    }
    const creating = mode === "create";
    const editing = creating || mode === "edit";
    const selected = new Set(
      (group?.category_ids || []).map(value => String(value)),
    );
    let draftPaths = Array.isArray(group?.selection_paths)
      ? group.selection_paths.slice()
      : (group?.paths || []).slice();
    let pathEditor = null;

    const root = document.createElement("section");
    root.className = "detail-stack product-group-detail-page";
    const surface = editing ? document.createElement("form") : document.createElement("div");
    surface.className = "product-group-detail-surface";
    if (editing) surface.noValidate = true;
    const headerValue = FTCatalogDetailUI.header(context, {
      title,
      editing,
      creating,
      canEdit: editable,
      onBack: () => context.navigate(helpers.pathFor("/products/groups", source)),
      onCancel: () => {
        if (creating) {
          context.closeTab?.(context.tabID);
          context.navigate(helpers.pathFor("/products/groups", source));
        } else {
          context.navigate(helpers.pathFor(
            `/products/group/${encodeURIComponent(groupPath(group))}`, source,
          ));
        }
      },
      onEdit: () => context.navigate(helpers.pathFor(
        `/products/group/${encodeURIComponent(groupPath(group))}?mode=edit`, source,
      )),
      onDelete: async () => {
        if (!window.confirm(context.t("确认删除该产品组？"))) return;
        try {
          await context.api(endpoint(source, groupPath(group)), {method: "DELETE"});
          context.closeTab?.(context.tabID);
          context.navigate(helpers.pathFor(
            `/products/groups?updated=${Date.now()}`, source,
          ));
        } catch (error) {
          context.showNotice?.(error.message || context.t("产品组删除失败"), true);
        }
      },
    });
    const header = headerValue.root;
    const save = headerValue.save;
    if (save) save.dataset.productGroupSave = "true";
    surface.append(header, helpers.sourceSummary(context));

    const nameField = document.createElement("label");
    nameField.className = "test-object-field product-group-name-field";
    nameField.append(Object.assign(document.createElement("b"), {
      textContent: context.t("产品组名称"),
    }));
    const nameInput = document.createElement("input");
    nameInput.value = group?.name || "";
    nameInput.required = editing;
    nameInput.readOnly = !editing;
    nameInput.placeholder = context.t("例如：日盘主力产品组");
    nameField.append(nameInput);
    surface.append(nameField);
    if (group) surface.append(metadata(context, group, categories));

    const categoryMount = document.createElement("div");
    const pathMount = document.createElement("div");
    pathMount.className = "product-group-path-editor-mount";
    const renderPathEditor = () => {
      pathEditor?.dispose();
      pathMount.replaceChildren();
      pathEditor = window.FTProductGroupPathEditor.render(context, helpers, {
        source,
        categories,
        categoryIDs: [...selected],
        group: {selection_paths: draftPaths},
        editable: editing,
        onChange: () => { draftPaths = pathEditor?.paths() || draftPaths; },
      });
      pathMount.append(pathEditor.root);
    };
    categoryMount.append(categoryPicker(
      context, categories, selected, editing, () => {
        if (editing) {
          draftPaths = pathEditor?.paths() || draftPaths;
          renderPathEditor();
        }
      },
    ));
    surface.append(categoryMount);
    renderPathEditor();
    surface.append(pathMount);
    if (group) surface.append(productsSection(context, group));
    const status = document.createElement("small");
    status.className = "product-group-form-status";
    surface.append(status);
    root.append(surface);
    context.content.__ftProductGroupCleanup = () => {
      pathEditor?.dispose();
      pathMount.replaceChildren();
    };
    context.content.replaceChildren(root);
    nameInput.addEventListener("input", () => {
      if (creating) context.updateActiveTab?.({
        title: nameInput.value.trim() || context.t("新增产品组"),
      });
    });
    if (editing) {
      surface.addEventListener("submit", async event => {
        event.preventDefault();
        const paths = pathEditor?.paths() || draftPaths;
        draftPaths = paths;
        if (!selected.size) {
          status.textContent = context.t("产品组至少需要绑定一个产品分类");
          return;
        }
        const positive = paths.filter(path => !String(path).startsWith("-"));
        if (!positive.length) {
          status.textContent = context.t("正路径至少需要一个产品路径");
          return;
        }
        const save = surface.querySelector("[data-product-group-save]");
        save.disabled = true;
        status.textContent = "";
        try {
          const payload = {
            name: nameInput.value.trim(),
            category_ids: [...selected],
            paths,
          };
          const localID = groupPath(group) || `inline-product-group:${payload.name}`;
          const selectedSources = window.FTStrategyEditorScope?.selectedSourceIDs?.(
            context.testState,
          ) || [];
          const value = context.testObjectTemporary
            ? {group: {
              ...payload,
              id: localID,
              group_ref: localID,
              product_group_template_id: localID,
              product_path_selection_id: localID,
              title_zh: payload.name,
              selected_paths: [...paths],
              temporary: true,
              source_kind: "transient",
              source_origin: "test_inline",
              source_ids: selectedSources,
              path_sources: positive.map(path => ({
                path, source_ids: [...selectedSources],
              })),
            }}
            : await context.api(
              creating ? endpoint(source) : endpoint(source, groupPath(group)),
              {method: creating ? "POST" : "PUT", body: JSON.stringify(payload)},
            );
          if (context.onSaved) {
            context.onSaved(value.group || value);
            return;
          }
          if (FTTabReturn.returnToSource(context, {
            kind: "product_group",
            ref: String(value.group?.group_ref || value.group?.id || ""),
          })) return;
          if (creating) {
            context.closeTab?.(context.tabID);
            context.navigate(helpers.pathFor(
              `/products/groups?updated=${Date.now()}`, source,
            ));
          } else {
            context.navigate(helpers.pathFor(
              `/products/group/${encodeURIComponent(groupPath(value.group || group))}?mode=edit&updated=${Date.now()}`,
              source,
            ));
          }
        } catch (error) {
          status.textContent = error.message || context.t("产品组保存失败");
          save.disabled = false;
        }
      });
    }
    return root;
  }

  window.FTProductGroupDetail = Object.freeze({render});
})();
