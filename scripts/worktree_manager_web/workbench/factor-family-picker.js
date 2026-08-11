(() => {
  function entries(options = {}) {
    const publicItems = (options.publicFamilies || []).map(item => normalize(
      item, "public", item.owner_ref || item.owner_alias || "",
      item.git_commit || "",
    ));
    const localItems = (options.localFamilies || []).map(item => normalize(
      item, "local", options.ownerRef || item.owner_ref || "",
      options.gitCommit || item.git_commit || "",
    ));
    return [...publicItems, ...localItems].filter(item => item.family);
  }

  function normalize(value, sourceKind, ownerRef, gitCommit) {
    const family = value.factor_family_alias || value.family_alias
      || value.family || value.name || "";
    const familyRef = value.family_ref || value.factor_family_ref || "";
    const sourceIdentity = familyRef || [ownerRef, gitCommit, family].join(":");
    return {
      ...value,
      key: `${sourceKind}:${sourceIdentity}`,
      sourceKind,
      family,
      familyRef,
      ownerRef,
      gitCommit,
      title: family,
      description: value.chinese_name || value.title_zh || value.desc
        || value.description || "",
    };
  }

  function filter(items, query) {
    const needle = String(query || "").trim().toLocaleLowerCase();
    if (!needle) return [...(items || [])];
    return (items || []).filter(item => [
      item.family, item.title, item.description, item.ownerRef,
      item.owner_alias, item.profile_id, item.familyRef,
    ].some(value => String(value || "").toLocaleLowerCase().includes(needle)));
  }

  function familyFactors(family, factors) {
    const refs = new Set(family?.factor_refs || []);
    return (factors || []).filter(item => refs.has(item.factor_ref));
  }

  function open(context, options = {}) {
    const items = Array.isArray(options.items) ? options.items : [];
    const dialog = document.createElement("dialog");
    dialog.className = "factor-family-picker-dialog";
    const card = document.createElement("section");
    card.className = "dialog-card wide factor-family-picker";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    const copy = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = context.t("选择因子家族");
    const note = document.createElement("p");
    note.textContent = context.t("搜索公共因子库或本地 Git 修订中的因子家族");
    copy.append(title, note); heading.append(copy);
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = context.t("搜索原类名、中文说明或所有者");
    search.setAttribute("aria-label", context.t("搜索因子家族"));
    const list = document.createElement("div");
    list.className = "factor-family-picker-list";
    const render = () => renderRows(context, list, filter(items, search.value), options, dialog);
    search.addEventListener("input", render);
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    actions.append(FTUI.actionButton(context.t("取消"), () => dialog.close(), {
      variant: "secondary",
    }));
    card.append(heading, search, list, actions);
    dialog.append(card);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog);
    dialog.showModal();
    render(); search.focus();
    return dialog;
  }

  function renderRows(context, mount, items, options, dialog) {
    if (!items.length) {
      mount.replaceChildren(FTUI.empty(
        context.t("没有匹配的因子家族"), context.t("请更换关键词"),
      ));
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `factor-family-picker-row${
        item.key === options.selectedKey ? " selected" : ""
      }`;
      const body = document.createElement("span");
      const name = document.createElement("b"); name.textContent = item.title;
      const description = document.createElement("small");
      description.textContent = item.description || item.ownerRef || item.familyRef;
      body.append(name, description);
      const source = document.createElement("span");
      source.className = "factor-family-source";
      source.textContent = context.t(item.sourceKind === "local" ? "本地修订" : "公共因子库");
      button.append(body, source);
      button.addEventListener("click", async () => {
        await options.onSelect?.(item);
        dialog.close();
      });
      fragment.append(button);
    }
    mount.replaceChildren(fragment);
  }

  window.FTFactorFamilyPicker = Object.freeze({entries, familyFactors, filter, open});
})();
