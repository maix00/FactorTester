(() => {
  function render(context, state, refresh) {
    FTTestInputState.initialize(state);
    const root = document.createElement("section");
    root.className = "strategy-binding-panel";
    synchronizeVenueState(state);

    const note = document.createElement("p");
    note.className = "strategy-binding-note";
    note.textContent = context.t(
      "每个 Nautilus Venue 维护独立账户和撮合状态。策略可以显式请求账户间划转；模拟环境由执行引擎校验并记账，实盘必须由券商适配器调用真实划转 API。Venue 之间不会自动共享余额。",
    );
    root.append(note);
    const useNautilus = state.executionBackend === "nautilus_trader"
      || state.analysis?.execution?.backend === "nautilus_trader";
    const nativeSchema = state.nautilusCapabilities?.simulated_venue_config || null;
    const nativeSchemaError = state.nautilusCapabilitiesError || "";
    if (useNautilus && !nativeSchema && !state.nautilusCapabilitiesLoading
        && !nativeSchemaError) {
      state.nautilusCapabilitiesLoading = true;
      void loadNativeSchema(context, state).then(() => {
        if (root.isConnected) refresh?.();
      }).catch(error => {
        state.nautilusCapabilitiesError = error.message || String(error);
        if (root.isConnected) refresh?.();
      }).finally(() => {
        state.nautilusCapabilitiesLoading = false;
      });
    }

    const venues = document.createElement("section");
    venues.className = "strategy-binding-venues";
    const venueHeading = document.createElement("div");
    venueHeading.className = "strategy-binding-section-heading";
    const venueTitle = document.createElement("h3");
    venueTitle.textContent = context.t("Nautilus Venue 与账户");
    const addVenue = context.button(context.t("添加 Venue"), () => {
      const name = nextVenueName(state.analysis.venues);
      state.analysis.venues.push({
        name, account_type: "MARGIN", oms_type: "NETTING", starting_balance: "",
      });
      state.nautilusReview = null;
      refresh?.();
    });
    venueHeading.append(venueTitle, addVenue);
    venues.append(venueHeading);
    if (!state.analysis.venues.length) {
      const empty = document.createElement("p");
      empty.className = "strategy-binding-empty";
      empty.textContent = context.t("尚未配置 Venue。请按真实交易场所的 Nautilus Venue ID 添加，例如数据中的 CFFEX 或 SHFE。" );
      venues.append(empty);
    }
    const venueRows = document.createElement("div");
    venueRows.className = "strategy-binding-venue-rows";
    state.analysis.venues.forEach((venue, index) => venueRows.append(
      venueRow(context, state, venue, index, refresh, useNautilus, nativeSchema, nativeSchemaError),
    ));
    venues.append(venueRows);
    root.append(venues);

    const groups = Array.isArray(state.analysis?.groups) ? state.analysis.groups : [];
    const strategySection = document.createElement("section");
    strategySection.className = "strategy-binding-strategies";
    const strategyHeading = document.createElement("h3");
    strategyHeading.textContent = context.t("策略与 Venue 路由");
    strategySection.append(strategyHeading);
    if (!groups.length) {
      strategySection.append(FTUI.empty(
        context.t("暂无策略实例"), context.t("请先添加回测策略配置，再将策略绑定到 Venue"),
      ));
      root.append(strategySection);
      return root;
    }

    const rows = document.createElement("div");
    rows.className = "strategy-binding-rows";
    strategySection.append(rows);
    root.append(strategySection);
    const redraw = () => {
      synchronizeVenueState(state);
      rows.replaceChildren(...groups.map(group => bindingRow(
        context, state, group, refresh,
      )));
    };
    redraw();
    return root;
  }

  function synchronizeVenueState(state) {
    state.analysis ||= {};
    if (!Array.isArray(state.analysis.venues)) state.analysis.venues = [];
    if (!Array.isArray(state.analysis.strategy_venue_bindings)) {
      state.analysis.strategy_venue_bindings = [];
    }
    const groups = Array.isArray(state.analysis.groups) ? state.analysis.groups : [];
    const current = new Map(state.analysis.strategy_venue_bindings
      .filter(item => item && item.strategy_id)
      .map(item => [String(item.strategy_id), item]));
    state.analysis.strategy_venue_bindings = groups.map(group => {
      const strategyID = String(group.id || "").trim();
      const prior = current.get(strategyID);
      let venueIDs = Array.isArray(prior?.venue_ids)
        ? prior.venue_ids.map(value => String(value).trim().toUpperCase()).filter(Boolean)
        : [];
      if (!venueIDs.length && state.analysis.venues.length === 1) {
        venueIDs = [String(state.analysis.venues[0].name || "").trim().toUpperCase()].filter(Boolean);
      }
      return {strategy_id: strategyID, venue_ids: [...new Set(venueIDs)]};
    }).filter(item => item.strategy_id);
  }

  function venueRow(context, state, venue, index, refresh, useNautilus, nativeSchema, nativeSchemaError) {
    const row = document.createElement("article");
    row.className = "strategy-binding-venue-row";
    const title = document.createElement("strong");
    title.className = "strategy-binding-venue-title";
    title.textContent = `${context.t("Venue")} ${index + 1}`;
    const venueIDLabel = nativeSchema?.venue_identity?.label || "Venue ID";

    const name = document.createElement("input");
    name.type = "text";
    name.maxLength = 64;
    name.value = String(venue.name || "");
    name.placeholder = context.t("Nautilus Venue ID，例如 CFFEX");
    name.setAttribute("aria-label", `${context.t(venueIDLabel)} ${index + 1}`);
    name.addEventListener("change", () => {
      const oldName = String(venue.name || "").trim().toUpperCase();
      venue.name = name.value.trim().toUpperCase();
      if (oldName && oldName !== venue.name) {
        for (const route of state.analysis.strategy_venue_bindings) {
          route.venue_ids = (route.venue_ids || []).map(value => (
            String(value).toUpperCase() === oldName ? venue.name : value
          )).filter(Boolean);
        }
      }
      state.nautilusReview = null;
      refresh?.();
    });

    const venueConfigFields = document.createElement("div");
    venueConfigFields.className = "strategy-binding-venue-fields";
    venueConfigFields.append(field(context, venueIDLabel, name));
    const descriptors = nativeSchema?.available
      ? nativeSchema.venue_fields || [] : [];
    if (descriptors.length) {
      for (const descriptor of descriptors) {
        if (descriptor.path === "base_currency") continue;
        const current = getPath(venue, descriptor.path);
        if (descriptor.path === "starting_balances" && current === undefined
            && venue.starting_balance != null && String(venue.starting_balance).trim()) {
          const currency = String(venue.currency || state.values?.base_currency || "CNY").toUpperCase();
          venue.starting_balances = [`${venue.starting_balance} ${currency}`];
          delete venue.starting_balance;
        }
        const control = nativeControl(context, venue, descriptor, state, refresh);
        venueConfigFields.append(field(context, descriptor.label, control));
      }
    } else if (useNautilus) {
      const message = document.createElement("p");
      message.className = "strategy-binding-native-note";
      message.textContent = nativeSchemaError || context.t("正在读取 Nautilus 能力目录；能力确认前不会显示可编辑参数。");
      venueConfigFields.append(message);
    } else {
      venueConfigFields.append(
        selectField(context, "账户类型", [
          ["MARGIN", "MARGIN · 保证金"], ["CASH", "CASH · 现金"], ["BETTING", "BETTING · 博彩"],
        ], venue.account_type || "MARGIN", value => {
          venue.account_type = value;
          state.nautilusReview = null;
          refresh?.();
        }),
        selectField(context, "订单管理", [
          ["NETTING", "NETTING · 净持仓"], ["HEDGING", "HEDGING · 对冲持仓"],
        ], venue.oms_type || "NETTING", value => {
          venue.oms_type = value;
          state.nautilusReview = null;
          refresh?.();
        }),
      );
      const balance = document.createElement("input");
      balance.type = "number";
      balance.min = "0";
      balance.step = "any";
      balance.inputMode = "decimal";
      balance.value = venue.starting_balance == null ? "" : String(venue.starting_balance);
      balance.placeholder = state.analysis.venues.length === 1
        ? context.t("留空时使用回测总资金") : context.t("填写此 Venue 的初始余额");
      balance.setAttribute("aria-label", `${context.t("Venue 初始余额")} ${index + 1}`);
      balance.addEventListener("change", () => {
        venue.starting_balance = balance.value.trim();
        delete venue.starting_balances;
        state.nautilusReview = null;
        refresh?.();
      });
      venueConfigFields.append(field(context, "初始余额", balance));
    }

    const remove = context.button(context.t("删除 Venue"), () => {
      const venueID = String(venue.name || "").trim().toUpperCase();
      state.analysis.venues.splice(index, 1);
      for (const route of state.analysis.strategy_venue_bindings) {
        route.venue_ids = (route.venue_ids || []).filter(value => (
          String(value).toUpperCase() !== venueID
        ));
      }
      state.nautilusReview = null;
      refresh?.();
    });

    venueConfigFields.append(remove);
    row.append(title, venueConfigFields);
    if (useNautilus) row.append(nativeConfigurationEditor(
      context, state, venue, refresh, nativeSchema, nativeSchemaError,
    ));
    return row;
  }

  function nativeConfigurationEditor(context, state, venue, refresh, nativeSchema, nativeSchemaError) {
    const details = document.createElement("details");
    details.className = "strategy-binding-native-config";
    const summary = document.createElement("summary");
    summary.textContent = context.t("Nautilus 原生撮合与账户参数");
    details.append(summary);
    if (!nativeSchema) {
      const message = document.createElement("p");
      message.textContent = nativeSchemaError || context.t("正在读取当前 Nautilus 版本的参数目录…");
      details.append(message);
      return details;
    }
    if (!nativeSchema.available) {
      const message = document.createElement("p");
      message.textContent = nativeSchema.reason || context.t("此服务上的 Nautilus 版本与参数目录不匹配");
      details.append(message);
      return details;
    }
    if (!venue.native_config) venue.native_config = structuredClone(nativeSchema.defaults);
    const config = venue.native_config;
    for (const section of nativeSchema.sections || []) {
      const group = document.createElement("fieldset");
      group.className = "strategy-binding-native-section";
      const legend = document.createElement("legend");
      legend.textContent = context.t(section.label || section.id);
      group.append(legend);
      for (const descriptor of nativeSchema.fields || []) {
        if (descriptor.section !== section.id || !fieldVisible(config, descriptor.visible_if)) continue;
        const control = nativeControl(context, config, descriptor, state, refresh);
        group.append(field(context, descriptor.label, control));
      }
      details.append(group);
    }
    for (const [name, reason] of Object.entries(nativeSchema.excluded || {})) {
      const note = document.createElement("p");
      note.className = "strategy-binding-native-note";
      note.textContent = context.t(`尚未映射 ${name}：${reason}`);
      details.append(note);
    }
    return details;
  }

  function nativeControl(context, config, descriptor, state, refresh) {
    const current = getPath(config, descriptor.path);
    const value = current === undefined ? descriptor.default : current;
    let control;
    if (descriptor.type === "boolean") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = Boolean(value);
    } else if (descriptor.type === "enum") {
      control = document.createElement("select");
      for (const optionValue of descriptor.options || []) {
        const optionSpec = typeof optionValue === "object" && optionValue !== null
          ? optionValue : {value: optionValue, label: optionValue};
        const option = document.createElement("option");
        option.value = String(optionSpec.value ?? "");
        option.textContent = context.t(String(optionSpec.label ?? optionSpec.value ?? ""));
        control.append(option);
      }
      control.value = value == null ? "" : String(value);
    } else if (descriptor.type === "money_array") {
      control = document.createElement("textarea");
      control.rows = Math.max(2, Math.min(4, (Array.isArray(value) ? value.length : 0) || 2));
      control.placeholder = context.t("100000 CNY");
      control.value = Array.isArray(value) ? value.join("\n") : "";
    } else if (["integer_array", "decimal_map", "rate_map"].includes(descriptor.type)) {
      control = document.createElement("textarea");
      control.rows = 2;
      control.value = descriptor.type === "integer_array"
        ? (Array.isArray(value) ? value.join(", ") : "")
        : JSON.stringify(value || {}, null, 2);
    } else {
      control = document.createElement("input");
      control.type = ["number", "integer", "decimal"].includes(descriptor.type) ? "number" : "text";
      if (control.type === "number") {
        control.step = descriptor.type === "integer" ? "1" : "any";
        if (descriptor.minimum !== undefined) control.min = String(descriptor.minimum);
        if (descriptor.maximum !== undefined) control.max = String(descriptor.maximum);
      }
      control.value = value == null ? "" : String(value);
    }
    if (descriptor.help) control.title = String(descriptor.help);
    const commit = () => {
      try {
        let next;
        if (descriptor.type === "boolean") next = control.checked;
        else if (descriptor.type === "integer_array") {
          const raw = control.value.trim();
          next = raw ? raw.split(/[,\s]+/).filter(Boolean).map(item => {
            const parsed = Number(item);
            if (!Number.isInteger(parsed) || parsed < 0) throw new Error("Bar 权重必须是非负整数");
            return parsed;
          }) : null;
        } else if (descriptor.type === "money_array") {
          const balances = control.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean);
          for (const item of balances) {
            if (!/^\d+(?:\.\d+)?\s+[A-Za-z]{3,8}$/.test(item)) {
              throw new Error("余额请按 '<金额> <币种>' 每行填写");
            }
          }
          next = balances.length ? balances : null;
        } else if (["decimal_map", "rate_map"].includes(descriptor.type)) {
          next = control.value.trim() ? JSON.parse(control.value) : {};
        } else if (descriptor.type === "integer") {
          const raw = control.value.trim();
          next = raw === "" ? nullableValue(descriptor) : Number(raw);
          if (next !== null && !Number.isInteger(next)) throw new Error("此项需要整数");
        } else if (descriptor.type === "decimal") {
          const raw = control.value.trim();
          next = raw === "" ? nullableValue(descriptor) : raw;
          if (next !== null && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(next)) {
            throw new Error("此项需要有限十进制数");
          }
        } else if (descriptor.type === "number") {
          const raw = control.value.trim();
          next = raw === "" ? nullableValue(descriptor) : Number(raw);
          if (next !== null && !Number.isFinite(next)) throw new Error("此项需要有限数字");
        } else {
          next = control.value.trim() || null;
        }
        setPath(config, descriptor.path, next);
        state.nautilusReview = null;
        refresh?.();
      } catch (error) {
        context.showNotice?.(`${context.t("参数格式错误")}: ${error.message}`, true);
      }
    };
    control.addEventListener("change", commit);
    if (control.tagName === "TEXTAREA") control.addEventListener("blur", commit);
    return control;
  }

  function fieldVisible(config, conditions) {
    if (!conditions || typeof conditions !== "object") return true;
    return Object.entries(conditions).every(([path, values]) => (
      (Array.isArray(values) ? values : [values]).includes(getPath(config, path))
    ));
  }

  function nullableValue(descriptor) {
    if (descriptor.nullable) return null;
    if (descriptor.default !== undefined) return descriptor.default;
    throw new Error("此项不能为空");
  }

  function getPath(root, path) {
    return String(path || "").split(".").reduce((value, key) => value?.[key], root);
  }

  function setPath(root, path, next) {
    const parts = String(path || "").split(".");
    let target = root;
    for (const key of parts.slice(0, -1)) target = target[key] ||= {};
    target[parts.at(-1)] = next;
  }

  function loadNativeSchema(context, state) {
    if (state.nautilusCapabilities?.simulated_venue_config) {
      return Promise.resolve(state.nautilusCapabilities.simulated_venue_config);
    }
    const request = window.FTNautilusConfiguration?.loadCapabilities
      ? window.FTNautilusConfiguration.loadCapabilities(context)
      : context.api(context.servicePath("/api/nautilus/capabilities"));
    return request.then(result => {
      state.nautilusCapabilities = result;
      const schema = result?.simulated_venue_config;
      if (!schema) throw new Error("服务端未提供 Nautilus Venue 参数目录");
      return schema;
    });
  }

  function selectField(context, label, options, value, onChange) {
    const select = document.createElement("select");
    select.setAttribute("aria-label", context.t(label));
    for (const [optionValue, optionLabel] of options) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = context.t(optionLabel);
      select.append(option);
    }
    select.value = value;
    select.addEventListener("change", () => onChange(select.value));
    return field(context, label, select);
  }

  function bindingRow(context, state, group, refresh) {
    const route = state.analysis.strategy_venue_bindings.find(item => (
      item.strategy_id === group.id
    ));
    const venuePicker = FTMultiSelectFilter.create(context, {
      title: context.t("绑定 Venue"),
      className: "strategy-binding-venue-picker",
      compact: false,
      multi: true,
      items: state.analysis.venues.filter(item => String(item.name || "").trim())
        .map(item => ({
          value: String(item.name).trim().toUpperCase(),
          label: `${item.name} · ${item.account_type || "MARGIN"}`,
          description: context.t("该策略在此场所使用共享的 Venue 账户与撮合状态"),
        })),
      selected: route?.venue_ids || [],
      onChange: values => {
        if (route) route.venue_ids = [...new Set(values.map(value => String(value).toUpperCase()))];
        state.nautilusReview = null;
        refresh?.();
      },
    });

    const controls = document.createElement("div");
    controls.className = "strategy-binding-controls";
    controls.append(field(context, "Venue 路由", venuePicker.element));
    const row = document.createElement("article");
    row.className = "strategy-binding-row";
    const title = document.createElement("h4");
    title.textContent = `${context.t("策略实例")} · ${group.name || group.id}`;
    row.append(title, controls);
    return row;
  }

  function field(context, label, control) {
    return FTTestFieldRow.create(context.t(label), control);
  }

  function nextVenueName(venues) {
    let index = 1;
    const existing = new Set(venues.map(item => String(item.name || "").toUpperCase()));
    while (existing.has(`VENUE${index}`)) index += 1;
    return `VENUE${index}`;
  }

  window.FTStrategyBindingPanel = Object.freeze({render});
})();
