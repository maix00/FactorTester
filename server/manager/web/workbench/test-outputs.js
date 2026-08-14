(() => {
  function content(context, state, refresh) {
    const section = document.createElement("div");
    section.className = "test-output-content";
    const declaration = FTTestRunFields.field(state.manifest, "output_requests");
    const heading = document.createElement("div");
    heading.className = "section-heading";
    const title = document.createElement("h2");
    title.textContent = context.t(declaration?.label || "结果与生成物");
    if (declaration?.help_text) heading.title = context.t(declaration.help_text);
    heading.append(title); section.append(heading);
    if (!state.outputCapabilitiesLoaded) {
      const lazy = state.lazy?.outputs;
      if (lazy?.status === "error") {
        section.append(FTUI.empty(
          context.t("读取失败"), lazy.error || context.t("请重试"),
        ));
        return section;
      }
      const hint = document.createElement("p");
      hint.className = "test-output-default-hint";
      hint.textContent = context.t("当前使用默认生成物；打开配置后选择需要的结果");
      const configure = context.button(context.t("配置生成物"), () => {
        window.FTTests?.ensureOutputCapabilities?.(context, state, refresh);
        refresh?.();
      });
      section.append(hint, configure);
      if (lazy?.status === "loading") {
        section.append(FTUI.loading(context.t("正在读取可选生成物…")));
      }
      return section;
    }
    if (!window.FTOutputChoices) {
      const hint = document.createElement("p");
      hint.className = "test-output-default-hint";
      hint.textContent = context.t("打开配置生成物后读取选择器代码");
      const configure = context.button(context.t("配置生成物"), () => {
        window.FTTests?.ensureOutputCapabilities?.(context, state, refresh);
        refresh?.();
      });
      section.append(hint, configure);
      return section;
    }
    const definitions = FTOutputChoices.available(
      state.outputCapabilities, state.kind,
    );
    if (!definitions.length) {
      section.append(FTUI.empty(context.t("暂无可选输出"), ""));
      return section;
    }
    section.append(FTOutputChoices.fieldValueSelector(
      context, definitions, state.outputRequests, value => {
        state.outputRequests = value;
        refresh?.();
      },
    ));
    return section;
  }

  function render(context, state, refresh) {
    const section = document.createElement("section");
    section.className = "test-output-panel";
    section.append(content(context, state, refresh));
    return section;
  }

  function selection(state) {
    return Array.isArray(state.outputRequests) ? [...state.outputRequests] : [];
  }

  window.FTTestOutputs = Object.freeze({content, render, selection});
})();
