(() => {
  let progressAbort = null;

  function statusTitle(value, context) {
    const title = {
      succeeded: "成功", failed: "失败", running: "运行中", queued: "排队中",
      planning: "规划中", cancelled: "已取消", paused: "已暂停",
      submitted: "已提交", created: "已创建",
    }[value];
    return title ? context.t(title) : value || context.t("未知");
  }

  function progressView(context, status) {
    const root = document.createElement("section");
    root.className = "job-progress job-section";
    const header = document.createElement("div");
    header.className = "job-progress-header";
    const heading = document.createElement("h2");
    heading.textContent = context.t("任务进度");
    const statusLabel = document.createElement("span");
    statusLabel.className = "job-progress-status";
    statusLabel.textContent = statusTitle(status, context);
    header.append(heading, statusLabel);
    const bar = document.createElement("progress");
    bar.max = 100;
    const current = document.createElement("div");
    current.className = "job-progress-current";
    const currentFields = {};
    [
      ["phase", "当前阶段"], ["flow", "当前流程"], ["timestamp", "业务时间"],
      ["count", "阶段计数"], ["percent", "总进度"],
    ].forEach(([key, text]) => {
      const field = document.createElement("span");
      field.className = `job-progress-current-field ${key}`;
      const name = document.createElement("small");
      name.textContent = context.t(text);
      const value = document.createElement("strong");
      value.textContent = "—";
      field.append(name, value);
      current.append(field);
      currentFields[key] = value;
    });
    const label = document.createElement("span");
    label.className = "job-progress-message";
    label.textContent = context.t("等待任务进度");
    const phaseTrack = document.createElement("div");
    phaseTrack.className = "job-progress-phases";
    const history = document.createElement("details");
    history.className = "job-progress-history";
    const historySummary = document.createElement("summary");
    historySummary.textContent = context.t("阶段记录");
    const historyRows = document.createElement("div");
    historyRows.className = "job-progress-history-rows";
    history.append(historySummary, historyRows);
    root.append(header, bar, current, label, phaseTrack, history);
    if (status === "succeeded") bar.value = 100;
    else if (!["running", "planning"].includes(status)) bar.value = 0;
    return {
      root, bar, current, currentFields, label, phaseTrack, historyRows,
      statusLabel, context,
      progressState: {
        lastSeq: 0,
        percent: status === "succeeded" ? 100 : null,
        phaseIndex: new Map(),
        phaseCount: 0,
        phases: [],
        activePhase: "",
        activeFlow: "",
        timestamp: "",
        message: "",
        currentInfo: {},
        phaseHistory: {},
        terminal: ["succeeded", "failed", "cancelled"].includes(status),
      },
    };
  }

  function stateOf(view) {
    if (!view.progressState) {
      view.progressState = {
        lastSeq: 0, percent: null, phaseIndex: new Map(), phaseCount: 0,
        phases: [], activePhase: "", activeFlow: "", timestamp: "", message: "",
        currentInfo: {}, phaseHistory: {}, terminal: false,
      };
    }
    view.progressState.phases ||= [];
    view.progressState.phaseIndex ||= new Map();
    view.progressState.phaseHistory ||= {};
    view.progressState.currentInfo ||= {};
    return view.progressState;
  }

  function registerPhases(state, phases) {
    if (!Array.isArray(phases) || !phases.length) return;
    const byKey = new Map((state.phases || []).map(item => [item.key, item]));
    phases.forEach((raw, phaseOrder) => {
      const source = typeof raw === "object" && raw ? raw : {key: raw};
      const key = String(source.key || source.phase || "").trim();
      if (!key) return;
      const previous = byKey.get(key) || {key, flows: [], order: byKey.size};
      const flows = new Map((previous.flows || []).map(item => [item.key, item]));
      (Array.isArray(source.flows) ? source.flows : []).forEach((flow, flowOrder) => {
        const flowKey = String(flow?.flow_key || flow?.key || "").trim();
        if (!flowKey) return;
        flows.set(flowKey, {
          key: flowKey,
          label: String(flow.flow_label || flow.flow_name || flowKey),
          eventKind: String(flow.event_kind || ""),
          order: Number(flow.display_order ?? flowOrder),
        });
      });
      byKey.set(key, {
        ...previous,
        key,
        label: String(source.label || previous.label || key),
        weight: Math.max(0, Number(source.weight ?? previous.weight ?? 1)),
        order: previous.order ?? phaseOrder,
        flows: [...flows.values()].sort((a, b) => a.order - b.order),
      });
    });
    state.phases = [...byKey.values()].sort((a, b) => a.order - b.order);
    const keys = state.phases.map(item => item.key);
    if (!keys.length) return;
    state.phaseIndex = new Map(keys.map((key, index) => [key, index]));
    state.phaseCount = keys.length;
  }

  function terminalStatus(event, source, payload) {
    const status = String(source.status || payload?.status || "").trim();
    if (["succeeded", "failed", "cancelled"].includes(status)) return status;
    if (event === "result") return "succeeded";
    if (event === "error") return "failed";
    return "";
  }

  function measuredPercent(state, source, event) {
    const completed = Number(source.completed);
    const total = Number(source.total);
    const explicit = Number.isFinite(Number(source.percent)) ? Number(source.percent) : null;
    if (explicit != null && (
      source.percent_scope === "global"
      || (event === "signal_progress" && source.percent_scope !== "phase")
    )) return explicit;
    const local = explicit != null ? explicit
      : Number.isFinite(completed) && Number.isFinite(total) && total > 0 ? completed / total * 100 : null;
    if (local == null) return null;
    const phase = String(source.phase || "").trim();
    if (state.phases?.length && state.phaseIndex.has(phase)) {
      const totalWeight = state.phases.reduce((sum, item) => sum + item.weight, 0) || 1;
      const before = state.phases.slice(0, state.phaseIndex.get(phase))
        .reduce((sum, item) => sum + item.weight, 0);
      const weight = state.phases[state.phaseIndex.get(phase)]?.weight || 0;
      return (before + weight * Math.max(0, Math.min(100, local)) / 100)
        * 100 / totalWeight;
    }
    return local;
  }

  function phaseLabel(state, key) {
    return state.phases?.find(item => item.key === key)?.label || key;
  }

  function flowLabel(state, phase, key) {
    return state.phases?.find(item => item.key === phase)?.flows
      ?.find(item => item.key === key)?.label || "";
  }

  function translated(view, value) {
    return value ? view.context?.t?.(value) || value : "";
  }

  function updatePhaseRecord(state, source, status) {
    const phase = String(source.phase || "").trim();
    if (!phase) return null;
    const previousPhase = state.activePhase;
    const previousIndex = state.phaseIndex.get(previousPhase);
    const nextIndex = state.phaseIndex.get(phase);
    if (
      previousPhase && previousPhase !== phase
      && Number.isInteger(previousIndex) && Number.isInteger(nextIndex)
      && nextIndex > previousIndex && state.phaseHistory[previousPhase]
    ) {
      state.phaseHistory[previousPhase].status = "completed";
    }
    const previous = state.phaseHistory[phase] || {
      phase, label: phaseLabel(state, phase), flow: "", timestamp: "",
      completed: 0, total: 0, message: "", status: "pending",
    };
    const completed = Number(source.completed);
    const total = Number(source.total);
    const record = {
      ...previous,
      label: phaseLabel(state, phase) || previous.label,
      flow: String(source.flow_label || flowLabel(
        state, phase, String(source.flow_key || ""),
      ) || previous.flow),
      timestamp: String(source.timestamp || previous.timestamp),
      completed: Number.isFinite(completed)
        ? Math.max(previous.completed || 0, completed) : previous.completed || 0,
      total: Number.isFinite(total)
        ? Math.max(previous.total || 0, total) : previous.total || 0,
      message: String(source.message || previous.message),
      status: status === "failed" ? "failed" : "active",
    };
    if (record.total > 0 && record.completed >= record.total) record.status = "completed";
    state.phaseHistory[phase] = record;
    return record;
  }

  function renderCurrentInfo(view, state) {
    const record = state.phaseHistory[state.activePhase] || {};
    const info = {
      phase: translated(view, phaseLabel(state, state.activePhase)),
      flow: translated(view, flowLabel(state, state.activePhase, state.activeFlow)
        || record.flow),
      timestamp: state.timestamp || record.timestamp || "",
      count: record.total > 0 ? `${record.completed}/${record.total}` : "",
      percent: state.percent == null ? "" : `${state.percent.toFixed(1)}%`,
    };
    state.currentInfo = info;
    Object.entries(view.currentFields || {}).forEach(([key, node]) => {
      node.textContent = info[key] || "—";
    });
  }

  function renderHistory(view, state) {
    if (!view.historyRows || typeof document === "undefined") return;
    const records = (state.phases || []).map(phase => state.phaseHistory[phase.key])
      .filter(Boolean);
    const nodes = records.map(record => {
      const row = document.createElement("div");
      row.className = `job-progress-history-row ${record.status}`;
      const values = [
        translated(view, record.label),
        record.total > 0 ? `${record.completed}/${record.total}` : "—",
        translated(view, {
          completed: "已完成", active: "进行中", failed: "失败", pending: "等待中",
        }[record.status] || record.status),
        translated(view, record.flow),
        record.timestamp || "—",
        record.message || "—",
      ];
      values.forEach(value => {
        const cell = document.createElement("span");
        cell.textContent = value;
        cell.title = value;
        row.append(cell);
      });
      return row;
    });
    view.historyRows.replaceChildren(...nodes);
  }

  function renderActivity(view, state) {
    if (!view.phaseTrack || typeof document === "undefined") return;
    const activeIndex = state.phaseIndex.get(state.activePhase) ?? -1;
    const nodes = (state.phases || []).map((phase, index) => {
      const node = document.createElement("div");
      node.className = "job-progress-phase";
      if (index < activeIndex || state.terminal && state.percent === 100) node.classList.add("done");
      if (index === activeIndex && !state.terminal) node.classList.add("active");
      const title = document.createElement("strong");
      title.textContent = view.context?.t?.(phase.label) || phase.label;
      node.append(title);
      if (phase.flows.length) {
        const flows = document.createElement("span");
        flows.className = "job-progress-flow-list";
        phase.flows.forEach(flow => {
          const item = document.createElement("span");
          item.textContent = view.context?.t?.(flow.label) || flow.label;
          if (phase.key === state.activePhase && flow.key === state.activeFlow) {
            item.className = "active";
          }
          flows.append(item);
        });
        node.append(flows);
      }
      return node;
    });
    view.phaseTrack.replaceChildren(...nodes);
  }

  function updateProgress(view, payload) {
    const state = stateOf(view);
    if (state.terminal) return state;
    const event = String(payload?.event || "message");
    const wrapped = payload?.latest_progress;
    const source = wrapped?.data || payload?.data || payload || {};
    const effectiveEvent = String(wrapped?.event || event);
    const seq = Number(payload?.seq ?? wrapped?.seq ?? 0);
    if (Number.isFinite(seq) && seq > 0) {
      if (seq <= state.lastSeq) return state;
      state.lastSeq = seq;
    }
    registerPhases(
      state,
      source.phases || source.manifest?.data?.phases || source.manifest?.phases,
    );
    const status = terminalStatus(event, source, payload);
    const measured = measuredPercent(state, source, effectiveEvent);
    if (measured != null) {
      state.percent = Math.max(state.percent ?? 0, Math.max(0, Math.min(100, measured)));
    }
    if (status === "succeeded") state.percent = 100;
    if (status) {
      state.percent ??= 0;
      state.terminal = true;
    }

    // Once determinate, heartbeats and count-less phase messages must not put
    // the native progress element back into its indeterminate animation.
    if (state.percent != null && view.bar.value !== state.percent) view.bar.value = state.percent;
    else if (state.percent == null && !state.terminal) view.bar.removeAttribute("value");
    const phase = String(source.phase || state.activePhase || "");
    updatePhaseRecord(state, source, status);
    if (phase && !["succeeded", "failed", "cancelled"].includes(phase)) {
      state.activePhase = phase;
    }
    if (effectiveEvent === "activity") {
      state.activeFlow = String(source.flow_key || "");
      state.timestamp = String(source.timestamp || "");
      state.message = String(source.message || "");
    } else if (source.message) {
      state.message = String(source.message);
    }
    const semantic = state.message
      || [phaseLabel(state, state.activePhase), flowLabel(
        state, state.activePhase, state.activeFlow,
      )].filter(Boolean).join(" · ")
      || statusTitle(status, view.context || {t: value => value});
    if (semantic && view.label.textContent !== semantic) view.label.textContent = semantic;
    if (status && view.statusLabel) {
      view.statusLabel.textContent = statusTitle(status, view.context);
    }
    if (status === "succeeded") {
      Object.values(state.phaseHistory).forEach(record => { record.status = "completed"; });
    }
    renderCurrentInfo(view, state);
    renderActivity(view, state);
    renderHistory(view, state);
    return state;
  }

  async function watchProgress(context, jobID, portQuery, view, options = {}) {
    const controller = new AbortController();
    progressAbort = controller;
    let streamError = null;
    try {
      const cursor = stateOf(view).lastSeq;
      const separator = portQuery ? "&" : "?";
      const path = `/api/jobs/${encodeURIComponent(jobID)}/stream${portQuery}`
        + (cursor > 0 ? `${separator}after=${encodeURIComponent(cursor)}` : "");
      const response = await context.raw(path, {signal: controller.signal});
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!controller.signal.aborted) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        frames.forEach(frame => {
          const event = frame.split(/\r?\n/).find(line => line.startsWith("event:"))
            ?.slice(6).trim() || "message";
          const id = Number(frame.split(/\r?\n/).find(line => line.startsWith("id:"))
            ?.slice(3).trim() || 0);
          const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
            .map(line => line.slice(5).trim()).join("\n");
          if (!data) return;
          try {
            const raw = JSON.parse(data);
            const payload = {event, seq: id, data: raw};
            updateProgress(view, payload);
            options.onPayload?.(payload);
          } catch (_) {}
        });
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        streamError = error;
        view.label.textContent = context.t("实时进度暂不可用");
      }
    } finally {
      const terminal = stateOf(view).terminal;
      if (!controller.signal.aborted && !terminal) {
        view.label.textContent = context.t("实时进度暂不可用");
      }
      if (progressAbort === controller) progressAbort = null;
      // Replacing a watcher or leaving the page is not task completion and
      // must not launch an obsolete cross-server detail read. A terminal
      // payload deliberately aborts its own stream and still converges once.
      if (!controller.signal.aborted || terminal) {
        options.onComplete?.({
          aborted: controller.signal.aborted,
          error: streamError,
          terminal,
        });
      }
    }
  }

  function stopProgress() {
    progressAbort?.abort();
    progressAbort = null;
  }

  window.FTJobProgress = {progressView, stopProgress, updateProgress, watchProgress};
})();
