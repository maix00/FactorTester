(() => {
  function choose(context, definitions) {
    const available = (Array.isArray(definitions) ? definitions : [])
      .filter((item, index, all) => item?.id && (
        all.findIndex(candidate => candidate?.id === item.id) === index
      ));
    return new Promise(resolve => {
      let resolved = false;
      const dialog = document.createElement("dialog");
      dialog.className = "product-category-dialog";
      const card = document.createElement("form");
      card.method = "dialog";
      card.className = "dialog-card wide product-category-overlay-card";
      const title = document.createElement("h2");
      title.textContent = context.t("创建乘积 Category");
      const description = document.createElement("p");
      description.textContent = context.t(
        "选择两个已有 Category；已有乘积也可继续参与组合",
      );
      const choices = document.createElement("div");
      choices.className = "product-category-overlay-choices";
      const inputs = available.map(item => {
        const label = document.createElement("label");
        label.className = "check-row";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = item.id;
        const copy = document.createElement("span");
        copy.textContent = item.title_zh || item.alias || item.id;
        label.append(input, copy);
        choices.append(label);
        return input;
      });
      const actions = document.createElement("div");
      actions.className = "dialog-actions";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "secondary";
      cancel.textContent = context.t("取消");
      const create = document.createElement("button");
      create.type = "button";
      create.className = "primary";
      create.textContent = context.t("创建");
      create.disabled = true;
      const selected = () => inputs.filter(input => input.checked);
      inputs.forEach(input => input.addEventListener("change", () => {
        if (selected().length > 2) input.checked = false;
        create.disabled = selected().length !== 2;
      }));
      const finish = value => {
        if (resolved) return;
        resolved = true;
        dialog.close();
        resolve(value);
      };
      cancel.addEventListener("click", () => finish(null));
      create.addEventListener("click", () => {
        finish(selected().map(input => input.value));
      });
      dialog.addEventListener("close", () => {
        dialog.remove();
        if (!resolved) {
          resolved = true;
          resolve(null);
        }
      });
      actions.append(cancel, create);
      card.append(title, description, choices, actions);
      dialog.append(card);
      document.body.append(dialog);
      dialog.showModal();
    });
  }

  window.FTProductCategoryOverlay = Object.freeze({choose});
})();
