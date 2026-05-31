/**
 * settings_snapshot.js — Snapshot & restore group test settings
 *
 * Pure logic module. Zero DOM dependencies.
 * Part of Phase 1 datamodel layer for Issue #85.
 *
 * Purpose:
 *   - Collect current state from datamodel modules for serialization (snapshot/export).
 *   - Apply (load/restore) a snapshot into the datamodel, replacing existing state.
 *   - Diff two snapshots for auditing or merge-conflict preview.
 *
 * Loading order (apply):
 *   1. groups (unified storage for base + derived)
 *   2. ls_configs
 *   3. registrations
 *
 * Validation on apply: all cross-module references resolved.
 */

(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');
    if (!GT.datamodel) { GT.datamodel = {}; }

    // ---------------------------------------------------------------------------
    // snapshot — collect all settings from current datamodel state
    // ---------------------------------------------------------------------------

    function snapshot() {
        var snap = {};

        // All groups (base + derived) are unified in base_groups.
        // Separately filter for backward-compatible snapshop format.
        if (GT.datamodel.groups) {
            var allGroups = GT.datamodel.groups.getAll();
            snap.baseGroups = allGroups.filter(function(g) { return !g.isDerived; });
            snap.derivedGraph = allGroups.filter(function(g) { return g.isDerived; });
        }
        if (GT.datamodel.ls_configs) {
            snap.lsConfigs = GT.datamodel.ls_configs.getAll();
        }
        if (GT.datamodel.registrations) {
            snap.registrations = GT.datamodel.registrations.getAll();
        }

        return snap;
    }

    // ---------------------------------------------------------------------------
    // apply — restore a snapshot into the datamodel
    // ---------------------------------------------------------------------------

    /**
     * Apply a snapshot, clearing existing state first.
     * Strict loading order: base → graph → ls → registrations.
     *
     * @param {object} snap - output of snapshot()
     * @returns {object} { applied: { baseGroups: N, derivedGraph: N, lsConfigs: N, registrations: N }, errors: [...] }
     */
    function apply(snap) {
        var result = {
            applied: { baseGroups: 0, derivedGraph: 0, lsConfigs: 0, registrations: 0 },
            errors: [],
        };

        // Validate required modules
        var required = ['groups', 'ls_configs', 'registrations'];
        for (var i = 0; i < required.length; i++) {
            if (!GT.datamodel[required[i]]) {
                result.errors.push('Missing datamodel module: ' + required[i]);
            }
        }
        if (result.errors.length > 0) return result;

        // 1) groups — reset once, then load base + derived (unified storage)
        GT.datamodel.groups._reset();
        if (snap.baseGroups && Array.isArray(snap.baseGroups)) {
            for (var bi = 0; bi < snap.baseGroups.length; bi++) {
                try {
                    GT.datamodel.groups.add(snap.baseGroups[bi]);
                    result.applied.baseGroups++;
                } catch (e) {
                    result.errors.push('baseGroups[' + bi + ']: ' + e.message);
                }
            }
        }
        if (snap.derivedGraph && Array.isArray(snap.derivedGraph)) {
            for (var di = 0; di < snap.derivedGraph.length; di++) {
                try {
                    GT.datamodel.groups.add(snap.derivedGraph[di]);
                    result.applied.derivedGraph++;
                } catch (e) {
                    result.errors.push('derivedGraph[' + di + ']: ' + e.message);
                }
            }
        }

        // 3) ls_configs
        GT.datamodel.ls_configs._reset();
        if (snap.lsConfigs && Array.isArray(snap.lsConfigs)) {
            for (var li = 0; li < snap.lsConfigs.length; li++) {
                try {
                    GT.datamodel.ls_configs.add(snap.lsConfigs[li]);
                    result.applied.lsConfigs++;
                } catch (e) {
                    result.errors.push('lsConfigs[' + li + ']: ' + e.message);
                }
            }
        }

        // 4) registrations
        GT.datamodel.registrations._reset();
        if (snap.registrations && Array.isArray(snap.registrations)) {
            for (var ri = 0; ri < snap.registrations.length; ri++) {
                var regEntry = snap.registrations[ri];
                try {
                    var regs = regEntry.registrations;
                    for (var rj = 0; rj < regs.length; rj++) {
                        var reg = regs[rj];
                        GT.datamodel.registrations.register(regEntry.lsConfigId, reg.groupId, reg.side, reg.weight);
                    }
                    result.applied.registrations++;
                } catch (e) {
                    result.errors.push('registrations[' + ri + ']: ' + e.message);
                }
            }
        }

        return result;
    }

    // ---------------------------------------------------------------------------
    // diff — compare two snapshots
    // ---------------------------------------------------------------------------

    /**
     * Compare two snapshots, returning structured differences.
     *
     * @param {object} snapA
     * @param {object} snapB
     * @returns {object} { keys: string[], details: object }
     */
    function diff(snapA, snapB) {
        var d = { keys: [], details: {} };

        var allKeys = {};
        ['baseGroups', 'derivedGraph', 'lsConfigs', 'registrations'].forEach(function(k) {
            allKeys[k] = true;
        });

        Object.keys(allKeys).forEach(function(k) {
            var a = JSON.stringify(snapA[k] || null);
            var b = JSON.stringify(snapB[k] || null);
            if (a !== b) {
                d.keys.push(k);
                d.details[k] = {
                    oldCount: (snapA[k] && snapA[k].length) || 0,
                    newCount: (snapB[k] && snapB[k].length) || 0,
                };
            }
        });

        return d;
    }

    /**
     * Return an empty snapshot — useful for "clear all" or initial state.
     */
    function emptySnapshot() {
        return {
            baseGroups: [],
            derivedGraph: [],
            lsConfigs: [],
            registrations: [],
        };
    }

    // ---------------------------------------------------------------------------
    // Export
    // ---------------------------------------------------------------------------

    GT.datamodel.settings = {
        snapshot: snapshot,
        apply: apply,
        diff: diff,
        emptySnapshot: emptySnapshot,
    };

    GT.log('datamodel.settings loaded');
})();