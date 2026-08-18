(() => {
  function section(context, title) {
    const root = document.createElement("section");
    root.className = "job-section profile-agent-skills";
    const heading = document.createElement("h2");
    heading.textContent = context.t(title);
    root.append(heading);
    return root;
  }

  function message(context, title, detail = "") {
    return FTUI.empty(context.t(title), detail ? context.t(detail) : "");
  }

  async function render(context, profile, refresh) {
    const root = section(context, "智能体 Skill");
    const note = document.createElement("p");
    note.className = "settings-muted";
    note.textContent = context.t(
      "Skill 由服务器管理员预装；Profile 只能勾选服务器已经提供的研究 Skill。",
    );
    root.append(note);

    const runtimeKind = String(profile.runtime?.runtime_kind || "");
    if (runtimeKind !== "server") {
      root.append(message(
        context,
        "当前 Profile 不是服务器运行",
        "客户端运行的 Skill 由客户端随应用管理。",
      ));
      return root;
    }

    const body = document.createElement("div");
    body.append(FTUI.loading(context.t("正在读取服务器 Skill…")));
    root.append(body);
    try {
      const payload = await context.api(
        `/api/client/profile-skills?profile_id=${encodeURIComponent(profile.profile_id)}`,
      );
      const skills = Array.isArray(payload.skills) ? payload.skills : [];
      body.replaceChildren();
      if (!skills.length) {
        body.append(message(
          context,
          "服务器没有可用的智能体 Skill",
          "请由服务器管理员先安装并发布研究 Skill。",
        ));
        return root;
      }

      const list = document.createElement("div");
      list.className = "settings-rows agent-skill-list";
      const controls = [];
      skills.forEach(item => {
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = Boolean(item.selected);
        checkbox.setAttribute("aria-label", context.t(item.label || item.skill_id));
        controls.push({checkbox, skillID: item.skill_id});

        const copy = document.createElement("div");
        const title = document.createElement("b");
        title.textContent = context.t(item.label || item.skill_id);
        const description = document.createElement("small");
        description.textContent = context.t(item.description || "");
        copy.append(title, description);

        const value = document.createElement("div");
        value.className = "settings-value agent-skill-toggle";
        value.append(checkbox);
        const row = document.createElement("div");
        row.className = "settings-row";
        row.append(copy, value);
        list.append(row);
      });

      const status = document.createElement("p");
      status.className = "settings-muted";
      const save = document.createElement("button");
      save.type = "button";
      save.className = "primary";
      save.textContent = context.t("保存 Skill 选择");
      save.onclick = async () => {
        save.disabled = true;
        status.textContent = context.t("正在保存…");
        try {
          await context.api("/api/client/profile-skills", {
            method: "POST",
            body: JSON.stringify({
              profile_id: profile.profile_id,
              skill_ids: controls.filter(item => item.checkbox.checked).map(item => item.skillID),
            }),
          });
          context.showNotice(context.t("Skill 选择已保存"));
          await refresh();
        } catch (error) {
          status.textContent = error.message || context.t("保存失败");
        } finally {
          save.disabled = false;
        }
      };
      const actions = document.createElement("div");
      actions.className = "settings-inline-actions";
      actions.append(save);
      body.append(list, actions, status);
    } catch (error) {
      const detail = String(error?.message || "");
      if (detail.includes("configure the Profile runtime")
          || detail.includes("Profile runtime is not configured")) {
        body.replaceChildren(message(
          context,
          "请先绑定服务器运行位置",
          "绑定成功后才能选择该 Profile 的服务器 Skill。",
        ));
      } else if (detail.includes("installed Skill is missing")) {
        body.replaceChildren(message(
          context,
          "服务器镜像缺少研究 Skill",
          "请让服务器管理员重新发布包含研究 Skill 的 FactorTester 镜像。",
        ));
      } else {
        body.replaceChildren(message(context, "无法读取服务器 Skill", detail));
      }
    }
    return root;
  }

  window.FTAgentSkills = {render};
})();
