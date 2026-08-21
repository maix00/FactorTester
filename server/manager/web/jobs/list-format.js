(() => {
  const text = value => value == null ? "" : String(value);
  const scalar = value => value == null
    || ["string", "number", "boolean"].includes(typeof value);
  const date = value => value ? FTUI.formatDate(value) : "";
  const table = (...args) => FTUI.table(...args);

  function statusTitle(value, context) {
    const title = {
      succeeded: "成功", failed: "失败", running: "运行中", queued: "排队中",
      planning: "规划中", cancelled: "已取消", paused: "已暂停",
      submitted: "已提交", created: "已创建",
      analyzing: "分析中",
      awaiting_confirmation: "等待确认",
    }[value];
    return title ? context.t(title) : value || context.t("未知");
  }

  function statusPill(value, context) {
    const pill = document.createElement("span");
    const normalized = String(value || "unknown").toLowerCase()
      .replace(/[^a-z0-9_-]/g, "-");
    pill.className = `job-status ${normalized || "unknown"}`;
    pill.textContent = statusTitle(value, context);
    return pill;
  }

  function statusCell(job, context) {
    const active = Number(job.supplemental_active_count || 0);
    return statusPill(active > 0 ? "analyzing" : job.status, context);
  }

  function kindTitle(value, context) {
    const title = {
      ic: "IC 测试", ic_test: "IC 测试", "ic-test": "IC 测试",
      backtest: "回测", group_backtest: "回测", test: "测试",
    }[String(value || "").toLowerCase()];
    return title ? context.t(title) : value || context.t("测试");
  }

  function jobPort(value) {
    const port = Number(value);
    return Number.isInteger(port) && port > 0 ? port : null;
  }

  function formatBytes(value) {
    const bytes = Math.max(0, Number(value) || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
    return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
  }

  function taskHash(job) {
    return String(
      job.run_spec_hash || job.job_spec_hash || job.job_id || "",
    ).replace(/^sha256:/i, "");
  }

  function taskTitle(job, context) {
    const category = kindTitle(job.kind, context);
    return `${category} · ${String(job.task_name || "").trim() || taskHash(job)}`;
  }

  function taskCell(job, context) {
    const root = document.createElement("div");
    root.className = "job-task-cell";
    const heading = document.createElement("strong");
    heading.textContent = taskTitle(job, context);
    root.append(heading);
    if (job.local_run || job.execution_mode === "local") {
      const mode = document.createElement("small");
      mode.className = "job-local-run-label";
      mode.textContent = context.t("本地运行");
      root.append(mode);
    }
    const name = String(job.task_name || "").trim();
    const hash = taskHash(job);
    if (name && hash) {
      const subtitle = document.createElement("small");
      subtitle.textContent = hash;
      root.append(subtitle);
    }
    return root;
  }

  function displayProfile(job, context) {
    const profile = job.server_context?.profile_name
      || job.acting_profile_name
      || job.server_context?.profile
      || job.profile || "";
    const owner = job.owner || job.server_context?.owner || "";
    if (owner && profile) return `${owner}（${profile}）`;
    return profile || owner || context.t("未知");
  }

  function serverLabel(job, context) {
    const serverID = String(job.server_id || "").trim();
    const host = String(job.server_host || "").trim();
    if (!serverID || serverID === "local") return context.t("本机");
    return host ? serverID + " · " + host : serverID;
  }

  function referenceURL(kind, target) {
    if (!target) return "";
    const value = String(target);
    if (value.startsWith("factortester://")) return value;
    return `factortester://${String(kind || "reference").replaceAll("_", "-")}/${encodeURIComponent(value)}`;
  }

  function artifactCell(job, prefix, context) {
    const root = document.createElement("div");
    root.className = "job-artifact-cell";
    const count = document.createElement("strong");
    count.textContent = String(job[`${prefix}_artifact_count`] || 0);
    const bytes = document.createElement("small");
    bytes.textContent = formatBytes(job[`${prefix}_artifact_bytes`] || 0);
    root.append(count, bytes);
    return root;
  }

  window.FTJobListFormat = Object.freeze({
    artifactCell, date, displayProfile, formatBytes, jobPort, kindTitle,
    referenceURL, scalar, serverLabel, statusCell, statusPill, table, taskCell, taskHash,
    taskTitle, text,
  });
})();
