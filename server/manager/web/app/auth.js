(() => {
  function bind(context) {
    const {state, api, t} = context;
    const registrationEnabled = document.querySelector(
      'meta[name="ft-registration-enabled"]',
    )?.content !== "0";

    function nativeAuthentication(action) {
      const handler = window.webkit?.messageHandlers?.factorTesterAuthentication;
      if (!handler?.postMessage) return false;
      handler.postMessage({action});
      return true;
    }

    function showAuthForm(kind) {
      if (kind === "register" && !registrationEnabled) kind = "login";
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
      context.checkpointActiveSession?.();
      try { await api("/auth/logout", {method: "POST"}); } catch (_) {}
      localStorage.removeItem("ft-session");
      sessionStorage.removeItem("ft-session");
      state.token = "";
      state.session = null;
      nativeAuthentication("logout");
      await context.refreshAfterSessionChange();
      await FTSettings.show(context.appContext(), "account");
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
        context.checkpointActiveSession?.();
        state.token = result.token; state.session = result;
        const storage = document.querySelector("#keep-login").checked
          ? localStorage : sessionStorage;
        storage.setItem("ft-session", result.token);
        let visitorDeviceError = null;
        if (result.visitor_login && window.FTVisitorDevice) {
          try {
            await FTVisitorDevice.ensureForSession(context, result);
          } catch (error) {
            visitorDeviceError = error;
            console.warn("allowlisted visitor device enrollment failed", error);
          }
        }
        nativeAuthentication("session-updated");
        document.querySelector("#login-dialog").close();
        await context.refreshAfterSessionChange();
        if (visitorDeviceError) {
          context.showNotice?.(
            context.t("白名单浏览器设备自动登记失败，本次登录仍然有效"), true,
          );
        }
      } catch (error) {
        if (error.code === "visitor_login_forbidden" && error.redirect) {
          window.location.replace(error.redirect);
          return;
        }
        const field = document.querySelector("#login-error");
        field.hidden = false; field.textContent = error.message;
      }
    });
    const registerButton = document.querySelector("#show-register");
    registerButton.hidden = !registrationEnabled;
    registerButton.onclick = () => showAuthForm("register");
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
        context.checkpointActiveSession?.();
        state.token = result.token; state.session = result;
        localStorage.setItem("ft-session", result.token);
        nativeAuthentication("session-updated");
        document.querySelector("#login-dialog").close();
        await context.refreshAfterSessionChange();
      } catch (error) {
        const field = document.querySelector("#register-error");
        field.hidden = false; field.textContent = error.message;
      }
    });
    document.querySelector("#account-button").onclick = () => context.navigate("/settings/account");

    return {openLogin, logout};
  }

  window.FTAuth = {bind};
})();
