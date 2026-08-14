(() => {
  function list(context, state, refresh) {
    const root = document.createElement("div"); root.className = "test-factor-candidates";
    const title = document.createElement("b"); title.textContent = context.t("因子候选"); root.append(title);
    const rows = FTTestFactorSelection.candidates(state);
    if (!rows.length) {
      root.append(FTUI.empty(context.t("暂无因子候选"), context.t("选择因子家族并填写参数后添加")));
      return root;
    }
    const listNode = document.createElement("div"); listNode.className = "test-factor-candidate-list";
    for (const factor of rows) {
      const row = document.createElement("label");
      const input = document.createElement("input");
      input.type = state.kind === "ic" ? "checkbox" : "radio";
      input.name = state.kind === "ic" ? "" : `factor-${state.kind}`;
      input.checked = FTTestFactorSelection.isSelected(state, factor);
      input.addEventListener("change", () => {
        FTTestFactorSelection.setSelected(state, factor, input.checked); refresh();
      });
      const copy = document.createElement("span");
      const name = document.createElement("b");
      name.textContent = factor.factor_alias || factor.alias || factor.factor_ref;
      const detail = document.createElement("small");
      const revision = factor.source_kind === "transient"
        ? context.t("任务临时输入")
        : factor.git_commit ? factor.git_commit.slice(0, 10) : context.t("服务器登记");
      detail.textContent = factor.source_kind === "transient"
        ? revision : `${factor.owner_ref || ""} · ${revision}`.replace(/^ · | · $/g, "");
      copy.append(name, detail);
      const remove = context.button(context.t("移除"), event => {
        event.preventDefault(); FTTestFactorSelection.removeCandidate(state, factor); refresh();
      });
      row.append(input, copy, remove); listNode.append(row);
    }
    root.append(listNode); return root;
  }

  window.FTTestFactorCandidates = Object.freeze({list});
})();
