(() => {
  async function profiles(context) {
    const session = context.tabSession || {};
    if (!session.pageAgentProfilesPromise) {
      session.pageAgentProfilesPromise = context.api("/api/client/profiles")
        .then(value => value.profiles || [])
        .catch(error => {
          delete session.pageAgentProfilesPromise;
          throw error;
        });
    }
    return session.pageAgentProfilesPromise;
  }

  async function self(context) {
    const values = await profiles(context);
    const profile = values.find(item => (
      item.is_self_profile || item.profile_kind === "self"
    ));
    if (!profile) throw new Error(context.t("当前用户没有 self Profile"));
    return profile;
  }

  async function bound(context, profileID) {
    const identifier = String(profileID || "").trim().replace(/^profile:/, "");
    const profile = (await profiles(context)).find(
      item => String(item.profile_id || "") === identifier,
    );
    if (!profile) throw new Error(context.t("研究报告绑定的 Profile 不可用"));
    return profile;
  }

  window.FTPageAgentProfiles = Object.freeze({bound, self});
})();
