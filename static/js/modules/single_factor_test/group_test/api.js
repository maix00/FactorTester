/**
 * GroupTest API client.
 *
 * Design goals:
 * - one place to define endpoints and payload shapes
 * - keep fetch options consistent (JSON, error handling)
 * - future-proof: can add timeouts/retries/logging centrally
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    function postJson(url, payload) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        }).then(function(resp) {
            return resp.text().then(function(text) {
                try { return JSON.parse(text); }
                catch (_) { return { success: false, error: 'Invalid JSON response', raw: text, status: resp.status }; }
            });
        });
    }

    GT.api = {
        postJson: postJson,
        getGroupDetail: function(payload) { return postJson('/get_group_detail', payload); },
        createDerivedGroup: function(payload) { return postJson('/create_derived_group', payload); },
        createDerivedGroupsBatch: function(payload) { return postJson('/create_derived_groups_batch', payload); },
        getGroupRankingDetail: function(payload) { return postJson('/get_group_ranking_detail', payload); },
        getGroupSnapshot: function(payload) { return postJson('/get_group_snapshot', payload); },

        // Settings snapshot persistence (Issue #85 P6)
        saveGroupSettings: function(payload) { return postJson('/save_group_settings', payload); },
        loadGroupSettings: function(payload) { return postJson('/load_group_settings', payload); },
        listGroupSettings: function(payload) { return postJson('/list_group_settings', payload); },
        deleteGroupSettings: function(payload) { return postJson('/delete_group_settings', payload); },
    };
})();
