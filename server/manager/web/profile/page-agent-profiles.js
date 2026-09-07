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
    const members = (membership.members || [])
      .filter(item => String(item.status || "active") === "active")
      .filter(item => identifier(item.profile_ref));
    const availableByID = new Map(available.map(item => [
      identifier(item.profile_id), {...item, runtime_bound_here: true},
    ]));
    return members.map(member => {
      const profileID = identifier(member.profile_ref);
      return availableByID.get(profileID) || {
        profile_id: profileID,
        alias: profileID,
        title: profileID,
        owner_ref: member.principal_ref || "",
        runtime_bound_here: false,
        binding_status: "unbound",
      };
    }).sort((left, right) => {
      if (left.profile_id === "self") return -1;
      if (right.profile_id === "self") return 1;
      return String(left.alias || left.profile_id).localeCompare(
        String(right.alias || right.profile_id), "zh-CN",
      );
    });
  }

  async function forPage(context) {
    const own = await self(context);
    if (!context.parentResearchID) return [own];
    const members = await forResearch(context, context.parentResearchID);
    return [own, ...members.filter(profile => profile.profile_id !== own.profile_id)];
  }

  window.FTPageAgentProfiles = Object.freeze({bound, forPage, forResearch, profiles, self});
})();
