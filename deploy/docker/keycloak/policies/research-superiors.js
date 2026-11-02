/* Deployed Keycloak policy; never uploaded as user-supplied policy code.
 * Read live admin-owned identity attributes, not a token's old parent claim.
 * This policy grants only scopes explicitly attached by the resource permission.
 */
(function () {
    var session = $evaluation.getAuthorizationProvider().getKeycloakSession();
    var realm = session.getContext().getRealm();
    var users = session.users();
    // KeycloakSession lives for this HTTP transaction. Reuse native user
    // lookups across its resources/scopes, never across authorization requests.
    var cacheKey = "tr.research.hierarchy.users.v1";
    var lookup = session.getAttribute(cacheKey);
    if (lookup === null) {
        lookup = new (Java.type("java.util.HashMap"))();
        session.setAttribute(cacheKey, lookup);
    }
    function byStable(stable) {
        if (lookup.containsKey(stable)) return lookup.get(stable);
        var matches = users.searchForUserByUserAttributeStream(realm, "tr_identity_id", stable);
        var rows;
        try { rows = matches.limit(2).toArray(); }
        finally { matches.close(); }
        var result = rows.length === 1 ? rows[0] : null;
        if (lookup.size() < 512) lookup.put(stable, result);
        return result;
    }
    var resource = $evaluation.getPermission().getResource();
    if (resource === null) return;
    var ownerIds = resource.getAttribute("traderesearch_owner_subject");
    if (ownerIds === null || ownerIds.size() !== 1) return;
    var viewer = users.getUserById(realm, $evaluation.getContext().getIdentity().getId());
    var current = users.getUserById(realm, ownerIds.get(0));
    if (viewer === null || !viewer.isEnabled() || current === null || !current.isEnabled()) return;
    function single(user, name) {
        var values = user.getAttributeStream(name).limit(2).toArray();
        return values.length === 1 && String(values[0]).length > 0 ? String(values[0]) : null;
    }
    var organization = single(current, "tr_organization_id");
    var viewerIdentity = single(viewer, "tr_identity_id");
    if (organization === null || viewerIdentity === null ||
        single(viewer, "tr_organization_id") !== organization || String(viewer.getId()) === String(current.getId())) return;
    var visited = Object.create(null);
    var ancestor = false;
    // Bound malformed directories without fetching all users. Keycloak owns
    // user lookup/caching; Manager does no HTTP ancestor walks or ACL caching.
    for (var depth = 0; depth < 128; depth++) {
        if (!current.isEnabled() || single(current, "tr_organization_id") !== organization) return;
        var stable = single(current, "tr_identity_id");
        if (stable === null || visited[stable]) return;
        visited[stable] = true;
        var parentValues = current.getAttributeStream("tr_parent_identity_id").limit(2).toArray();
        if (parentValues.length > 1) return;
        if (parentValues.length === 0 || String(parentValues[0]) === "") {
            if (ancestor) $evaluation.grant();
            return;
        }
        var parent = String(parentValues[0]);
        current = byStable(parent);
        if (current === null) return;
        if (String(current.getId()) === String(viewer.getId())) ancestor = true;
    }
})();
