/**
 * factor_type_analysis_module.js
 *
 * 因子类型分析——前端模块。
 * 与因子序列查看器平行，使用同一套 settings 框架，
 * 分析因子与趋势/波动率等类别的相关性。
 */

(function () {
    'use strict';

    var Progress = window.SingleFactorProgress;
    if (!Progress) throw new Error('SingleFactorProgress bootstrap not loaded');

    var APP = 'factor_type_analysis';

    var state = {
        manifest: null,
        mountedTabs: {},
        values: {},
        lastResult: null,
        factors: [],
    };
    var progressUi = Progress.createSimpleProgressController({
        resolve: function() {
            return {
                wrapper: document.getElementById('factor-type-analysis-progress'),
                bar: document.getElementById('factor-type-analysis-progress-bar'),
                text: document.getElementById('factor-type-analysis-progress-text'),
            };
        },
        visibleDisplay: '',
    });

    // =========================================================
    //  Helpers
    // =========================================================

    function msg(text, isError) {
        var div = document.createElement('div');
        div.style.cssText = 'text-align:center;padding:40px 20px;color:' + (isError ? '#d32f2f' : '#64748b') + ';font-size:13px;';
        div.textContent = text;
        return div;
    }

    function escapeHTML(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function selectedFactor() {
        var name = state.values.factor || state.values.factor_name || '';
        var alias = state.values.factor_alias || '';
        var list = state.factors || [];
        for (var i = 0; i < list.length; i++) {
            if (list[i].alias === alias || list[i].name === alias || list[i].alias === name || list[i].name === name) {
                return list[i];
            }
        }
        return null;
    }

    function getSelections() {
        return {
            product_path_selection: state.values.product_path_selection || null,
            factor: state.values.factor || state.values.factor_name || '',
            settings: state.values || {},
        };
    }

    function setSelections(data) {
        if (data.product_path_selection) state.values.product_path_selection = data.product_path_selection;
        if (data.factor) state.values.factor = data.factor;
        renderSettingChips();
    }

    function updateStatus(text) {
        var el = document.getElementById('factor-type-analysis-status');
        if (el) el.textContent = text;
    }

    function showProgress() {
        progressUi.show('0%');
    }

    function hideProgress(label) {
        progressUi.done(label || '完成', 0);
    }

    function setProgress(pct, label) {
        progressUi.set(pct, label);
    }

    function failProgress(msg) {
        var bar = document.getElementById('factor-type-analysis-progress-bar');
        if (bar) { bar.style.background = '#d32f2f'; bar.style.width = '100%'; }
        progressUi.fail(msg || '失败', 100, -1);
    }

    function displayProductLabel() {
        var selection = state.values.product_path_selection;
        var utils = window.ProductPathSelectionUtils || {};
        if (utils.selectionDisplayLabel) return utils.selectionDisplayLabel(selection);
        if (!selection) return '';
        return selection.product_group || selection.label || selection.name || selection.product_path_selection_id || '';
    }

    function settingMeta(key) {
        return state.manifest && state.manifest.defaults && state.manifest.defaults[key] || null;
    }

    function effectiveValue(key) {
        if (Object.prototype.hasOwnProperty.call(state.values, key)) return state.values[key];
        var meta = settingMeta(key);
        return meta ? meta.value : undefined;
    }

    function settingVisible(setting, values) {
        return window.BackendSettingsPanel.settingVisibleForValues(setting, values || state.values || {});
    }

    function displaySettingValue(setting, value) {
        if (setting && setting.key === 'factor') {
            var factor = selectedFactor();
            return factor ? factor.alias || factor.name || '' : '无';
        }
        return window.BackendSettingsPanel.displaySettingValue(setting, value);
    }

    // settingChipParts 已删除：chip 改由 manifest 驱动的 ChipRenderer + FieldStore 渲染。

    function renderChipHtml(labelOrText, value) {
        var text = value === undefined || value === null || value === ''
            ? String(labelOrText == null ? '' : labelOrText)
            : String(labelOrText == null ? '' : labelOrText) + ': ' + String(value);
        var match = text.match(/^([^:：]{1,16})[:：]\s*(.*)$/);
        if (match && match[2]) {
            return '<span class="gt-backend-chip-label">' + escapeHTML(match[1]) + '</span>'
                + '<span class="gt-backend-chip-value">' + escapeHTML(match[2]) + '</span>';
        }
        return '<span class="gt-backend-chip-value">' + escapeHTML(text) + '</span>';
    }

    // =========================================================
    //  Settings manifest / factors
    // =========================================================

    function loadManifest() {
        return fetch('/api/backtest/settings/' + APP)
            .then(function (r) { return r.json(); })
            .then(function (m) {
                state.manifest = m;
                setupSettingsHost();
            })
            .catch(function (err) {
                console.warn('factor_type_analysis: loadManifest error', err);
            });
    }

    function setupSettingsHost() {
        if (!state.manifest) return;
        var defaults = state.manifest.defaults || {};
        var merged = {};
        Object.keys(defaults).forEach(function (k) {
            merged[k] = defaults[k].value;
        });
        state.values = merged;

        // Apply page time defaults
        if (typeof applyPageTimeDefaults === 'function') {
            applyPageTimeDefaults({ blockOnAnyTimeValue: false });
        }
    }

    function loadFactors() {
        var aliasEl = document.getElementById('factor_type_analysis_module');
        var familyAlias = aliasEl ? aliasEl.getAttribute('data-factor-family-alias') : '';
        if (!familyAlias) return Promise.resolve([]);
        var uuid = window._pageUuid || '';
        return fetch('/api/factor_list?factor_family_alias=' + encodeURIComponent(familyAlias) + '&page_uuid=' + encodeURIComponent(uuid))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                state.factors = Array.isArray(data) ? data : (data.factors || []);
                return state.factors;
            })
            .catch(function () { state.factors = []; return []; });
    }

    // =========================================================
    //  Tab / Chip rendering
    // =========================================================

    function renderTabBar() {
        if (!state.manifest) return;
        var tabLists = state.manifest.tab_lists || {};
        var localTabs = tabLists['local-settings'] || [];
        var bar = document.getElementById('factor-type-analysis-tab-bar');
        if (!bar) return;

        bar.innerHTML = '';
        localTabs.forEach(function (tab, idx) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'backend-tab-btn' + (idx === 0 ? ' active' : '');
            btn.textContent = tab.label;
            btn.dataset.tabKey = tab.key;
            btn.addEventListener('click', function () {
                openTab(tab.key);
            });
            bar.appendChild(btn);
        });

        if (localTabs.length) {
            openTab(localTabs[0].key);
        }
    }

    function openTab(tabKey) {
        if (!state.manifest) return;
        var tabs = state.manifest.tab_lists && state.manifest.tab_lists['local-settings'] || [];
        var tabDef = null;
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].key === tabKey) { tabDef = tabs[i]; break; }
        }
        if (!tabDef) return;

        // highlight tab button
        var bar = document.getElementById('factor-type-analysis-tab-bar');
        if (bar) {
            var btns = bar.querySelectorAll('.backend-tab-btn');
            btns.forEach(function (b) { b.classList.remove('active'); });
            var active = bar.querySelector('[data-tab-key="' + tabKey + '"]');
            if (active) active.classList.add('active');
        }

        var host = document.getElementById('factor-type-analysis-settings-host');
        if (!host) return;

        // Load the tab template from backend
        var url = (state.manifest.tab_url_template || '').replace('{tab_key}', tabKey);
        if (!url) return;

        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (tabManifest) {
                renderTabContent(host, tabManifest, tabKey);
                if (!state.mountedTabs[tabKey]) {
                    state.mountedTabs[tabKey] = true;
                    bindTabEvents(tabKey);
                }
            })
            .catch(function (err) {
                host.innerHTML = '<div style="color:#d32f2f;padding:12px;font-size:12px;">加载设置失败: ' + (err.message || String(err)) + '</div>';
            });
    }

    function renderTabContent(host, tabManifest, tabKey) {
        var settings = tabManifest.settings || [];
        if (!settings.length) {
            host.innerHTML = '<div style="color:#64748b;padding:12px;font-size:12px;">该标签页暂无设置项。</div>';
            host.style.display = '';
            return;
        }

        var html = '';
        settings.forEach(function (s) {
            if (s.control_template === 'custom') {
                html += '<div class="backend-setting-row-wide"><label class="backend-setting-label">' + s.label + '</label>';
                html += '<div class="backend-setting-control">' + renderCustomSetting(s) + '</div></div>';
                return;
            }
            html += '<div class="backend-setting-row">';
            html += '<label class="backend-setting-label">' + s.label + '</label>';
            html += '<div class="backend-setting-control">' + renderSettingControl(s) + '</div>';
            html += '</div>';
        });
        host.innerHTML = html;
        host.style.display = '';
    }

    function renderSettingControl(s) {
        var val = state.values[s.key] !== undefined ? state.values[s.key] : s.default;
        var opts = s.options || [];
        if (s.key === 'product_path_selection') {
            return '<div class="backend-input" style="height:auto;min-height:28px;display:flex;align-items:center;color:#475569;background:#f8fafc;">'
                + (displayProductLabel() || '尚未选择产品路径')
                + '</div>';
        }
        switch (s.control_template) {
            case 'select':
                var html = '<select data-setting-key="' + s.key + '" class="backend-select">';
                opts.forEach(function (o) {
                    var sel = (String(o.value) === String(val)) ? ' selected' : '';
                    html += '<option value="' + o.value + '"' + sel + '>' + o.label + '</option>';
                });
                html += '</select>';
                return html;
            case 'date':
                return '<input type="date" data-setting-key="' + s.key + '" value="' + (val || '') + '" class="backend-input" />';
            case 'time':
                return '<input type="time" data-setting-key="' + s.key + '" value="' + (val || '') + '" class="backend-input" />';
            case 'number':
                return '<input type="number" data-setting-key="' + s.key + '" value="' + (val || '') + '" class="backend-input" step="' + (s.step || 'any') + '" />';
            default:
                return '<input data-setting-key="' + s.key + '" value="' + (val || '') + '" class="backend-input" />';
        }
    }

    function renderCustomSetting(s) {
        if (s.key === 'factor') {
            return renderFactorPicker(s);
        }
        if (s.key === 'product_path_selection') {
            return '<div style="font-size:12px;color:#64748b;">从产品路径设置选择或管理产品路径。</div>';
        }
        return '<div style="font-size:12px;color:#64748b;">' + (s.key) + '</div>';
    }

    function renderFactorPicker(s) {
        var val = state.values.factor || '';
        var html = '<select data-setting-key="factor" class="backend-select" style="max-width:300px;">';
        html += '<option value="">-- 请选择因子 --</option>';
        var factors = state.factors || [];
        for (var i = 0; i < factors.length; i++) {
            var f = factors[i];
            var fv = f.alias || f.name || '';
            var sel = (fv === val) ? ' selected' : '';
            html += '<option value="' + fv + '"' + sel + '>' + (f.label || f.name || f.alias || fv) + '</option>';
        }
        html += '</select>';
        return html;
    }

    function bindTabEvents(tabKey) {
        var host = document.getElementById('factor-type-analysis-settings-host');
        if (!host) return;
        var inputs = host.querySelectorAll('[data-setting-key]');
        inputs.forEach(function (el) {
            el.addEventListener('change', function () {
                var key = el.getAttribute('data-setting-key');
                state.values[key] = el.value;
                renderSettingChips();
            });
        });
    }

    // 响应式 chip：manifest 建 FieldStore（backing = state.values），ChipRenderer 订阅。
    var ftaStore = null, ftaChipUnbind = null;
    function ensureFtaStore() {
        if (!ftaStore && state.manifest && window.FieldStore) {
            ftaStore = window.FieldStore.create({ defaults: state.manifest.defaults, values: state.values, parent: window._singleFactorPageStore || null });
        }
        if (ftaStore && window._singleFactorPageStore && ftaStore.setParent) {
            ftaStore.setParent(window._singleFactorPageStore);
        }
        return ftaStore;
    }

    function renderSettingChips() {
        if (!state.manifest) return;
        var row = document.getElementById('factor-type-analysis-chip-row');
        if (!row) return;
        ensureFtaStore();
        if (ftaStore) ftaStore.setMany(state.values);
        if (ftaChipUnbind) { ftaChipUnbind(); ftaChipUnbind = null; }
        var defaults = state.manifest.defaults || {};
        var keys = window.BackendSettingsPanel.sortSettingKeysByDisplayOrder(Object.keys(defaults), defaults)
            .filter(function (k) { return defaults[k] && defaults[k].chip_template; });
        if (window.ChipRenderer && ftaStore) {
            ftaChipUnbind = window.ChipRenderer.render(row, {
                manifest: state.manifest, store: ftaStore, settingKeys: keys,
                escapeHTML: escapeHTML, renderChipHtml: renderChipHtml,
            });
        } else {
            row.innerHTML = '';
        }
    }

    // =========================================================
    //  Run analysis
    // =========================================================

    function syncProductFromActiveTree() {
        if (typeof window.FactorSeriesViewer !== 'undefined') {
            var fse = window.FactorSeriesViewer;
            if (typeof fse.getSelections === 'function') {
                var sel2 = fse.getSelections();
                if (sel2 && sel2.product_path_selection) {
                    state.values.product_path_selection = sel2.product_path_selection;
                }
            }
        }
    }

    function compactProductPathSelectionForRun(selection) {
        var utils = window.ProductPathSelectionUtils || {};
        var def = state.manifest && state.manifest.defaults && state.manifest.defaults.product_path_selection;
        var serialization = def && def.serialization || {};
        if (utils.compactSelection) return utils.compactSelection(selection, serialization);
        if (!selection) return null;
        return { product_path_selection_id: selection.product_path_selection_id || selection.selection_id || selection.id || '' };
    }

    async function runAnalysis() {
        var panel = document.getElementById('factor-type-analysis-result-panel');
        var status = document.getElementById('factor-type-analysis-status');
        var factor = selectedFactor();
        if (!panel) return;

        showProgress();
        setProgress(5, '检查配置');

        if (!state.values.product_path_selection) {
            syncProductFromActiveTree();
        }
        if (!state.values.product_path_selection) {
            panel.innerHTML = msg('请先选择产品路径。');
            hideProgress();
            return;
        }
        if (!factor) {
            panel.innerHTML = msg('请先选择因子。', true);
            if (status) status.textContent = '请先选择因子';
            hideProgress();
            return;
        }

        if (status) status.textContent = '分析中...';
        setProgress(25, '分析因子类型');

        try {
            var data = await fetch('/api/factor_type_analysis/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    product_path_selection: compactProductPathSelectionForRun(state.values.product_path_selection),
                    factor_family_alias: document.getElementById('factor_type_analysis_module').getAttribute('data-factor-family-alias') || '',
                    factor_alias: factor.alias || factor.name,
                    page_uuid: window._pageUuid || '',
                    settings: state.values || {},
                    method: state.values.correlation_method || 'pearson',
                    min_periods: state.values.min_periods || 30,
                }),
            });
            var result = await data.json();

            if (!result || result.success === false) {
                panel.innerHTML = msg(result.error || '分析失败', true);
                if (status) status.textContent = '失败';
                failProgress('失败');
                return;
            }

            state.lastResult = result;
            setProgress(80, '渲染结果');
            renderResults(result);
            hideProgress('100%');
            if (status) {
                var doneText = '完成：' + (result.meta ? result.meta.product_count + ' 个产品' : '');
                if (result.meta && result.meta.elapsed_ms != null) doneText += '（' + result.meta.elapsed_ms + 'ms）';
                status.textContent = doneText;
            }
        } catch (err) {
            panel.innerHTML = msg(err.message || String(err), true);
            if (status) status.textContent = '失败';
            failProgress('失败');
        }
    }

    // =========================================================
    //  Render results
    // =========================================================

    function renderResults(result) {
        // 1) Best match card
        renderBestMatch(result);

        // 2) Reference factor table
        renderRefTable(result);

        // 3) Registered tests that were not run
        renderSkippedRefs(result);

        // 4) Category aggregation
        renderCategoryTable(result);

        // 5) Product correlation matrix
        renderProductMatrix(result);

        // 6) Product type profiles
        renderProductProfiles(result);

        // 7) Category product ranking
        renderCategoryRankings(result);

        // 8) Product summary
        renderProductSummary(result);
    }

    function renderBestMatch(result) {
        var el = document.getElementById('factor-type-analysis-best-match');
        if (!el) return;
        var best = result.best_match || {};
        var cat = best.best_category || '';
        if (!cat) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';
        el.className = 'factor-type-analysis-best-match ' + (result.best_match ? result.best_match._category_class || '' : '');
        // Map category to class
        var catClass = '';
        if (cat === '趋势跟踪') catClass = 'trend';
        else if (cat === '动量') catClass = 'momentum';
        else if (cat === '波动率') catClass = 'volatility';
        else if (cat === '持仓量') catClass = 'position';
        else if (cat === '量价关系') catClass = 'price_volume';
        el.className = 'factor-type-analysis-best-match ' + catClass;

        el.innerHTML = '该因子与「<strong>' + cat + '</strong>」类别最接近（相关性: ' + (best.best_corr != null ? best.best_corr.toFixed(4) : 'N/A') + '）';
    }

    function renderRefTable(result) {
        var el = document.getElementById('factor-type-analysis-ref-table');
        var tbody = document.getElementById('factor-type-analysis-ref-table-body');
        if (!el || !tbody) return;
        var refs = result.reference_factors || [];
        if (!refs.length) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';
        tbody.innerHTML = '';
        refs.forEach(function (r) {
            var tr = document.createElement('tr');
            var corrVal = r.correlation != null ? r.correlation.toFixed(4) : 'N/A';
            var pVal = r.p_value != null ? r.p_value.toFixed(6) : 'N/A';
            if (r.insufficient_data) {
                corrVal = '数据不足';
                pVal = '—';
            }
            tr.innerHTML = '<td>' + r.name + '</td>'
                + '<td>' + r.category_label + '</td>'
                + '<td>' + corrVal + '</td>'
                + '<td>' + pVal + '</td>'
                + '<td>' + r.valid_periods + '</td>';
            tbody.appendChild(tr);
        });
    }

    function renderCategoryTable(result) {
        var el = document.getElementById('factor-type-analysis-category-section');
        var tbody = document.getElementById('factor-type-analysis-category-table');
        if (!el || !tbody) return;
        var cats = result.category_correlations || {};
        var keys = Object.keys(cats);
        if (!keys.length) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';
        tbody.innerHTML = '';
        // Sort by abs correlation descending
        keys.sort(function (a, b) { return Math.abs(cats[b]) - Math.abs(cats[a]); });
        keys.forEach(function (cat) {
            var corr = cats[cat];
            var tr = document.createElement('tr');
            var strength = corr != null ? corrStrengthLabel(corr) : '无数据';
            tr.innerHTML = '<td><strong>' + cat + '</strong></td>'
                + '<td>' + (corr != null ? corr.toFixed(4) : 'N/A') + '</td>'
                + '<td>' + strength + '</td>';
            tbody.appendChild(tr);
        });
    }

    function renderSkippedRefs(result) {
        var el = document.getElementById('factor-type-analysis-skipped-ref-section');
        var tbody = document.getElementById('factor-type-analysis-skipped-ref-table');
        if (!el || !tbody) return;
        var refs = result.skipped_reference_factors || [];
        if (!refs.length) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';
        tbody.innerHTML = '';
        refs.forEach(function (r) {
            var reason = r.reason || '';
            if (reason === 'asset_class_not_applicable') reason = '不适用于当前产品域';
            else if (reason.indexOf('requires_explicit_enable_or_data') === 0) reason = '需要显式启用或补充数据';
            else if (reason === 'requires_explicit_enable') reason = '需要显式启用';
            else if (reason === 'calculation_failed') reason = '计算失败';
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + (r.name || r.key || '') + '</td>'
                + '<td>' + (r.category_label || r.category || '') + '</td>'
                + '<td>' + reason + '</td>'
                + '<td>' + (r.help_text || '') + '</td>';
            tbody.appendChild(tr);
        });
    }

    function corrStrengthLabel(corr) {
        var abs = Math.abs(corr);
        if (abs >= 0.8) return '高度相关';
        if (abs >= 0.5) return '中度相关';
        if (abs >= 0.3) return '弱相关';
        return '几乎无关';
    }

    function renderProductMatrix(result) {
        var el = document.getElementById('factor-type-analysis-product-section');
        var container = document.getElementById('factor-type-analysis-product-matrix');
        if (!el || !container) return;
        var pc = result.product_correlation || {};
        var matrix = pc.matrix || [];
        var products = pc.products || [];
        if (!matrix.length || !products.length) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';

        var html = '<table class="factor-type-analysis-data-table" style="font-size:11px;">';
        html += '<thead><tr><th style="min-width:70px;">产品</th>';
        products.forEach(function (p) {
            var short = p.length > 10 ? p.substring(0, 10) + '…' : p;
            html += '<th class="factor-type-analysis-matrix-cell" title="' + p + '">' + short + '</th>';
        });
        html += '</tr></thead><tbody>';
        for (var i = 0; i < matrix.length; i++) {
            html += '<tr><td class="factor-type-analysis-matrix-row-label">' + products[i] + '</td>';
            for (var j = 0; j < matrix[i].length; j++) {
                var val = matrix[i][j];
                var display = val != null ? val.toFixed(4) : '—';
                var bg = val != null ? corrColor(val) : '';
                html += '<td class="factor-type-analysis-matrix-cell" style="background:' + bg + ';">' + display + '</td>';
            }
            html += '</tr>';
        }
        html += '</tbody></table>';
        container.innerHTML = html;
    }

    function corrColor(val) {
        // Gradient: red (negative) -> white -> green (positive)
        var abs = Math.min(Math.abs(val), 1);
        var intensity = Math.round(abs * 200);
        if (val > 0) {
            return 'rgba(0, 128, 0, ' + (abs * 0.3) + ')';
        } else {
            return 'rgba(200, 0, 0, ' + (abs * 0.3) + ')';
        }
    }

    function renderProductSummary(result) {
        var el = document.getElementById('factor-type-analysis-product-summary-section');
        var tbody = document.getElementById('factor-type-analysis-product-summary-table');
        if (!el || !tbody) return;
        var summaries = result.product_summaries || [];
        if (!summaries.length) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';
        tbody.innerHTML = '';
        summaries.forEach(function (s) {
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + s.product + '</td>'
                + '<td>' + (s.count || 0) + '</td>'
                + '<td>' + (s.mean != null ? s.mean.toFixed(6) : 'N/A') + '</td>'
                + '<td>' + (s.std != null ? s.std.toFixed(6) : 'N/A') + '</td>';
            tbody.appendChild(tr);
        });
    }

    function renderProductProfiles(result) {
        var el = document.getElementById('factor-type-analysis-product-profile-section');
        var tbody = document.getElementById('factor-type-analysis-product-profile-table');
        if (!el || !tbody) return;
        var profiles = result.product_type_profiles || [];
        if (!profiles.length) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';
        tbody.innerHTML = '';
        profiles.forEach(function (p) {
            var topRefs = (p.reference_correlations || []).slice(0, 3).map(function (r) {
                var corr = r.correlation != null ? Number(r.correlation).toFixed(4) : 'N/A';
                return r.name + ' ' + corr;
            }).join(' / ');
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + p.product + '</td>'
                + '<td>' + (p.best_category || '无数据') + '</td>'
                + '<td>' + (p.best_score != null ? Number(p.best_score).toFixed(4) : 'N/A') + '</td>'
                + '<td>' + (topRefs || '—') + '</td>';
            tbody.appendChild(tr);
        });
    }

    function renderCategoryRankings(result) {
        var el = document.getElementById('factor-type-analysis-category-ranking-section');
        var container = document.getElementById('factor-type-analysis-category-ranking');
        if (!el || !container) return;
        var rankings = result.category_product_rankings || {};
        var categories = Object.keys(rankings);
        if (!categories.length) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';
        categories.sort(function (a, b) {
            var av = rankings[a] && rankings[a][0] ? Math.abs(rankings[a][0].score || 0) : 0;
            var bv = rankings[b] && rankings[b][0] ? Math.abs(rankings[b][0].score || 0) : 0;
            return bv - av;
        });
        var html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;padding:8px;">';
        categories.forEach(function (cat) {
            html += '<div style="border:1px solid #edf2f7;border-radius:6px;overflow:hidden;background:#fff;">';
            html += '<div style="font-size:12px;font-weight:600;color:#334155;background:#f8fafc;padding:6px 8px;">' + cat + '</div>';
            html += '<table class="factor-type-analysis-data-table" style="font-size:11px;"><tbody>';
            (rankings[cat] || []).slice(0, 8).forEach(function (row) {
                html += '<tr><td>' + row.product + '</td><td>' + Number(row.score || 0).toFixed(4) + '</td></tr>';
            });
            html += '</tbody></table></div>';
        });
        html += '</div>';
        container.innerHTML = html;
    }

    // =========================================================
    //  Init
    // =========================================================

    async function render() {
        await loadManifest();
        if (typeof applyPageTimeDefaults === 'function') {
            applyPageTimeDefaults({ blockOnAnyTimeValue: false });
        }
        await loadFactors();
        renderTabBar();
        renderSettingChips();
        var panel = document.getElementById('factor-type-analysis-result-panel');
        if (panel) {
            panel.innerHTML = msg('从产品树选择产品，再选择因子并运行分析。');
        }
    }

    function init() {
        var header = document.getElementById('factor-type-analysis-header');
        var body = document.getElementById('factor-type-analysis-body');
        var runBtn = document.getElementById('factor-type-analysis-run-btn');
        var triangle = document.getElementById('factor-type-analysis-triangle');

        function setOpen(open) {
            if (!body) return;
            var openState = !!open;
            body.style.display = openState ? '' : 'none';
            if (triangle) triangle.style.transform = openState ? 'rotate(0deg)' : 'rotate(-90deg)';
            if (openState) render();
        }

        // Toggle on header click
        if (header) {
            header.addEventListener('click', function (e) {
                if (e.target.closest('.gt-section-title-actions')) return;
                var isOpen = body && body.style.display !== 'none';
                setOpen(!isOpen);
            });
        }

        // Run button
        if (runBtn) {
            runBtn.addEventListener('click', function () {
                runAnalysis();
            });
        }

        // Open by default if header has 'open' class
        if (header && header.classList.contains('open')) {
            setOpen(true);
        }
    }

    // Public API
    window.FactorTypeAnalyzer = {
        setSelections: setSelections,
        getSelections: getSelections,
        render: render,
    };

    // Auto-init on DOMContentLoaded if module element exists
    if (document.getElementById('factor_type_analysis_module')) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
        } else {
            init();
        }
    }
})();
