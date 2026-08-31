(() => {
  const retryDelays = [0, 100, 250, 500, 1000];

  function transient(error) {
    return /failed to fetch|load failed|network|connection|fetch/i.test(
      String(error?.message || error || ""),
    );
  }

  async function requestProfiles(context) {
    let lastError;
    for (let attempt = 0; attempt < retryDelays.length; attempt += 1) {
      if (retryDelays[attempt]) {
        await new Promise(resolve => setTimeout(resolve, retryDelays[attempt]));
      }
      try {
        const value = await context.api("/api/client/profiles");
        return value.profiles || [];
      } catch (error) {
        lastError = error;
        if (!transient(error)) break;
      }
    }
    throw lastError;
  }

  async function profiles(context) {
    const session = context.tabSession || {};
    if (!session.pageAgentProfilesPromise) {
      session.pageAgentProfilesPromise = requestProfiles(context)
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

  function identifier(value) {
    return String(value || "").trim().replace(/^profile:/, "");
  }

  async function forResearch(context, researchID) {
    const id = String(researchID || "").trim();
    if (!id) return [];
    const [available, membership] = await Promise.all([
      profiles(context),
      context.api(`/api/research/${encodeURIComponent(id)}/members`),
    ]);
    const boundIDs = new Set((membership.members || [])
      .filter(item => String(item.status || "active") === "active")
      .map(item => identifier(item.profile_ref))
      .filter(Boolean));
    // /api/client/profiles already represents the current execution boundary:
    // a Web server returns its server Profiles and a client returns its local
    // Profiles.  Intersecting here prevents a Research membership on another
    // host from appearing as a selectable but unusable assistant.
    return available.filter(item => boundIDs.has(identifier(item.profile_id)));
  }

  window.FTPageAgentProfiles = Object.freeze({bound, forResearch, profiles, self});
})();
