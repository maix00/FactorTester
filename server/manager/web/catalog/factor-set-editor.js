(() => {
  function frozenRecord(value) {
    return window.FTFactorModel?.objectChoice?.(value)?.record || null;
  }

  function candidates(data, current = []) {
    const mine = data?.factorScopes?.mine || data?.factor_scopes?.mine
      || data?.familyScopes?.mine || data?.family_scopes?.mine;
    const personal = Array.isArray(mine?.factors)
      ? mine.factors
      : (data?.factors || []).filter(item => (
        String(item?.owner_username || "") === String(data?.principal || "")
      ));
    const values = [...personal];
    current.forEach(item => values.push(item?.data || item));
    const seen = new Set();
    return values.flatMap(value => {
      const record = frozenRecord(value);
      if (!record || seen.has(record.ref)) return [];
      seen.add(record.ref);
      return [{
        value: record.ref,
        label: record.alias,
        description: [record.identity.family_alias, record.owner_ref]
          .filter(Boolean).join(" · "),
        record,
      }];
    });
  }

  function ownerLabel(context, current) {
    return String(
      current.owner_alias || current.owner_username
      || context.session.display_name || context.session.username || "",
    ).trim();
  }

  function cancel(context) {
    if (!FTTabReturn.returnToSource(context)) {
      context.closeTab?.(context.tabID);
      context.navigate("/factors/sets?scope=mine");
    }
  }

  async function render(context, data, targetRef, mode, options = {}) {
    if (!context.session) throw new Error(context.t("登录后才能编辑因子集合"));
    const current = options.initialValue || data?.sets?.find(item => (
      item.target_ref === targetRef || item.set_ref === targetRef
    )) || {};
    if (mode === "edit" && current.can_edit !== true) {
      throw new Error(context.t("当前因子集合为只读，不能编辑"));
    }
    const manifest = current.manifest || {};
    const identity = manifest.identity || current.identity || {};
    const related = current.related_references || [];
    const items = candidates(data, related);
    const state = {
      setID: identity.set_id || current.set_id || "",
      alias: manifest.alias || current.title_zh || current.alias || "",
      description:
        manifest.description || current.description_zh || current.description || "",
      owner: ownerLabel(context, current),
      members: (identity.members || related.map(item => item.data || item))
        .map(item => typeof item === "string" ? item : item?.ref || item?.target_ref)
        .filter(Boolean),
    };
    const title = mode === "create"
      ? context.t("新增因子集合") : state.alias || context.t("编辑因子集合");
    const jobs = window.FTFactorObjectJobs.create(context, {
      objectKind: "set",
      objectRef: current.target_ref || targetRef,
    });
    window.FTFactorObjectForm.render(context, {
      objectKind: "set",
      mode,
      title,
      subtitle: context.t("因子集合详情"),
      state,
      fields: [
        {
          key: "setID", label: "集合标识", required: true,
          readOnly: mode === "edit",
        },
        {key: "alias", label: "因子集合", required: true},
        {key: "description", label: "说明", multiline: true},
        {key: "owner", label: "所有者", kind: "readonly", tab: "identity"},
        {
          key: "members",
          label: "因子",
          kind: "picker",
          tab: "members",
          multi: true,
          items,
          searchPlaceholder: context.t("搜索因子"),
        },
      ],
      sections: mode === "edit" && !context.testObjectTemporary
        ? [{tab: "jobs", content: jobs.mount}] : [],
      tabOverrides: {
        sources: {hidden: true},
        jobs: {
          hidden: mode !== "edit" || context.testObjectTemporary === true,
          onActivate: jobs.load,
        },
      },
      onReady: editor => {
        window.FTFactorSetAssistance?.register?.(context, {
          mode, state, tabs: editor.tabs,
          onImport: document => {
            state.setID = document.set_id;
            state.alias = document.alias;
            state.description = document.description;
            state.members = [...document.members];
            editor.syncFromState();
          },
        });
      },
      onCancel: () => cancel(context),
      onSubmit: async values => {
        const members = values.members.map(ref => (
          items.find(item => item.value === ref)?.record
        )).filter(Boolean);
        if (!members.length) throw new Error(context.t("请至少选择一个因子"));
        const payload = await context.api("/api/catalog/factor-sets", {
          method: "POST",
          body: JSON.stringify({
            persist: context.testObjectTemporary !== true,
            replace_target_ref: mode === "edit" ? targetRef : "",
            definition: {
              set_id: values.setID.trim(),
              alias: values.alias.trim(),
              description: values.description.trim(),
              members,
            },
          }),
        });
        const value = payload.factor_set || payload;
        if (context.onSaved) return context.onSaved(value);
        const ref = value.target_ref || value.manifest?.ref;
        if (FTTabReturn.returnToSource(context, {kind: "factor_set", ref})) return;
        context.closeTab?.(context.tabID);
        context.navigate(`/factors/set/${encodeURIComponent(ref)}`);
      },
    });
  }

  window.FTFactorSetEditor = Object.freeze({render});
})();
