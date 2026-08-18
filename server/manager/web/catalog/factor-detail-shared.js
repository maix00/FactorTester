(() => {
  function expression(value) {
    return window.FTFactorModel?.factorExpression?.(value) || "";
  }

  function summary(context, value) {
    const expressionValue = expression(value);
    const description = String(
      value?.description || value?.chinese_name || value?.desc || "",
    ).trim();
    if (!description && !expressionValue) return document.createDocumentFragment();
    const root = document.createElement("section");
    root.className = "factor-family-summary";
    if (description) {
      const copy = document.createElement("p");
      copy.textContent = description;
      root.append(copy);
    }
    if (expressionValue && window.katex) {
      const heading = document.createElement("h3");
      heading.textContent = context.t("FactorExpr 公式");
      const formula = document.createElement("div");
      formula.className = "factor-family-formula display-math";
      window.katex.render(expressionValue, formula, {
        displayMode: true, throwOnError: false,
      });
      root.append(heading, formula);
    }
    return root;
  }

  function parameterEditor(context, parameters = [], initial = {}) {
    const values = {...initial};
    const root = document.createElement("section");
    root.className = "factor-detail-parameter-editor";
    for (const parameter of parameters) {
      const alias = String(parameter?.alias || parameter?.name || "").trim();
      if (!alias) continue;
      const row = document.createElement("label");
      row.className = "test-object-field";
      const title = document.createElement("b");
      title.textContent = alias;
      const input = document.createElement("input");
      input.type = "text";
      input.value = values[alias] ?? parameter.default_value ?? "";
      values[alias] = input.value;
      input.addEventListener("input", () => { values[alias] = input.value; });
      row.append(title, input);
      if (parameter.desc || parameter.value_space_desc) {
        const help = document.createElement("small");
        help.textContent = parameter.desc || parameter.value_space_desc;
        row.append(help);
      }
      root.append(row);
    }
    return {root, values};
  }

  window.FTFactorDetailShared = Object.freeze({expression, parameterEditor, summary});
})();
