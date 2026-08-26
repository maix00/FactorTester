(() => {
  const PAGE_SIZE = 20;

  function subjectRef(object) {
    const kind = String(object.objectKind || "");
    if (kind === "factor") {
      const fingerprint = String(object.selfFormulaFingerprint || "").trim();
      return fingerprint ? `factor-formula:v1:${fingerprint}` : "";
    }
    if (kind === "family") {
      const fingerprint = String(object.familyFormulaFingerprint || "").trim();
      return fingerprint ? `factor-family-formula:v1:${fingerprint}` : "";
    }
    return String(object.objectRef || "").trim();
  }

  function create(context, object = {}) {
    const mount = document.createElement("section");
    mount.className = "factor-object-job-table";
    let loaded = false;
    let loading = false;
    let page = 1;
    let requestVersion = 0;

    async function load(requestedPage = page) {
      if (loading) return;
      loading = true;
      const version = ++requestVersion;
      page = Math.max(1, Number(requestedPage) || 1);
      const objectRef = subjectRef(object);
      if (!objectRef) {
        mount.replaceChildren(FTUI.empty(
          context.t("暂无相关测试任务"),
          context.t("此对象尚未登记公式指纹"),
        ));
        loaded = true;
        loading = false;
        return;
      }
      mount.replaceChildren(FTUI.loading(context.t("正在读取相关测试任务…")));
      try {
        const query = new URLSearchParams({
          scope: !context.session || context.session.role === "super_admin"
            ? "server" : "visible",
          page: String(page),
          limit: String(PAGE_SIZE),
          object_kind: String(object.objectKind || ""),
          object_ref: objectRef,
        });
        const payload = await context.api(`/api/jobs?${query.toString()}`);
        // This component can remain mounted in a cached left-navigation tab.
        // Its page-level route token is stale after the tab is restored, but
        // the component itself is still live and must be allowed to finish
        // lazy loading.  Only a newer request from this instance supersedes
        // the response.
        if (version !== requestVersion) return;
        render(payload || {});
        loaded = true;
      } catch (error) {
        if (version !== requestVersion) return;
        const failure = FTUI.empty(
          context.t("相关测试任务读取失败"),
          error.message || context.t("请稍后重试"),
        );
        failure.append(context.button(
          context.t("重试"), () => { void load(page); }, context.t("重试"),
        ));
        mount.replaceChildren(failure);
      } finally {
        if (version === requestVersion) loading = false;
      }
    }

    function render(payload) {
      const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      if (!jobs.length) {
        mount.replaceChildren(FTUI.empty(
          context.t("暂无相关测试任务"),
          context.t("使用此对象提交的测试任务会显示在这里"),
        ));
        return;
      }
      const view = FTUI.pagedTable([
        context.t("任务"), context.t("测试类型"), context.t("所有者"),
        context.t("更新时间"), context.t("状态"),
      ], jobs.map(job => [
        job.task_name || job.job_id,
        context.t(job.kind || ""),
        job.acting_profile_name || job.owner || "—",
        FTUI.formatDate?.(job.updated_at) || String(job.updated_at || ""),
        context.t(job.status || ""),
      ]), {
        remote: true,
        page: Number(payload.page || page),
        pageSize: Number(payload.page_size || PAGE_SIZE),
        total: Number(payload.total || jobs.length),
        previousLabel: context.t("上一页"),
        nextLabel: context.t("下一页"),
        pageLabel: (current, total) => context.t("第 %lld / %lld 页")
          .replace("%lld", String(current)).replace("%lld", String(total)),
        totalLabel: total => context.t("共 %lld 个任务").replace("%lld", String(total)),
        onPageChange: next => { void load(next); },
      });
      [...view.body.rows].forEach((row, index) => {
        row.dataset.href = "true";
        row.tabIndex = 0;
        const open = () => {
          context.navigate(`/jobs/${encodeURIComponent(jobs[index].job_id)}`);
        };
        row.addEventListener("click", open);
        row.addEventListener("keydown", event => {
          if (!["Enter", " "].includes(event.key)) return;
          event.preventDefault();
          open();
        });
      });
      mount.replaceChildren(view.shell);
    }

    return Object.freeze({
      mount,
      load: () => loaded ? Promise.resolve() : load(1),
      refresh: () => {
        loaded = false;
        requestVersion += 1;
        loading = false;
        return load(page);
      },
    });
  }

  window.FTFactorObjectJobs = Object.freeze({create});
})();
