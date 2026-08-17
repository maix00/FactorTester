(() => {
  function prepare(state) { FTTestFactorCatalog.prepare(state); }

  async function initialize(context, state) {
    await FTTestFactorCatalog.initialize(context, state);
  }

  function panel(context, state, refresh, contentOptions = {}) {
    const root = document.createElement("div"); root.className = "test-factor-builder";
    const catalog = state.factorCatalog;
    const sourceInput = (contentOptions.inputs || [])
      .find(item => item.kind === "factor_source");
    const setPanel = FTTestFactorSets.panel(context, state, refresh);
    if (setPanel) root.append(setPanel);
    if (sourceInput) root.append(FTTestSourceUpload.factorControls(
      context, state, refresh,
      entry => FTTestFactorCatalog.selectFamily(context, state, entry, refresh), sourceInput,
    ));
    if (!catalog.native) {
      root.append(
        FTTestFactorEditor.familyChooser(context, state, refresh),
        FTTestFactorEditor.familyContent(context, state, refresh, sourceInput),
        FTTestFactorCandidates.list(context, state, refresh),
      );
      return root;
    }
    const source = document.createElement("div"); source.className = "test-factor-source-rows";
    source.append(
      FTTestFactorEditor.selectField(
        context.t("所有者"), catalog.owners.map(item => ({
          value: item.owner_ref,
          label: item.display_name || item.title_zh || item.profile_name || item.owner_ref,
        })), state.values.factor_owner_ref, async value => {
          state.values.factor_owner_ref = value;
          state.values.factor_git_commit = ""; state.values.factor_family_ref = "";
          state.values.factor_params = {}; catalog.selectedFamilyEntry = null;
          catalog.selectedFamilyName = "";
          await FTTestFactorCatalog.update(context, state, refresh,
            () => FTTestFactorCatalog.loadRevisions(state));
        }, context,
      ),
      FTTestFactorEditor.selectField(
        context.t("Git commit"), catalog.revisions.map(item => ({
          value: item.git_commit, label: `${item.git_commit.slice(0, 10)} · ${item.subject || ""}`,
        })), state.values.factor_git_commit, async value => {
          state.values.factor_git_commit = value; state.values.factor_family_ref = "";
          state.values.factor_params = {}; catalog.selectedFamilyEntry = null;
          catalog.selectedFamilyName = "";
          await FTTestFactorCatalog.update(context, state, refresh,
            () => FTTestFactorCatalog.loadFamilies(state));
        }, context,
      ),
      FTTestFactorEditor.familyChooser(context, state, refresh),
    );
    root.append(source);
    root.append(FTTestFactorEditor.familyContent(context, state, refresh, sourceInput));
    if (catalog.busy) root.append(FTUI.loading(context.t("正在读取因子工作区…")));
    if (catalog.error) root.append(FTTestFactorEditor.errorText(catalog.error));
    root.append(FTTestFactorCandidates.list(context, state, refresh));
    return root;
  }

  function selectedFactor(state) { return FTTestFactorSelection.selectedFactor(state); }
  function selectedFamily(state, factor) { return FTTestFactorSelection.selectedFamily(state, factor); }

  window.FTTestFactors = {initialize, panel, prepare, selectedFactor, selectedFamily};
})();
