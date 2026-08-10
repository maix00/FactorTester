(() => {
  function tokens(value) {
    const source = Array.isArray(value) ? value : String(value || "").split(/[\s,，;；]+/);
    return source.map(item => String(item).trim()).filter(Boolean);
  }

  function unique(values) {
    return values.filter((value, index) => values.indexOf(value) === index);
  }

  function normalizeHorizon(value) {
    const raw = value && typeof value === "object" ? value : {};
    const sampling = String(raw.sampling || "").toLowerCase();
    if (sampling === "scale_aware" || sampling === "auto") {
      return {sampling: "scale_aware"};
    }
    const bases = unique(tokens(raw.bases || ["signal"]));
    const multipliers = unique(tokens(raw.multipliers || [1])
      .map(Number).filter(item => Number.isInteger(item) && item > 0));
    return {
      sampling: "explicit",
      bases: bases.length ? bases : ["signal"],
      multipliers: multipliers.length ? multipliers : [1],
    };
  }

  function normalizeDelays(value) {
    const delays = unique(tokens(value).map(Number)
      .filter(item => Number.isInteger(item) && item >= 0));
    return delays.length ? delays : [0];
  }

  function normalizeDecayLags(value) {
    const lags = unique(tokens(value).map(Number)
      .filter(item => Number.isInteger(item) && item > 0));
    return lags.length ? lags : [5];
  }

  function normalizeSettingValues(manifest, values) {
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const target = field?.serialization?.storage_key || key;
      if (!Object.prototype.hasOwnProperty.call(values || {}, target)) continue;
      if (field.control_template === "ic_horizon_grid") {
        values[target] = normalizeHorizon(values[target]);
      } else if (field.control_template === "ic_delay_grid") {
        values[target] = normalizeDelays(values[target]);
      } else if (field.control_template === "ic_decay_grid") {
        values[target] = normalizeDecayLags(values[target]);
      }
    }
    return values;
  }

  function field(labelText, value, placeholder, disabled, onChange) {
    const label = document.createElement("label");
    const title = document.createElement("small");
    title.textContent = labelText;
    const input = document.createElement("input");
    input.type = "text";
    input.value = value;
    input.placeholder = placeholder;
    input.disabled = disabled;
    input.addEventListener("change", () => onChange(input));
    label.append(title, input);
    return label;
  }

  function renderHorizon({value, context, disabled, onChange}) {
    const normalized = normalizeHorizon(value);
    let explicit = normalized.sampling === "explicit"
      ? normalized : {sampling: "explicit", bases: ["signal"], multipliers: [1]};
    const root = document.createElement("div");
    root.className = "ic-grid-control";
    const mode = document.createElement("select");
    for (const [key, label] of [
      ["scale_aware", context.t("按因子频率自动生成")],
      ["explicit", context.t("手动冻结收益期网格")],
    ]) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = label;
      mode.append(option);
    }
    mode.value = normalized.sampling;
    mode.disabled = disabled;
    const manual = document.createElement("div");
    manual.className = "ic-grid-manual";
    const bases = field(
      context.t("收益期基准"), explicit.bases.join(", "),
      context.t("例如 signal, 1m, 1d"), disabled,
      input => {
        explicit = normalizeHorizon({...explicit, bases: tokens(input.value)});
        input.value = explicit.bases.join(", ");
        onChange(explicit);
      },
    );
    const multiples = field(
      context.t("正整数倍数"), explicit.multipliers.join(", "),
      context.t("例如 1, 5, 20"), disabled,
      input => {
        explicit = normalizeHorizon({...explicit, multipliers: tokens(input.value)});
        input.value = explicit.multipliers.join(", ");
        onChange(explicit);
      },
    );
    manual.append(bases, multiples);
    manual.hidden = normalized.sampling !== "explicit";
    mode.addEventListener("change", () => {
      manual.hidden = mode.value !== "explicit";
      onChange(mode.value === "explicit" ? explicit : {sampling: "scale_aware"});
    });
    root.append(mode, manual);
    return root;
  }

  function renderDelays({value, context, disabled, onChange}) {
    const root = document.createElement("div");
    root.className = "ic-grid-control";
    const delays = field(
      context.t("信号 bar 延迟"), normalizeDelays(value).join(", "),
      context.t("例如 0, 1, 2"), disabled,
      input => {
        const next = normalizeDelays(input.value);
        input.value = next.join(", ");
        onChange(next);
      },
    );
    const note = document.createElement("small");
    note.textContent = context.t("每个延迟都会与每个收益期组合计算");
    root.append(delays, note);
    return root;
  }

  function renderDecayLags({value, context, disabled, onChange}) {
    const root = document.createElement("div");
    root.className = "ic-grid-control";
    const lags = field(
      context.t("正整数 Lag"), normalizeDecayLags(value).join(", "),
      context.t("例如 1, 2, 5, 10"), disabled,
      input => {
        const next = normalizeDecayLags(input.value);
        input.value = next.join(", ");
        onChange(next);
      },
    );
    const note = document.createElement("small");
    note.textContent = context.t("用于 IC 序列自相关与衰减诊断，不改变入场延迟");
    root.append(lags, note);
    return root;
  }

  window.FTICHorizonSettings = Object.freeze({
    normalizeDecayLags, normalizeDelays, normalizeHorizon, normalizeSettingValues,
    renderDecayLags, renderDelays, renderHorizon, tokens,
  });
})();
