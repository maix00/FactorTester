(() => {
  function list(context, helpers) {
    const source = helpers.sourceOf();
    context.activeNav("products");
    context.setHeading(context.t("产品分类"),
      source === "local" ? context.t("本地产品目录") : context.t("服务器产品目录"));
    helpers.catalogSwitch(context, "categories", source);
    const root = document.createElement("div");
    root.className = "library-page product-category-management-page";
    root.append(helpers.sourceSummary(context, source));
    const toolbar = document.createElement("div");
    toolbar.className = "product-category-management-actions";
    const readOnly = source === "local";
    if (!readOnly) {
      toolbar.append(
        FTUI.actionButton(context.t("新增分类"), () => openCreate(context, helpers), {
          variant: "primary",
        }),
        FTUI.actionButton(context.t("新增乘积分类"), async () => {
          const value = await helpers.loadCategories(context, source);
          const selected = await window.FTProductCategoryOverlay.choose(
            context, value.categories || [],
          );
          if (!selected) return;
          try {
            await context.api("/api/catalog/categories/composite", {
              method: "POST",
              body: JSON.stringify({category_ids: selected}),
            });
            list(context, helpers);
          } catch (error) {
            context.showNotice?.(error.message || context.t("产品分类保存失败"), true);
          }
        }, {variant: "secondary"}),
      );
    }
    toolbar.append(context.button("↻", () => list(context, helpers), context.t("刷新")));
    root.append(toolbar);
    const mount = document.createElement("div");
    mount.className = "product-category-management-results";
    mount.append(FTUI.loading(context.t("正在读取产品分类…")));
    root.append(mount);
    context.content.replaceChildren(root);
    helpers.loadCategories(context, source).then(value => {
      if (!helpers.isCurrent()) return;
      renderCategories(context, helpers, mount, value.categories || [], readOnly);
    }).catch(error => {
      if (!helpers.isCurrent()) return;
      mount.replaceChildren(FTUI.empty(
        context.t("产品分类读取失败"), error.message || "",
      ));
    });
  }

  function renderCategories(context, helpers, mount, categories, readOnly) {
    if (!categories.length) {
      mount.replaceChildren(FTUI.empty(
        context.t("尚无产品分类"), context.t("请先新增一个产品分类"),
      ));
      return;
    }
    const table = FTUI.table(
      [context.t("名称"), context.t("类型"), context.t("条目数"),
        context.t("分类维度"), context.t("数据源"), context.t("产品路径")],
      categories.map(category => [
        category.title_zh || category.alias || category.id,
        category.source_managed
          ? context.t("数据源分类")
          : category.is_composite ? context.t("乘积分类") : context.t("用户分类"),
        Array.isArray(category.items) ? category.items.length : 0,
        (category.parent_category_ids || category.dimensions || []).join(" × "),
        (category.source_ids || []).join("、") || "—",
        pathSummary(context, category),
      ]),
    );
    [...table.body.rows].forEach((row, index) => {
      const category = categories[index];
      row.dataset.href = "true";
      row.addEventListener("click", () => showDetail(context, helpers, category, readOnly));
    });
    mount.replaceChildren(table.shell);
  }

  function pathSummary(context, category) {
    const values = (category.items || []).flatMap(item => item.paths || []);
    if (!values.length) return category.is_composite ? context.t("按父分类解析") : "—";
    return `${values.length} ${context.t("条")}`;
  }

  function showDetail(context, helpers, category, readOnly) {
    const dialog = document.createElement("dialog");
    dialog.className = "product-category-detail-dialog";
    const card = document.createElement("form");
    card.method = "dialog";
    card.className = "dialog-card wide product-category-detail-card";
    const close = document.createElement("button");
    close.type = "submit"; close.className = "dialog-close"; close.textContent = "×";
    const title = document.createElement("h2");
    title.textContent = category.title_zh || category.alias || category.id;
    const rows = (category.items || []).map(item => [
      item.label || "—", multiline(item.paths || []),
    ]);
    const content = rows.length
      ? FTUI.table([context.t("标签"), context.t("产品路径")], rows).shell
      : FTUI.empty(context.t("暂无显式条目"), context.t("该分类按父分类或数据源目录解析"));
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    if (!readOnly && !category.source_managed) {
      const remove = FTUI.actionButton(context.t("删除"), async () => {
        if (!window.confirm(context.t("确认删除该产品分类？"))) return;
        try {
          await context.api(`/api/catalog/categories/${encodeURIComponent(category.id)}`, {
            method: "DELETE",
          });
          dialog.close();
          list(context, helpers);
        } catch (error) {
          context.showNotice?.(error.message || context.t("产品分类删除失败"), true);
        }
      }, {variant: "secondary"});
      actions.append(remove);
    }
    card.append(close, title, content, actions);
    dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog); dialog.showModal();
  }

  function openCreate(context, helpers) {
    const dialog = document.createElement("dialog");
    dialog.className = "product-category-create-dialog";
    const form = document.createElement("form");
    form.className = "dialog-card wide product-category-create-card";
    const title = document.createElement("h2");
    title.textContent = context.t("新增分类");
    const nameField = document.createElement("label");
    nameField.className = "test-object-field";
    const nameLabel = document.createElement("b"); nameLabel.textContent = context.t("分类名称");
    const name = document.createElement("input"); name.required = true;
    name.placeholder = context.t("例如：日夜盘、行业");
    nameField.append(nameLabel, name);
    const note = document.createElement("p");
    note.textContent = context.t("标准产品路径不包含分类；保存时会自动转换可识别的分类路径");
    const rows = document.createElement("div");
    rows.className = "product-category-item-rows";
    const addRow = () => rows.append(itemRow(context, rows));
    addRow();
    const add = FTUI.actionButton(context.t("新增条目"), addRow, {variant: "secondary"});
    const status = document.createElement("small"); status.className = "product-category-form-error";
    const actions = document.createElement("div"); actions.className = "dialog-actions";
    const cancel = FTUI.actionButton(context.t("取消"), () => dialog.close(), {variant: "secondary"});
    const save = FTUI.actionButton(context.t("保存"), null, {variant: "primary"});
    save.type = "submit"; actions.append(cancel, save);
    form.append(title, nameField, note, rows, add, status, actions);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const items = [...rows.children].map(row => ({
        label: row.querySelector("input")?.value || "",
        paths: row.querySelector("textarea")?.value.split(/\r?\n/) || [],
      }));
      save.disabled = true; status.textContent = "";
      try {
        await context.api("/api/catalog/categories", {
          method: "POST", body: JSON.stringify({name: name.value, items}),
        });
        dialog.close(); list(context, helpers);
      } catch (error) {
        status.textContent = error.message || context.t("产品分类保存失败");
      } finally { save.disabled = false; }
    });
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    dialog.append(form); document.body.append(dialog); dialog.showModal(); name.focus();
  }

  function itemRow(context, rows) {
    const row = document.createElement("div"); row.className = "product-category-item-row";
    const label = document.createElement("input"); label.placeholder = context.t("条目标签"); label.required = true;
    const paths = document.createElement("textarea"); paths.placeholder = context.t("每行一个产品路径"); paths.required = true; paths.rows = 3;
    const remove = FTUI.actionButton(context.t("移除"), () => {
      if (rows.children.length > 1) row.remove();
    }, {variant: "secondary"});
    row.append(label, paths, remove); return row;
  }

  function multiline(values) {
    const mount = document.createElement("div"); mount.className = "catalog-source-lines";
    (values || []).forEach(value => mount.append(Object.assign(document.createElement("div"), {
      textContent: value,
    })));
    return mount;
  }

  window.FTProductCategories = Object.freeze({list, openCreate});
})();
