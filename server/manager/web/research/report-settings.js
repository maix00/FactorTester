(() => {
  function labelledToggle(context, title, detail, checked) {
    const row = document.createElement("label");
    row.className = "setting-row";
    const copy = document.createElement("span");
    const heading = document.createElement("b");
    heading.textContent = context.t(title);
    const note = document.createElement("small");
    note.textContent = context.t(detail);
    copy.append(heading, note);
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(checked);
    row.append(copy, input);
    return {row, input};
  }

  function authorizedUserRow(context, value = "") {
    const row = document.createElement("div");
    row.className = "authorized-user";
    const input = document.createElement("input");
    input.placeholder = context.t("完整用户名");
    input.value = value;
    const remove = FTUI.iconButton(
      context, "trash", "移除授权用户", () => row.remove(),
    );
    row.append(input, remove);
    return row;
  }

  async function ownerSettings(context, report) {
    const result = await context.api("/api/research-publications/settings");
    const publicationID = String(report?.publication_id || report?.source_ref || "")
      .replace(/^(?:local|server):/, "");
    return (result.reports || []).find(item => (
      publicationID && item.publication_id === publicationID
    )) || (result.reports || []).find(item => (
      item.report_id === report?.report_id
      && (!report?.branch_ref || item.branch_ref === report.branch_ref)
    ));
  }

  async function open(context, report, onSaved = null) {
    let settings;
    try {
      settings = await ownerSettings(context, report);
    } catch (error) {
      context.showNotice?.(error.message || String(error), true);
      return;
    }
    if (!settings) {
      context.showNotice?.(
        context.t("报告尚未上传；首次上传后才能设置服务器同步"), true,
      );
      return;
    }
    const dialog = document.createElement("dialog");
    dialog.className = "ft-dialog research-report-settings-dialog";
    const form = document.createElement("form");
    form.className = "dialog-card wide";
    form.addEventListener("submit", event => event.preventDefault());
    const heading = document.createElement("h2");
    heading.textContent = context.t("研究报告设置");
    const close = FTUI.iconButton(context, "xmark", "关闭", () => dialog.close());
    close.classList.add("dialog-close");
    form.append(heading, close);

    const note = document.createElement("p");
    note.className = "secondary";
    note.textContent = context.t(
      "自动上传开启后，获授权用户可在 Web 或客户端读取服务器镜像；关闭后仅保留服务器已有版本",
    );
    form.append(note);
    const list = document.createElement("div");
    list.className = "settings-list";
    const automatic = labelledToggle(
      context, "自动上传",
      "本地报告更新后，将结构化报告镜像上传到当前服务器",
      settings.auto_sync,
    );
    const relay = labelledToggle(
      context, "本地文件中继",
      "仅在所有者客户端在线且访问者获授权时读取未上传的本地文件",
      settings.relay_local_files,
    );
    const visibilityRow = document.createElement("label");
    visibilityRow.className = "setting-row";
    const visibilityCopy = document.createElement("span");
    visibilityCopy.innerHTML = `<b>${context.t("访问范围")}</b><small>${context.t("仅自己、指定用户或全体用户")}</small>`;
    const visibility = document.createElement("select");
    [
      ["private", "仅自己"], ["authorized", "指定用户可见"],
      ["public", "全体用户共享"],
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value; option.textContent = context.t(label);
      option.selected = value === settings.visibility;
      visibility.append(option);
    });
    visibilityRow.append(visibilityCopy, visibility);
    list.append(automatic.row, visibilityRow, relay.row);
    form.append(list);

    const users = document.createElement("section");
    users.className = "authorized-users";
    const usersHeading = document.createElement("div");
    usersHeading.className = "section-heading";
    const usersTitle = document.createElement("h3");
    usersTitle.textContent = context.t("授权用户");
    const add = FTUI.iconButton(
      context, "plus", "添加授权用户",
      () => usersList.append(authorizedUserRow(context)),
    );
    usersHeading.append(usersTitle, add);
    const usersList = document.createElement("div");
    usersList.className = "authorized-user-list";
    (settings.authorized_users || []).forEach(value => (
      usersList.append(authorizedUserRow(context, value))
    ));
    users.append(usersHeading, usersList);
    form.append(users);

    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const cancel = context.button(context.t("取消"), () => dialog.close());
    cancel.classList.add("secondary");
    const save = context.button(context.t("保存"), async () => {
      save.disabled = true;
      try {
        const authorizedUsers = [...usersList.querySelectorAll("input")]
          .map(input => input.value.trim()).filter(Boolean);
        await context.api("/api/research-publications/settings", {
          method: "POST",
          body: JSON.stringify({
            publication_id: settings.publication_id,
            report_id: settings.report_id,
            auto_sync: automatic.input.checked,
            visibility: visibility.value,
            relay_local_files: relay.input.checked,
            authorized_users: authorizedUsers,
          }),
        });
        dialog.close();
        await onSaved?.();
      } catch (error) {
        context.showNotice?.(error.message || String(error), true);
        save.disabled = false;
      }
    });
    save.classList.add("primary");
    actions.append(cancel, save);
    form.append(actions);
    dialog.append(form);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    document.body.append(dialog);
    dialog.showModal();
  }

  window.FTResearchReportSettings = Object.freeze({open});
})();
