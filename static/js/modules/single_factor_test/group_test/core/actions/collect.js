/**
 * Collect / build payloads for group-test API calls.
 *
 * Responsibilities:
 *   - buildGroupRunPayload      — assemble a single (submissionId, factorAlias) payload
 *   - collectLongShortConfig    — single LS config → payload
 *   - collectLongShortConfigs   — all LS configs → payload array
 *   - buildGroupStructureKey    — deterministic cache key from run parameters
 *   - collectDerivedPayloadForBatch  — derived-group definitions for a batch
 *   - defaultLongShortDefinition — fallback LS definition
 *   - buildLongShortPayload     — LS definition → API payload
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) { console.warn('[collect] GroupTest bootstrap missing'); return; }

    GT.core = GT.core || {};
    GT.core.actions = GT.core.actions || {};
    GT.core.actions.collect = {};

    // ── Local bridge refs (same pattern as app.js) ──
    var getActiveSubmissionId = GT.utils.dates ? GT.utils.dates.getActiveSubmissionId : function() { return null; };
    var getActiveFactorAlias  = GT.utils.dates ? GT.utils.dates.getActiveFactorAlias  : function() { return null; };
    var resolveGroupRunTimeRange = GT.utils.dates ? GT.utils.dates.resolveGroupRunTimeRange : function() { return {startDate:null,endDate:null}; };
    var persistGroupTimeRangeToDatamodel = GT.utils.dates ? GT.utils.dates.persistGroupTimeRangeToDatamodel : function(){};
    var buildValidDate = GT.utils.dates ? GT.utils.dates.buildValidDate : function(y,m,d){ return y+'-'+m+'-'+d; };
    var escapeHtml = GT.escapeHTML;

    // ── longShortDefinitions state (shared via GT.core.cache) ──
    function _getLSDefinitions() {
        return GT.core.cache ? GT.core.cache.getLongShortDefinitions() : [];
    }

    // ════════════════════════════════════════════════════════════════
    //  Exports
    // ════════════════════════════════════════════════════════════════

    /**
     * Assemble the payload for a single (submissionId, factorAlias) group test.
     * Formerly collectGroupRunPayload.
     */
    GT.core.actions.collect.buildGroupRunPayload = async function(submissionId, factorAlias) {
        var statusSpan = document.getElementById('group_test_status');
        if (!submissionId || !factorAlias) {
            return { error: '请先选择测试器和因子' };
        }

        // P7: Read params from datamodel if available, else fallback to DOM
        var n_groups = 5;
        var rebalance_mode = 'buy_and_hold';
        var start_date = null;
        var end_date = null;

        if (GT.datamodel && GT.datamodel.groups) {
            var allBase = GT.datamodel.groups.getAll();
            if (allBase && allBase.length > 0) {
                var bg = allBase[0];
                n_groups = bg.groupCount || 5;
                rebalance_mode = bg.rebalanceMode || 'buy_and_hold';
                start_date = bg.startDate || null;
                end_date = bg.endDate || null;
            }
        }

        if (!start_date) {
            var gcEl = document.getElementById('group_count');
            if (gcEl) n_groups = parseInt(gcEl.value, 10) || 5;
            var rmEl = document.getElementById('rebalance_mode');
            if (rmEl) rebalance_mode = rmEl.value || 'buy_and_hold';
        }

        var use_closetoday = GT.fee ? GT.fee.useCloseToday() : false;

        // ── Fee aggregation ──
        var fee = 0;
        var fee_map = {};
        var hasPerProduct = false;
        if (GT.datamodel && GT.datamodel.groups) {
            var allFeeGroups = GT.datamodel.groups.getAll() || [];
            for (var fgi = 0; fgi < allFeeGroups.length; fgi++) {
                var fg = allFeeGroups[fgi];
                if (fg.isDerived) continue;
                if (fg.feeMode === 'per_product') hasPerProduct = true;
                if (fg.feeMode === 'uniform' && fee === 0) {
                    fee = fg.feeRate != null ? fg.feeRate : 0.0025;
                }
            }
        }
        if (hasPerProduct && GT.fee) {
            try {
                fee_map = await GT.fee.ensureFeeData();
            } catch (err) {
                console.error('[buildGroupRunPayload] ensureFeeData failed:', err);
            }
        }

        var groupTimeRange = resolveGroupRunTimeRange(start_date, end_date);
        start_date = groupTimeRange.startDate;
        end_date = groupTimeRange.endDate;
        persistGroupTimeRangeToDatamodel(groupTimeRange.explicitStartDate, groupTimeRange.explicitEndDate);

        if (!start_date) {
            var timeSy = document.getElementById('start_year') ? document.getElementById('start_year').value : null;
            var timeSm = document.getElementById('start_month') ? document.getElementById('start_month').value : null;
            var timeSd = document.getElementById('start_day') ? document.getElementById('start_day').value : null;
            if (timeSy && timeSm && timeSd) start_date = buildValidDate(timeSy, timeSm, timeSd);
        }
        if (!end_date) {
            var timeEy = document.getElementById('end_year') ? document.getElementById('end_year').value : null;
            var timeEm = document.getElementById('end_month') ? document.getElementById('end_month').value : null;
            var timeEd = document.getElementById('end_day') ? document.getElementById('end_day').value : null;
            if (timeEy && timeEm && timeEd) end_date = buildValidDate(timeEy, timeEm, timeEd);
        }

        if (!start_date || !end_date) {
            var submission = window.submissions ? window.submissions.find(function(s) { return String(s.id) === String(submissionId); }) : null;
            if (submission) {
                if (!start_date) start_date = submission.start_date;
                if (!end_date) end_date = submission.end_date;
            }
        }

        if (!start_date || !end_date) return { error: '请设置时间范围' };
        if (start_date > end_date) return { error: '起始日期不能晚于终止日期' };

        var derivedPayload = [];
        if (GT.datamodel && GT.datamodel.groups) {
            derivedPayload = GT.datamodel.groups.getAll().filter(function(g) { return g.isDerived; }).map(function(d) {
                return {
                    id: d.id,
                    name: d.name || d.label,
                    baseGroup: d.baseGroupId,
                    productNames: d.productNames || []
                };
            });
        }

        // ── group_fee_maps ──
        var group_fee_maps = null;
        if (GT.datamodel && GT.datamodel.groups) {
            var allGroups = GT.datamodel.groups.getAll() || [];
            var gfmObj = {};
            for (var gi = 0; gi < allGroups.length; gi++) {
                var grp = allGroups[gi];
                if (grp.isDerived) continue;
                if (grp.feeMode === 'per_product' && grp.feeMap && typeof grp.feeMap === 'object') {
                    var gIdx = Number(grp.groupIndex || 1) - 1;
                    var gfm = {};
                    Object.keys(grp.feeMap).forEach(function(code) {
                        var ov = grp.feeMap[code];
                        if (ov && typeof ov === 'object') {
                            gfm[code.toLowerCase()] = {
                                open: ov.open_ratio != null ? ov.open_ratio : null,
                                close: ov.close_ratio != null ? ov.close_ratio : null,
                                close_today: ov.closetoday_ratio != null ? ov.closetoday_ratio : null
                            };
                        }
                    });
                    if (Object.keys(gfm).length > 0) {
                        gfmObj[gIdx] = gfm;
                    }
                }
            }
            if (Object.keys(gfmObj).length > 0) group_fee_maps = gfmObj;
        }

        return {
            payload: {
                submission_id: submissionId,
                factor_alias: factorAlias,
                n_groups: n_groups,
                fee: fee,
                fee_map: fee_map,
                use_closetoday: use_closetoday,
                start_date: start_date,
                end_date: end_date,
                rebalance_mode: rebalance_mode,
                ls_config: GT.core.actions.collect.collectLongShortConfig(n_groups),
                ls_configs: GT.core.actions.collect.collectLongShortConfigs(n_groups),
                derived_groups: derivedPayload.length > 0 ? derivedPayload : null,
                group_fee_maps: group_fee_maps,
                structure_key: GT.core.actions.collect.buildGroupStructureKey(submissionId, factorAlias, n_groups, start_date, end_date)
            },
            statusEl: statusSpan,
        };
    };

    /**
     * Build a single Long-Short config payload from definitions.
     */
    GT.core.actions.collect.collectLongShortConfig = function(nGroups) {
        var defs = _getLSDefinitions();
        var def = (defs && defs[0]) || GT.core.actions.collect.defaultLongShortDefinition();
        return GT.core.actions.collect.buildLongShortPayload(def, nGroups);
    };

    /**
     * Build all Long-Short config payloads.
     */
    GT.core.actions.collect.collectLongShortConfigs = function(nGroups) {
        var defs = _getLSDefinitions();
        if (!defs || !defs.length) {
            if (GT.core.cache) {
                var ds = GT.core.cache.getLongShortDefinitions();
                if (!ds || !ds.length) {
                    var dflt = GT.core.actions.collect.defaultLongShortDefinition();
                    GT.core.cache.setLongShortDefinitions([dflt]);
                }
            }
            defs = GT.core.cache ? GT.core.cache.getLongShortDefinitions() : [GT.core.actions.collect.defaultLongShortDefinition()];
        }
        return GT.datamodel.ls_configs.buildLegacyPayloads(defs, nGroups);
    };

    /**
     * Deterministic cache key from run parameters.
     */
    GT.core.actions.collect.buildGroupStructureKey = function(submissionId, factorAlias, nGroups, startDate, endDate) {
        return [
            String(submissionId || ''),
            String(factorAlias || ''),
            String(nGroups || ''),
            String(startDate || ''),
            String(endDate || '')
        ].join('|');
    };

    /**
     * Collect derived-group definitions for a batch (from GT.datamodel).
     */
    GT.core.actions.collect.collectDerivedPayloadForBatch = function(batch) {
        if (!GT.datamodel || !GT.datamodel.groups || typeof GT.datamodel.groups.collectDerivedPayloadForBatch !== 'function') return [];
        return GT.datamodel.groups.collectDerivedPayloadForBatch(batch, {
            getProductsForTester: function(testerId) {
                var subs = window.submissions || [];
                for (var i = 0; i < subs.length; i++) {
                    if (String(subs[i].id) !== String(testerId)) continue;
                    return (subs[i].products || []).map(function(product) {
                        return typeof product === 'string' ? product : (product && (product.name || product.desc)) || '';
                    }).filter(Boolean);
                }
                return [];
            }
        });
    };

    /**
     * Fallback LS definition when no user config exists.
     */
    GT.core.actions.collect.defaultLongShortDefinition = function() {
        if (GT.datamodel && GT.datamodel.ls_configs && GT.datamodel.ls_configs.defaultLegacyDefinition) {
            return GT.datamodel.ls_configs.defaultLegacyDefinition();
        }
        return { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' };
    };

    /**
     * Convert a single LS definition into an API payload chunk.
     */
    GT.core.actions.collect.buildLongShortPayload = function(def, nGroups) {
        return GT.datamodel.ls_configs.buildLegacyPayload(def, nGroups);
    };

})();
