(() => {
  function render(context, helpers, options = {}) {
    const category = options.category || null;
    const source = options.source || "server";
    const mode = options.mode || "view";
    const creating = !category;
    const editing = creating || mode === "edit";
    const sourceManaged = category?.source_managed === true;
    const composite = category?.is_composite === true;
    const canEdit = options.canEdit === true;
    const policy = category?.editability || {};
    const titleEditable = editing && canEdit
      && (policy.category_title === true || (!sourceManaged && !composite)
        || (sourceManaged && policy.category_title === "super_admin"));
    const labelsEditable = editing && canEdit
      && (policy.label_title === true || (!sourceManaged && !composite));
    const pathsEditable = editing && canEdit
      && (policy.label_paths === true || (!sourceManaged && !composite));
    const labels = Array.isArray(category?.items) ? category.items : [];
    const treeState = {
      activeRow: null,
    };

    const root = document.createElement("section");
    root.className = "detail-stack product-category-detail-page";
    const surface = editing ? document.createElement("form") : document.createElement("div");
    surface.className = "product-category-detail-surface";
    if (editing) surface.noValidate = true;

    const headingText = creating
      ? context.t("新增分类")
      : category.title_zh || category.alias || category.id;
    const categoryViewURL = category
      ? helpers.pathFor(
        `/products/categories/${encodeURIComponent(category.id)}`, source,
      )
      : "";
    // Standalone pages own their authoring actions in the global top header
    // (shared mode component); overlays keep the in-dialog header actions.
    const globalHeader = !context.testObjectOverlay;
    let save = null;
    if (globalHeader) {
      if (editing) {
        const actions = window.FTObjectModeActions?.mount?.(context, {
          mode: creating ? "create" : "edit",
          viewHref: creating ? "" : categoryViewURL,
          onCancel: () => {
            if (category) {
              context.navigate(categoryViewURL);
            } else {
              context.closeTab?.(context.tabID);
              context.navigate(helpers.pathFor("/products/categories", source));
            }
          },
          onSave: () => surface.requestSubmit(),
        }) || [];
        save = actions[actions.length - 1];
      } else if (canEdit && category) {
        // Same-tab authoring: the edit URL derives from the current location.
        window.FTObjectModeActions?.mount?.(context, {
          mode: "view",
          onEdit: true,
          editLabel: "编辑",
          editHelp: "编辑产品分类",
        });
      }
    }
    const headerValue = FTCatalogDetailUI.header(context, {
      title: headingText,
      // Standalone pages: authoring actions live in the global top header,
      // and there is no list-back button — tabs are the navigation surface.
      editing: globalHeader ? false : editing,
      creating,
      canEdit: globalHeader ? false : canEdit,
      onBack: undefined,
      onCancel: globalHeader ? undefined : () => {
        if (category) {
          context.navigate(categoryViewURL);
        } else {
          context.closeTab?.(context.tabID);
          context.navigate(helpers.pathFor("/products/categories", source));
        }
      },
      onEdit: globalHeader ? undefined : () => context.navigate(
        helpers.pathFor(
          `/products/categories/${encodeURIComponent(category.id)}?mode=edit`,
          source,
        ),
      ),
    });
    const header = headerValue.root;
    if (!save) save = headerValue.save;
    if (save) save.dataset.categorySave = "true";
    if (category && canEdit && policy.delete !== false && !sourceManaged) {
      header.append(options.deleteButton?.());
    }
    if (category?.is_composite && canEdit && policy.refresh !== false) {
      header.append(options.refreshButton?.(editing ? "edit" : "view"));
    }
    surface.append(header);
    if (options.sourceSummary) surface.append(options.sourceSummary());

    const layout = document.createElement("div");
    layout.className = "product-category-detail-layout";
    const main = document.createElement("div");
    main.className = "product-category-detail-main";
    const titleField = identitySection(context, category, {
      creating, titleEditable, sourceManaged, composite,
    });
    main.append(titleField.section);
    const titleInput = titleField.input;
    if (category) main.append(categoryInfo(context, category));
    if (category) appendSourceSection(context, main, category, options);
    if (category?.parent_category_ids?.length) {
      main.append(parentSection(context, category));
    }

    const labelView = window.FTProductCategoryLabels.render(
      context, category, treeState, {
        creating, labels, labelsEditable, pathsEditable,
        removable: editing && canEdit
          && (policy.label_remove === true || (!sourceManaged && !composite)),
        editability: policy,
        renderTree: options.renderTree,
      },
    );
    main.append(labelView.section);
    layout.append(main);
    surface.append(layout);

    const status = document.createElement("small");
    status.className = "product-category-form-error";
    status.dataset.categoryFormStatus = "true";
    surface.append(status);
    root.append(surface);
    const previousCleanup = context.content.__ftProductCategoryCleanup;
    previousCleanup?.();
    const cleanup = () => labelView.dispose();
    context.content.__ftProductCategoryCleanup = cleanup;
    context.content.replaceChildren(root);

    titleInput.addEventListener("input", () => {
      if (!category) {
        context.updateActiveTab?.({title: titleInput.value.trim() || context.t("新增分类")});
      }
    });
    if (editing) {
      surface.addEventListener("submit", async event => {
        event.preventDefault();
        const save = surface.querySelector("[data-category-save]");
        const items = sourceManaged ? undefined : labelView.items();
        const validation = window.FTProductCategoryLabels.validate(
          context, items, creating,
        );
        if (validation) {
          status.textContent = validation;
          return;
        }
        save.disabled = true;
        status.textContent = "";
        labelView.dispose();
        try {
          await options.onSave({
            name: titleInput.value.trim(),
            ...(sourceManaged ? {} : {items}),
          });
        } catch (error) {
          status.textContent = error.message || context.t("产品分类保存失败");
          save.disabled = false;
        }
      });
    }
    return root;
  }

  function identitySection(context, category, options) {
    const section = document.createElement("section");
    section.className = "product-category-identity-section";
    const fields = document.createElement("div");
    fields.className = "product-category-identity-fields";
    if (category) fields.append(readonlyField(context, "分类 ID", category.id));
    const field = document.createElement("label");
    field.className = "test-object-field";
    const label = document.createElement("b");
    label.textContent = context.t("分类名称");
    const input = document.createElement("input");
    input.required = true;
    input.value = category?.title_zh || category?.alias || "";
    input.placeholder = context.t("例如：中国期货日夜盘");
    input.readOnly = options.titleEditable !== true;
    input.dataset.categoryTitle = "true";
    field.append(label, input);
    fields.append(field);
    const note = document.createElement("small");
    note.className = "product-category-editor-note";
    note.textContent = options.creating
      ? context.t("产品分类只能保存具体的正产品路径；产品组才支持负路径或分类引用")
      : options.sourceManaged
        ? context.t("数据源分类的 ID 与产品路径由服务器固定提供，仅超级管理员可以修改标题")
        : options.composite
          ? context.t("乘积分类的标题与产品路径由父分类快照决定，只能修改 Label 标题")
          : context.t("产品分类只能保存具体的正产品路径；产品组才支持负路径或分类引用");
    section.append(fields, note);
    return {section, input};
  }

  function readonlyField(context, labelText, value) {
    const field = document.createElement("label");
    field.className = "test-object-field";
    const label = document.createElement("b");
    label.textContent = context.t(labelText);
    const input = document.createElement("input");
    input.value = value || "";
    input.readOnly = true;
    input.tabIndex = -1;
    field.append(label, input);
    return field;
  }

  function categoryInfo(context, category) {
    return FTUI.table(
      [context.t("字段"), context.t("值")],
      [
        [context.t("分类类型"), category.source_managed
          ? context.t("数据源分类")
          : category.is_composite ? context.t("乘积分类") : context.t("用户分类")],
        [context.t("分类维度"), (category.dimensions || []).join(" × ") || "—"],
        [context.t("所有者"), category.source_managed
          ? context.t("数据源") : category.owner_ref || context.t("当前用户")],
      ],
    ).shell;
  }

  function sourceSection(context, category, sources, options = {}) {
    const section = document.createElement("section");
    section.className = "product-category-source-section";
    section.append(Object.assign(document.createElement("h2"), {
      textContent: context.t("绑定的数据源"),
    }));
    const ids = Array.isArray(category.source_ids) && category.source_ids.length
      ? category.source_ids
      : FTProductCategoryModel.sourceIDsForPaths(
        (category.items || []).flatMap(item => item.paths || []), sources,
      );
    const rows = ids.map(id => {
      const source = sources.find(item => String(
        item.id || item.family_id || item.bundle_id || "",
      ) === String(id));
      const family = document.createElement("a");
      family.className = "catalog-source-family-link";
      family.textContent = source?.family_name || source?.bundle_name
        || source?.source_name || id || "—";
      if (source && options.sourceFamilyPath) {
        family.href = options.sourceFamilyPath(
          source.family_id || source.bundle_id || source.id, options.source,
        );
        family.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation();
          context.navigate(family.href);
        });
      }
      return [
        family,
        providerServers(source, context),
        source?.status || context.t("已登记"),
      ];
    });
    section.append(rows.length
      ? FTUI.table([context.t("数据源族"), context.t("提供服务器"), context.t("状态")], rows).shell
      : FTUI.empty(context.t("暂无绑定数据源"), context.t("该分类没有声明数据源绑定")));
    return section;
  }

  function appendSourceSection(context, main, category, options) {
    if (Array.isArray(options.sources)) {
      main.append(sourceSection(context, category, options.sources, options));
      return;
    }
    const mount = document.createElement("section");
    mount.className = "product-category-source-section";
    mount.append(FTUI.loading(context.t("正在读取绑定的数据源…")));
    main.append(mount);
    if (!options.loadSources) return;
    Promise.resolve(options.loadSources()).then(sources => {
      if (!helpersAreCurrent(context)) return;
      mount.replaceWith(sourceSection(context, category, sources || [], options));
    }).catch(error => {
      if (!helpersAreCurrent(context)) return;
      mount.replaceChildren(FTUI.empty(
        context.t("数据源读取失败"), error.message || context.t("请稍后重试"),
      ));
    });
  }

  function helpersAreCurrent(context) {
    const page = context.content?.querySelector(".product-category-detail-page");
    return Boolean(page && context.content.contains(page));
  }

  function parentSection(context, category) {
    return FTUI.table(
      [context.t("绑定的父分类"), context.t("分类 ID")],
      category.parent_category_ids.map(id => [
        (category.parent_category_labels || {})[id] || id, id,
      ]),
    ).shell;
  }

  function providerServers(source, context) {
    const values = source?.servers || source?.server_ids
      || source?.provider_servers || source?.provided_by || [];
    if (Array.isArray(values)) return values.join("、") || "—";
    if (values && typeof values === "object") return Object.keys(values).join("、") || "—";
    return String(values || context.t("当前服务器")).trim();
  }

  window.FTProductCategoryDetailLayout = Object.freeze({render});
})();
