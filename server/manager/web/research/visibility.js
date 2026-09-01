(() => {
  const definitions = [
    ["private", "仅自己"],
    ["superiors", "分享给上级"],
    ["authorized", "指定用户可见"],
    ["public", "全体用户共享"],
  ];

  function label(context, value) {
    return context.t(definitions.find(item => item[0] === value)?.[1] || value || "仅自己");
  }

  function styledButton(context, title, action, style = "secondary") {
    const button = context.button(context.t(title), action);
    button.classList.add(style);
    return button;
  }

  async function authorizedDialog(context, currentUsers) {
    const response = await context.api("/api/research/principals");
    const principals = response.principals || [];
    return new Promise(resolve => {
      const dialog = document.createElement("dialog");
      dialog.className = "ft-dialog research-visibility-dialog";
      const card = document.createElement("div");
      card.className = "dialog-card";
      const heading = document.createElement("h2");
      heading.textContent = context.t("指定可见用户");
      const note = document.createElement("p");
      note.className = "research-dialog-note";
      note.textContent = context.t("搜索并选择可查看该内容的用户");
      const search = document.createElement("input");
      search.type = "search";
      search.placeholder = context.t("搜索用户");
      const choices = document.createElement("div");
      choices.className = "research-principal-choices";
      const selected = new Set(currentUsers || []);
      const renderChoices = () => {
        const needle = search.value.trim().toLowerCase();
        choices.replaceChildren(...principals.filter(item => (
          !needle || String(item.label || item.principal_ref).toLowerCase().includes(needle)
        )).map(item => {
          const row = document.createElement("label");
          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.checked = selected.has(item.principal_ref);
          checkbox.addEventListener("change", () => {
            if (checkbox.checked) selected.add(item.principal_ref);
            else selected.delete(item.principal_ref);
          });
          row.append(checkbox, document.createTextNode(item.label || item.principal_ref));
          return row;
        }));
      };
      search.addEventListener("input", renderChoices);
      renderChoices();
      const actions = document.createElement("div");
      actions.className = "dialog-actions";
      actions.append(
        styledButton(context, "取消", () => dialog.close("cancel")),
        styledButton(context, "保存", () => dialog.close("save"), "primary"),
      );
      card.append(heading, note, search, choices, actions);
      dialog.append(card);
      dialog.addEventListener("close", () => {
        const users = dialog.returnValue === "save"
          ? [...selected]
          : null;
        dialog.remove();
        resolve(users);
      }, {once: true});
      document.body.append(dialog);
      dialog.showModal();
      search.focus();
    });
  }

  function shareDialog(context, item, kind) {
    const dialog = document.createElement("dialog");
    dialog.className = "ft-dialog research-visibility-dialog";
    const card = document.createElement("div");
    card.className = "dialog-card";
    const heading = document.createElement("h2");
    heading.textContent = context.t("创建分享链接");
    const mode = document.createElement("select");
    [["one_time", "一次性链接"], ["permanent", "长期链接"]].forEach(([value, title]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = context.t(title);
      mode.append(option);
    });
    const expires = document.createElement("input");
    expires.type = "datetime-local";
    expires.setAttribute("aria-label", context.t("失效时间（可选）"));
    const output = document.createElement("input");
    output.readOnly = true;
    output.hidden = true;
    const links = document.createElement("div");
    links.className = "research-share-links";
    const renderLinks = async () => {
      const response = await context.api(
        `/api/research/${encodeURIComponent(item.research_id)}/share-links`,
      );
      const rows = (response.share_links || []).filter(link => (
        link.target_kind === kind
        && (kind !== "report" || link.report_id === item.report_id)
        && !link.revoked_at
      ));
      links.replaceChildren(...rows.map(link => {
        const row = document.createElement("div");
        const text = document.createElement("span");
        text.textContent = context.t(link.mode === "one_time" ? "一次性链接" : "长期链接")
          + (link.redeemed_by ? ` · ${context.t("已领取")}: ${link.redeemed_by}` : "");
        const revoke = styledButton(context, "撤销", async () => {
          revoke.disabled = true;
          try {
            await context.api(
              `/api/research/${encodeURIComponent(item.research_id)}`
                + `/share-links/${encodeURIComponent(link.link_id)}`,
              {method: "PATCH", body: JSON.stringify({revoked: true})},
            );
            await renderLinks();
          } catch (error) {
            context.showNotice?.(error.message || String(error), true);
            revoke.disabled = false;
          }
        });
        row.append(text, revoke);
        return row;
      }));
    };
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const close = styledButton(context, "关闭", () => dialog.close());
    const create = styledButton(context, "创建并复制", async () => {
      create.disabled = true;
      try {
        const payload = await context.api(
          `/api/research/${encodeURIComponent(item.research_id)}/share-links`,
          {method: "POST", body: JSON.stringify({
            target_kind: kind,
            report_id: kind === "report" ? item.report_id : "",
            mode: mode.value,
            expires_at: expires.value ? new Date(expires.value).getTime() / 1000 : 0,
          })},
        );
        const token = payload.share_link.token;
        const url = new URL("/research?share_token=" + encodeURIComponent(token), location.origin).href;
        output.value = url;
        output.hidden = false;
        await navigator.clipboard?.writeText(url);
        context.showNotice?.(context.t("分享链接已创建并复制"));
        await renderLinks();
      } catch (error) {
        context.showNotice?.(error.message || String(error), true);
      } finally {
        create.disabled = false;
      }
    }, "primary");
    actions.append(close, create);
    card.append(heading, mode, expires, output, links, actions);
    dialog.append(card);
    document.body.append(dialog);
    dialog.addEventListener("close", () => dialog.remove(), {once: true});
    dialog.showModal();
    void renderLinks().catch(error => context.showNotice?.(
      error.message || String(error), true,
    ));
  }

  async function redeemFromLocation(context) {
    const url = new URL(location.href);
    const token = url.searchParams.get("share_token");
    if (!token || !context.session) return false;
    await context.api("/api/research/share-links/redeem", {
      method: "POST",
      body: JSON.stringify({token}),
    });
    url.searchParams.delete("share_token");
    history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    context.showNotice?.(context.t("分享权限已领取"));
    return true;
  }

  function control(context, item, {kind, onSaved}) {
    if (item?.access?.can_manage !== true) {
      const value = document.createElement("span");
      value.textContent = label(context, item?.visibility);
      return value;
    }
    const wrapper = document.createElement("span");
    wrapper.className = "research-visibility-control";
    const select = document.createElement("select");
    select.className = "research-visibility-select";
    select.setAttribute("aria-label", context.t("可见性"));
    definitions.forEach(([value, title]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = context.t(title);
      option.selected = value === item.visibility;
      select.append(option);
    });
    select.addEventListener("click", event => event.stopPropagation());
    select.addEventListener("change", async event => {
      event.stopPropagation();
      const previous = item.visibility || "private";
      const visibility = select.value;
      let authorizedUsers = item.authorized_users || [];
      if (visibility === "authorized") {
        const selected = await authorizedDialog(context, authorizedUsers);
        if (selected === null) {
          select.value = previous;
          return;
        }
        authorizedUsers = selected;
      }
      select.disabled = true;
      try {
        const path = kind === "report"
          ? `/api/research/${encodeURIComponent(item.research_id)}`
            + `/reports/${encodeURIComponent(item.report_id)}`
          : `/api/research/${encodeURIComponent(item.research_id)}`;
        const result = await context.api(path, {
          method: "PATCH",
          body: JSON.stringify({visibility, authorized_users: authorizedUsers}),
        });
        Object.assign(item, result[kind] || {}, {visibility, authorized_users: authorizedUsers});
        context.showNotice?.(context.t("可见性已更新"));
        await onSaved?.();
      } catch (error) {
        select.value = previous;
        context.showNotice?.(error.message || String(error), true);
      } finally {
        select.disabled = false;
      }
    });
    const share = FTUI.iconButton(context, "link", "分享链接", event => {
      event.stopPropagation();
      shareDialog(context, item, kind);
    }, {className: "research-share-link-button"});
    wrapper.append(select, share);
    return wrapper;
  }

  window.FTResearchVisibility = Object.freeze({
    authorizedDialog, control, label, redeemFromLocation,
  });
})();
