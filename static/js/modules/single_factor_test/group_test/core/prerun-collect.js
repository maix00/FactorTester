/**
 * core/prerun-collect.js — 运行前数据收集
 *
 * 从 GT.groupSettings 读取分组配置，组装 API payload。
 * 不再读取 DOM/window.submissions 兜底——group-settings 是唯一数据源。
 *
 * 挂载到 GT.core.collect。
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) { console.warn('[prerun-collect] GroupTest bootstrap missing'); return; }

    GT.core = GT.core || {};
    if (GT.core.collect) { console.warn('[prerun-collect] already loaded'); return; }

    var collect = {};

    // ════════════════════════════════════════════════════════════════
    //  主入口
    // ════════════════════════════════════════════════════════════════

    /**
     * 组装单次 (submissionId, factorAlias) 分组测试的 API payload。
     */
    collect.buildGroupRunPayload = async function(submissionId, factorAlias) {
        if (!submissionId || !factorAlias) {
            return { error: '请先选择测试器和因子' };
        }

        var groups = GT.groupSettings.groups;
        if (!groups) {
            return { error: '分组数据模型未就绪' };
        }

        var allBase = groups.getAll().filter(function(g) { return !g.isDerived; });
        if (!allBase.length) {
            return { error: '请先添加分组' };
        }

        var bg = allBase[0];
        var n_groups = bg.groupCount || 5;
        var rebalance_mode = bg.rebalanceMode || 'buy_and_hold';
        var start_date = bg.startDate || null;
        var end_date = bg.endDate || null;

        // ── 费率 ──
        var fee = 0;
        var fee_map = {};
        var hasPerProduct = false;
        var allFeeGroups = groups.getAll() || [];
        for (var fgi = 0; fgi < allFeeGroups.length; fgi++) {
            var fg = allFeeGroups[fgi];
            if (fg.isDerived) continue;
            if (fg.feeMode === 'per_product') hasPerProduct = true;
            if (fg.feeMode === 'uniform' && fee === 0) {
                fee = fg.feeRate != null ? fg.feeRate : 0.0025;
            }
        }
        if (hasPerProduct && GT.fee) {
            try {
                fee_map = await GT.fee.ensureFeeData();
            } catch (err) {
                console.error('[buildGroupRunPayload] ensureFeeData failed:', err);
            }
        }

        var use_closetoday = GT.fee ? GT.fee.useCloseToday() : false;

        // ── 时间范围（从 group 配置读取，空则入参方兜底） ──
        if (!start_date || !end_date) {
            return { error: '请设置时间范围' };
        }
        if (start_date > end_date) {
            return { error: '起始日期不能晚于终止日期' };
        }

        // ── 派生组 ──
        var derivedPayload = groups.getAll().filter(function(g) { return g.isDerived; }).map(function(d) {
            return {
                id: d.id,
                name: d.name || d.label,
                baseGroup: d.baseGroupId,
                productNames: d.productNames || []
            };
        });

        // ── group_fee_maps ──
        var group_fee_maps = null;
        var allGroups = groups.getAll() || [];
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
                ls_config: collect.collectLongShortConfig(n_groups),
                ls_configs: collect.collectLongShortConfigs(n_groups),
                derived_groups: derivedPayload.length > 0 ? derivedPayload : null,
                group_fee_maps: group_fee_maps,
                structure_key: collect.buildGroupStructureKey(submissionId, factorAlias, n_groups, start_date, end_date)
            }
        };
    };

    // ════════════════════════════════════════════════════════════════
    //  LS 工具
    // ════════════════════════════════════════════════════════════════

    collect.collectLongShortConfig = function(nGroups) {
        var lsConfigs = GT.groupSettings.lsConfigs;
        if (!lsConfigs) return null;
        var allLS = lsConfigs.getAll() || [];
        var def = allLS[0] || collect.defaultLongShortDefinition();
        return GT.groupSettings.lsConfigs.buildLegacyPayload(def, nGroups);
    };

    collect.collectLongShortConfigs = function(nGroups) {
        var lsConfigs = GT.groupSettings.lsConfigs;
        if (!lsConfigs) return [];
        var allLS = lsConfigs.getAll() || [];
        if (!allLS.length) {
            var dflt = collect.defaultLongShortDefinition();
            allLS = [dflt];
        }
        return GT.groupSettings.lsConfigs.buildLegacyPayloads(allLS, nGroups);
    };

    collect.defaultLongShortDefinition = function() {
        if (GT.groupSettings.lsConfigs && GT.groupSettings.lsConfigs.defaultLegacyDefinition) {
            return GT.groupSettings.lsConfigs.defaultLegacyDefinition();
        }
        return { id: 'LS1', name: 'Long-Short', longGroups: '1', longWeights: '1', shortGroups: '', shortWeights: '1' };
    };

    collect.buildLongShortPayload = function(def, nGroups) {
        return GT.groupSettings.lsConfigs.buildLegacyPayload(def, nGroups);
    };

    // ════════════════════════════════════════════════════════════════
    //  缓存 & 批量
    // ════════════════════════════════════════════════════════════════

    collect.buildGroupStructureKey = function(submissionId, factorAlias, nGroups, startDate, endDate) {
        return [
            String(submissionId || ''),
            String(factorAlias || ''),
            String(nGroups || ''),
            String(startDate || ''),
            String(endDate || '')
        ].join('|');
    };

    collect.collectDerivedPayloadForBatch = function(batch) {
        if (!GT.groupSettings.groups || typeof GT.groupSettings.groups.collectDerivedPayloadForBatch !== 'function') return [];
        return GT.groupSettings.groups.collectDerivedPayloadForBatch(batch, {
            getProductsForTester: function(testerId) {
                // 从 group-settings 获取 tester 的品种列表
                var allGroups = GT.groupSettings.groups.getAll() || [];
                for (var i = 0; i < allGroups.length; i++) {
                    if (String(allGroups[i].testerId) === String(testerId) && allGroups[i].products) {
                        return allGroups[i].products.map(function(product) {
                            return typeof product === 'string' ? product : (product && (product.name || product.desc)) || '';
                        }).filter(Boolean);
                    }
                }
                return [];
            }
        });
    };

    GT.core.collect = collect;
})();
