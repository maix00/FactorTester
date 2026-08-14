(() => {
  function content(context, state, refresh) {
    const section = document.createElement("div");
    section.className = "test-output-content";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    const copy = document.createElement("div");
    const declaration = FTTestRunFields.field(state.manifest, "output_requests");
    const title = document.createElement("h2");
    title.textContent = context.t(declaration?.label || "结果与生成物");
    const note = document.createElement("p");
    note.textContent = context.t(
      declaration?.help_text || "提交前选定的输出会冻结进 RunSpec，并保留生成所需的原始结果",
    );
    copy.append(title, note); heading.append(copy); section.append(heading);
    const definitions = FTOutputChoices.available(
      state.outputCapabilities, state.kind,
    );
    if (!definitions.length) {
      section.append(FTUI.empty(context.t("暂无可选输出"), ""));
      return section;
    }
    section.append(FTOutputChoices.choices(
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
