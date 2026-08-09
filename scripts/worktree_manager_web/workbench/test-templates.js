(() => {
  function kindOf(template) {
    const analyses = template.payload?.analyses || {};
    if (analyses.ic) return "ic";
    if (analyses.backtest) return "backtest";
    return "";
  }

  function summary(template, context) {
    const payload = template.payload || {};
    const kind = kindOf(template);
    const analysis = payload.analyses?.[kind] || {};
    const families = (payload.shared?.factor_families || []).map(item => item.alias).filter(Boolean);
    const factors = (payload.shared?.factors || []).map(item => item.alias).filter(Boolean);
    const local = analysis.local_settings || analysis.settings || {};
    return [
      [context.t("模板名称"), template.name],
      [context.t("测试类型"), kind === "ic" ? context.t("IC 测试") : context.t("回测")],
      [context.t("因子家族"), families.join("、")],
      [context.t("因子"), factors.join("、")],
      [context.t("时间范围"), [local.start_date, local.end_date].filter(Boolean).join(" → ")],
      [context.t("配置版本"), template.revision],
      [context.t("更新时间"), FTUI.formatDate(template.updated_at)],
    ];
  }

  function list(context, templates, kind, handlers) {
    const rows = templates.filter(item => kindOf(item) === kind);
    const root = document.createElement("section");
    root.className = "test-template-section";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    heading.innerHTML = `<div><h2>${context.t("测试模板")}</h2><p>${context.t("保存、预览或加载当前测试配置")}</p></div>`;
    const save = context.button(context.t("保存当前配置"), handlers.save);
    heading.append(save);
    root.append(heading);
    if (!rows.length) {
      root.append(FTUI.empty(context.t("暂无模板"), context.t("保存当前设置后会显示在这里")));
      return root;
    }
    const table = FTUI.table(
      [context.t("名称"), context.t("因子"), context.t("更新时间"), context.t("操作")],
      rows.map(item => {
        const actions = document.createElement("span");
        actions.className = "row-actions";
        actions.append(
          context.button(context.t("加载"), () => handlers.load(item)),
          context.button(context.t("查看"), () => context.navigate(`/test-templates/${encodeURIComponent(item.configuration_id)}`)),
          context.button(context.t("覆盖"), () => handlers.overwrite(item)),
          context.button(context.t("删除"), () => handlers.delete(item)),
        );
        return [
          item.name,
          (item.payload?.shared?.factors || []).map(value => value.alias).join("、"),
          FTUI.formatDate(item.updated_at),
          actions,
        ];
      }),
    );
    root.append(table.shell);
    return root;
  }

  async function detail(context, configurationID) {
    context.activeNav("");
    context.content.replaceChildren(FTUI.loading(context.t("正在读取模板…")));
    const value = await context.api(context.servicePath("/api/configuration-templates"));
    const template = (value.templates || []).find(item => item.configuration_id === configurationID);
    if (!template) throw new Error(context.t("模板不存在"));
    context.setHeading(template.name || context.t("模板详情"), context.t("测试模板"));
    const root = document.createElement("div");
    root.className = "detail-stack";
    root.append(
      FTUI.table([context.t("字段"), context.t("值")], summary(template, context)).shell,
      FTUI.code(template.payload),
    );
    context.content.replaceChildren(root);
  }

  window.FTTestTemplates = {detail, kindOf, list, summary};
})();
