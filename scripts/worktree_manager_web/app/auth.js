(() => {
  function bind(context) {
    const {state, api, t} = context;

    function showAuthForm(kind) {
      document.querySelector("#login-form").hidden = kind !== "login";
      document.querySelector("#register-form").hidden = kind !== "register";
    }

    function openLogin(message = "") {
      const dialog = document.querySelector("#login-dialog");
      showAuthForm("login");
      document.querySelector("#login-error").hidden = !message;
      document.querySelector("#login-error").textContent = message;
      dialog.showModal();
    }

    async function logout() {
      try { await api("/auth/logout", {method: "POST"}); } catch (_) {}
      localStorage.removeItem("ft-session");
      sessionStorage.removeItem("ft-session");
      state.token = "";
      state.session = null;
      await context.loadModules();
      await FTSettings.show(context.appContext(), "account");
    }

    function addAuthorizedUser(value = "") {
      const row = document.createElement("div"); row.className = "authorized-user";
      row.innerHTML = '<input><button type="button"></button>';
      row.querySelector("input").placeholder = t("完整用户名");
      row.querySelector("button").textContent = t("移除");
      row.querySelector("input").value = value;
      row.querySelector("button").onclick = () => row.remove();
      document.querySelector("#authorized-user-list").append(row);
    }

    async function openReportSettings() {
      const settings = (await api("/api/research-publications/settings")).reports
        .find(item => item.publication_id === state.report.publication_id);
      if (!settings) return;
      document.querySelector("#setting-auto-sync").checked = settings.auto_sync;
      document.querySelector("#setting-visibility").value = settings.visibility;
      document.querySelector("#setting-relay").checked = settings.relay_local_files;
      const list = document.querySelector("#authorized-user-list"); list.replaceChildren();
      (settings.authorized_users || []).forEach(addAuthorizedUser);
      document.querySelector("#report-settings-dialog").showModal();
    }

    document.querySelector("#login-form").addEventListener("submit", async event => {
      event.preventDefault();
      try {
        const result = await api("/auth/login", {
          method: "POST",
          body: JSON.stringify({
            username: document.querySelector("#username").value,
            password: document.querySelector("#password").value,
          }),
        });
        state.token = result.token; state.session = result;
        const storage = document.querySelector("#keep-login").checked
          ? localStorage : sessionStorage;
        storage.setItem("ft-session", result.token);
        document.querySelector("#login-dialog").close();
        await context.loadLanguage();
        await context.loadModules();
        await context.renderRoute();
      } catch (error) {
        const field = document.querySelector("#login-error");
        field.hidden = false; field.textContent = error.message;
      }
    });
    document.querySelector("#show-register").onclick = () => showAuthForm("register");
    document.querySelector("#show-login").onclick = () => showAuthForm("login");
    document.querySelector("#close-login").onclick = () => document.querySelector("#login-dialog").close();
    document.querySelector("#close-register").onclick = () => document.querySelector("#login-dialog").close();
    document.querySelector("#register-form").addEventListener("submit", async event => {
      event.preventDefault();
      try {
        const result = await api("/auth/register", {
          method: "POST",
          body: JSON.stringify({
            username: document.querySelector("#register-username").value,
            password: document.querySelector("#register-password").value,
            organization_id: document.querySelector("#register-organization").value,
          }),
        });
        state.token = result.token; state.session = result;
        localStorage.setItem("ft-session", result.token);
        document.querySelector("#login-dialog").close();
        await context.loadLanguage();
        await context.loadModules();
        await context.renderRoute();
      } catch (error) {
        const field = document.querySelector("#register-error");
        field.hidden = false; field.textContent = error.message;
      }
    });
    document.querySelector("#report-settings-form").addEventListener("submit", async event => {
      event.preventDefault();
      try {
        const users = [...document.querySelectorAll("#authorized-user-list input")]
          .map(item => item.value.trim()).filter(Boolean);
        await api("/api/research-publications/settings", {
          method: "POST",
          body: JSON.stringify({
            report_id: state.report.report_id,
            auto_sync: document.querySelector("#setting-auto-sync").checked,
            visibility: document.querySelector("#setting-visibility").value,
            relay_local_files: document.querySelector("#setting-relay").checked,
            authorized_users: users,
          }),
        });
        document.querySelector("#report-settings-dialog").close();
        await context.renderReport(state.report.publication_id);
      } catch (error) {
        const field = document.querySelector("#settings-error");
        field.hidden = false; field.textContent = error.message;
      }
    });
    document.querySelector("#add-authorized-user").onclick = () => addAuthorizedUser();
    document.querySelector("#account-button").onclick = () => context.navigate("/settings/account");

    return {openLogin, logout, openReportSettings};
  }

  window.FTAuth = {bind};
})();
