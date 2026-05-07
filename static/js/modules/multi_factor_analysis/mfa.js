/**
 * 多因子分析模块 — MFA (Multi-Factor Analysis)
 */
(function () {
  'use strict';

  // ── DOM refs ──────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const submissionSel = $('#mf-submission-select');
  const familySel     = $('#mf-family-select');
  const loadFactorsBtn = $('#mf-load-factors-btn');
  const tagsWrap      = $('#mf-factor-tags');
  const selectedCount = $('#mf-selected-count');
  const selectAllBtn  = $('#mf-select-all-btn');
  const deselectAllBtn = $('#mf-deselect-all-btn');

  const runCorrBtn    = $('#mf-run-correlation-btn');
  const corrStatus    = $('#mf-corr-status');
  const corrContainer = $('#mf-corr-container');
  const corrSpearman  = $('#corr-type-spearman');
  const corrPearson   = $('#corr-type-pearson');

  const methodBtns    = $$('#mf-combo-chart').length ? null : null; // queried later
  const returnFreqSel = $('#mf-return-freq');
  const nGroupsInput  = $('#mf-n-groups');
  const runComboBtn   = $('#mf-run-combination-btn');
  const comboStatus   = $('#mf-combo-status');
  const weightsContainer = $('#mf-weights-container');
  const comboChartDiv = $('#mf-combo-chart');

  // ── State ─────────────────────────────────────────────────
  let allFactors   = [];   // { alias, chinese_name }
  let selectedFactors = new Set();
  let corrMatrix   = null;   // last result: { spearman: {labels, matrix}, pearson: {labels, matrix} }
  let currentCorrType = 'spearman';
  let currentComboMethod = 'equal_weight';

  // ── Init ──────────────────────────────────────────────────
  let _hierSelectsPopulated = false;
  function init() {
    loadSubmissions();
    submissionSel.addEventListener('change', onSubmissionChange);
    familySel.addEventListener('change', onFamilyChange);
    loadFactorsBtn.addEventListener('click', loadFactorList);

    selectAllBtn.addEventListener('click', () => { selectAll(true); renderTags(); });
    deselectAllBtn.addEventListener('click', () => { selectAll(false); renderTags(); });

    runCorrBtn.addEventListener('click', runCorrelation);
    corrSpearman.addEventListener('click', () => switchCorrType('spearman'));
    corrPearson.addEventListener('click', () => switchCorrType('pearson'));

    // method buttons
    const mBtns = document.querySelectorAll('.method-btn[data-method]');
    mBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        mBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentComboMethod = btn.dataset.method;
      });
    });

    runComboBtn.addEventListener('click', runCombination);

    initHeatmapButtons();
    runHierBtn.addEventListener('click', runHierarchy);
  }

  // ── Submissions ───────────────────────────────────────────
  async function loadSubmissions() {
    try {
      const resp = await fetch('/api/list_submissions');
      const data = await resp.json();
      submissionSel.innerHTML = '<option value="">— 请选择提交 —</option>';
      if (data.success && data.submissions) {
        data.submissions.forEach(s => {
          const opt = document.createElement('option');
          opt.value = s.id;
          opt.textContent = `#${s.id} (${s.product_count} 个产品)`;
          submissionSel.appendChild(opt);
        });
      }
    } catch (e) {
      console.error('loadSubmissions', e);
    }
  }

  function onSubmissionChange() {
    const id = submissionSel.value;
    familySel.innerHTML = '<option value="">加载中...</option>';
    allFactors = [];
    selectedFactors.clear();
    renderTags();
    if (!id) {
      familySel.innerHTML = '<option value="">— 请先创建提交 —</option>';
      return;
    }
    loadFamilies();
  }

  async function loadFamilies() {
    const id = submissionSel.value;
    if (!id) return;
    try {
      const resp = await fetch(`/api/list_factor_families?submission_id=${id}`);
      const data = await resp.json();
      familySel.innerHTML = '<option value="">— 选择因子家族 —</option>';
      if (data.success && data.families) {
        data.families.forEach(f => {
          const opt = document.createElement('option');
          opt.value = f.alias;
          opt.textContent = f.alias + (f.chinese_name ? ` (${f.chinese_name})` : '');
          familySel.appendChild(opt);
        });
      }
    } catch (e) {
      console.error('loadFamilies', e);
    }
  }

  function onFamilyChange() {
    allFactors = [];
    selectedFactors.clear();
    renderTags();
  }

  // ── Factor list ───────────────────────────────────────────
  async function loadFactorList() {
    const id = submissionSel.value;
    const family = familySel.value;
    if (!id) { alert('请先选择提交'); return; }
    if (!family) { alert('请先选择因子家族'); return; }

    tagsWrap.innerHTML = '<span style="color:#888;">加载中...</span>';
    try {
      const resp = await fetch(`/api/factor_list?submission_id=${id}&family=${family}`);
      const data = await resp.json();
      if (data.success && data.factors) {
        allFactors = data.factors;
        selectedFactors.clear();
        // auto select all
        allFactors.forEach(f => selectedFactors.add(f.alias));
        renderTags();
      } else {
        tagsWrap.innerHTML = '<span style="color:#888;">无可用因子</span>';
      }
    } catch (e) {
      console.error('loadFactorList', e);
      tagsWrap.innerHTML = '<span style="color:#d40000;">加载失败</span>';
    }
  }

  function selectAll(sel) {
    if (sel) allFactors.forEach(f => selectedFactors.add(f.alias));
    else selectedFactors.clear();
  }

  function toggleFactor(alias) {
    if (selectedFactors.has(alias)) selectedFactors.delete(alias);
    else selectedFactors.add(alias);
    renderTags();
  }

  function renderTags() {
    selectedCount.textContent = selectedFactors.size;
    if (!allFactors.length) {
      tagsWrap.innerHTML = '<span style="color:#888;font-size:13px;">选择测试器和因子家族后加载因子</span>';
      return;
    }
    tagsWrap.innerHTML = allFactors.map(f => {
      const cls = selectedFactors.has(f.alias) ? 'factor-tag selected' : 'factor-tag';
      return `<span class="${cls}" data-alias="${f.alias}">${f.alias}</span>`;
    }).join('');

    tagsWrap.querySelectorAll('.factor-tag').forEach(tag => {
      tag.addEventListener('click', () => toggleFactor(tag.dataset.alias));
    });

    // 更新分层选择器的因子列表
    populateHierSelects();
  }

  function getSelectedAliases() {
    return allFactors.filter(f => selectedFactors.has(f.alias)).map(f => f.alias);
  }

  // ── Correlation ───────────────────────────────────────────
  function switchCorrType(type) {
    currentCorrType = type;
    corrSpearman.classList.toggle('active', type === 'spearman');
    corrPearson.classList.toggle('active', type === 'pearson');
    if (corrMatrix) {
      renderCorrelation(corrMatrix);
    }
  }

  async function runCorrelation() {
    const id = submissionSel.value;
    const family = familySel.value;
    const aliases = getSelectedAliases();

    if (!id) { alert('请选择提交'); return; }
    if (!family) { alert('请选择因子家族'); return; }
    if (aliases.length < 2) { alert('请至少选择2个因子'); return; }

    corrStatus.textContent = '计算中...';
    corrContainer.innerHTML = '<div style="text-align:center;padding:24px;color:#888;">计算中...</div>';
    runCorrBtn.disabled = true;

    try {
      const resp = await fetch('/run_mfa_correlation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          submission_id: id,
          factor_family_alias: family,
          factor_aliases: aliases
        })
      });
      const data = await resp.json();
      if (data.success) {
        corrMatrix = data;
        currentCorrType = 'spearman';
        corrSpearman.classList.add('active');
        corrPearson.classList.remove('active');
        renderCorrelation(data);
        corrStatus.textContent = `✓ N=${data.n_obs}`;
        corrStatus.style.color = '#2e7d32';
      } else {
        corrContainer.innerHTML = `<div style="color:#d40000;padding:20px;">${data.error || '计算失败'}</div>`;
        corrStatus.textContent = '✗ 失败';
        corrStatus.style.color = '#d40000';
      }
    } catch (e) {
      console.error('runCorrelation', e);
      corrStatus.textContent = '✗ 网络错误';
      corrStatus.style.color = '#d40000';
    } finally {
      runCorrBtn.disabled = false;
    }
  }

  function renderCorrelation(data) {
    const type = currentCorrType;
    const src = data[type];
    if (!src) { corrContainer.innerHTML = '<div style="color:#888;">无数据</div>'; return; }

    const labels = src.labels;
    const matrix = src.matrix;
    const n = labels.length;

    // build full symmetric matrix for display
    const full = [];
    for (let i = 0; i < n; i++) {
      full[i] = [];
      for (let j = 0; j < n; j++) {
        if (i === j) full[i][j] = 1.0;
        else if (j > i) full[i][j] = matrix[j] ? matrix[j][i] : null; // mirror upper
        else full[i][j] = matrix[i] ? matrix[i][j] : null;
      }
    }

    function colorFor(v) {
      if (v == null) return '#f0f0f0';
      const abs = Math.abs(v);
      if (v > 0) {
        const r = 220, g = Math.round(220 - abs * 180), b = Math.round(220 - abs * 180);
        return `rgb(${r},${g},${b})`;
      } else {
        const r = Math.round(220 - abs * 180), g = 220, b = Math.round(220 - abs * 180);
        return `rgb(${r},${g},${b})`;
      }
    }

    let html = '<table class="corr-table"><tr><td class="label-cell"></td>';
    // column headers (vertical)
    for (let j = 0; j < n; j++) {
      html += `<td class="label-col">${labels[j]}</td>`;
    }
    html += '</tr>';

    for (let i = 0; i < n; i++) {
      html += '<tr>';
      html += `<td class="label-cell">${labels[i]}</td>`;
      for (let j = 0; j < n; j++) {
        const v = full[i][j];
        const display = v == null ? '' : v.toFixed(2);
        html += `<td><div class="corr-cell" style="background:${colorFor(v)}">${display}</div></td>`;
      }
      html += '</tr>';
    }
    html += '</table>';
    corrContainer.innerHTML = html;
  }

  // ── Combination ──────────────────────────────────────────
  async function runCombination() {
    const id = submissionSel.value;
    const family = familySel.value;
    const aliases = getSelectedAliases();
    const nGroups = parseInt(nGroupsInput.value) || 5;

    if (!id) { alert('请选择提交'); return; }
    if (!family) { alert('请选择因子家族'); return; }
    if (aliases.length < 2) { alert('请至少选择2个因子'); return; }

    comboStatus.textContent = '运行中...';
    comboStatus.style.color = '#888';
    weightsContainer.innerHTML = '';
    comboChartDiv.style.display = 'none';
    runComboBtn.disabled = true;

    try {
      const resp = await fetch('/run_mfa_combination', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          submission_id: id,
          factor_family_alias: family,
          factor_aliases: aliases,
          method: currentComboMethod,
          n_groups: nGroups,
          return_freq: returnFreqSel.value || null
        })
      });
      const data = await resp.json();
      if (data.success) {
        comboStatus.textContent = '✓ 完成';
        comboStatus.style.color = '#2e7d32';

        // show weights
        if (data.weights) {
          let metaHtml = '';
          if (data.optimization_metrics) {
            const m = data.optimization_metrics;
            metaHtml = ` <span style="font-size:11px;color:#888;margin-left:8px;">
              预期收益=${m.expected_return?.toFixed(4)||'-'} | 
              预期波动=${m.expected_vol?.toFixed(4)||'-'} | 
              夏普=${m.sharpe?.toFixed(4)||'-'}</span>`;
          }
          weightsContainer.innerHTML = '<div style="margin-top:8px;"><strong>因子权重：</strong>' +
            Object.entries(data.weights).map(([k, v]) =>
              `<span class="weight-tag">${k}: ${(v*100).toFixed(1)}%</span>`
            ).join(' ') + metaHtml + '</div>';
        }

        // draw chart
        if (data.groups && data.groups.length) {
          comboChartDiv.style.display = 'block';
          drawComboChart(data);
        }
      } else {
        comboStatus.textContent = '✗ ' + (data.error || '运行失败');
        comboStatus.style.color = '#d40000';
      }
    } catch (e) {
      console.error('runCombination', e);
      comboStatus.textContent = '✗ 网络错误';
      comboStatus.style.color = '#d40000';
    } finally {
      runComboBtn.disabled = false;
    }
  }

  function drawComboChart(data) {
    if (typeof Highcharts === 'undefined') {
      comboChartDiv.innerHTML = '<div style="color:#888;padding:20px;">Highcharts 未加载</div>';
      return;
    }

    const series = data.groups.map(g => ({
      name: g.name,
      data: g.timestamps.map((t, i) => [t * 1000, g.cumulative_returns[i]]),
      type: 'line',
      lineWidth: 2,
      marker: { enabled: false }
    }));

    Highcharts.stockChart('mf-combo-chart', {
      chart: { animation: false },
      title: { text: `合成因子分组回测 (${data.method})` },
      xAxis: { type: 'datetime', title: { text: '时间' } },
      yAxis: { title: { text: '累计收益' } },
      series: series,
      credits: { enabled: false },
      rangeSelector: { enabled: false },
      navigator: { enabled: false },
      scrollbar: { enabled: false }
    });
  }

  // ── Heatmap ─────────────────────────────────────────────
  const heatmapGroupMonth  = $('#hm-group-month');
  const heatmapGroupQuarter = $('#hm-group-quarter');
  const heatmapMetricMeanIc = $('#hm-metric-mean_ic');
  const heatmapMetricCumIc  = $('#hm-metric-cum_ic');
  const heatmapMetricIr    = $('#hm-metric-ir');
  const heatmapReturnFreq  = $('#mf-hm-return-freq');
  const runHeatmapBtn      = $('#mf-run-heatmap-btn');
  const heatmapStatus      = $('#mf-heatmap-status');
  const heatmapContainer   = $('#mf-heatmap-container');

  let hmGroupBy = 'month';
  let hmMetric  = 'mean_ic';

  function initHeatmapButtons() {
    function toggleGroup(active, inactive) {
      active.classList.add('active');
      inactive.classList.remove('active');
    }
    heatmapGroupMonth.addEventListener('click', () => { toggleGroup(heatmapGroupMonth, heatmapGroupQuarter); hmGroupBy = 'month'; });
    heatmapGroupQuarter.addEventListener('click', () => { toggleGroup(heatmapGroupQuarter, heatmapGroupMonth); hmGroupBy = 'quarter'; });

    const mBtns = [heatmapMetricMeanIc, heatmapMetricCumIc, heatmapMetricIr];
    heatmapMetricMeanIc.addEventListener('click', () => { mBtns.forEach(b => b.classList.remove('active')); heatmapMetricMeanIc.classList.add('active'); hmMetric = 'mean_ic'; });
    heatmapMetricCumIc.addEventListener('click', () => { mBtns.forEach(b => b.classList.remove('active')); heatmapMetricCumIc.classList.add('active'); hmMetric = 'cum_ic'; });
    heatmapMetricIr.addEventListener('click', () => { mBtns.forEach(b => b.classList.remove('active')); heatmapMetricIr.classList.add('active'); hmMetric = 'ir'; });

    runHeatmapBtn.addEventListener('click', runHeatmap);
  }

  async function runHeatmap() {
    const id = submissionSel.value;
    const family = familySel.value;
    const aliases = getSelectedAliases();

    if (!id) { alert('请选择提交'); return; }
    if (!family) { alert('请选择因子家族'); return; }
    if (aliases.length < 2) { alert('请至少选择2个因子'); return; }

    heatmapStatus.textContent = '计算中...';
    heatmapStatus.style.color = '#888';
    runHeatmapBtn.disabled = true;

    try {
      const resp = await fetch('/run_mfa_heatmap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          submission_id: id,
          factor_family_alias: family,
          factor_aliases: aliases,
          return_freq: heatmapReturnFreq.value || null,
          group_by: hmGroupBy,
          metric: hmMetric
        })
      });
      const data = await resp.json();
      if (data.success) {
        renderHeatmap(data);
        heatmapStatus.textContent = '✓ 完成';
        heatmapStatus.style.color = '#2e7d32';
      } else {
        heatmapContainer.innerHTML = `<div style="color:#d40000;padding:20px;">${data.error || '生成失败'}</div>`;
        heatmapStatus.textContent = '✗ 失败';
        heatmapStatus.style.color = '#d40000';
      }
    } catch (e) {
      console.error('runHeatmap', e);
      heatmapStatus.textContent = '✗ 网络错误';
      heatmapStatus.style.color = '#d40000';
    } finally {
      runHeatmapBtn.disabled = false;
    }
  }

  function renderHeatmap(data) {
    const factors = data.factors;
    const periods = data.periods;
    const matrix  = data.matrix;  // [factors][periods]

    // 找值域范围用于颜色映射
    let vmin = Infinity, vmax = -Infinity;
    for (const row of matrix) {
      for (const v of row) {
        if (v != null) {
          if (v < vmin) vmin = v;
          if (v > vmax) vmax = v;
        }
      }
    }
    if (!isFinite(vmin)) vmin = -0.1;
    if (!isFinite(vmax)) vmax = 0.1;
    const range = vmax - vmin || 0.01;

    function heatColor(v) {
      if (v == null) return '#f0f0f0';
      const t = (v - vmin) / range;  // 0~1
      // 蓝(负) → 白(0) → 红(正)
      if (t < 0.5) {
        const s = t * 2;
        const r = Math.round(100 + s * 120);
        const g = Math.round(100 + s * 120);
        const b = Math.round(240);
        return `rgb(${r},${g},${b})`;
      } else {
        const s = (t - 0.5) * 2;
        const r = Math.round(240);
        const g = Math.round(100 + (1 - s) * 120);
        const b = Math.round(100 + (1 - s) * 120);
        return `rgb(${r},${g},${b})`;
      }
    }

    let html = '<table class="corr-table"><tr><td class="label-cell"></td>';
    for (const p of periods) {
      html += `<td class="label-cell" style="font-size:10px;">${p}</td>`;
    }
    html += '</tr>';

    for (let i = 0; i < factors.length; i++) {
      html += '<tr>';
      html += `<td class="label-cell">${factors[i]}</td>`;
      for (let j = 0; j < periods.length; j++) {
        const v = matrix[i] ? matrix[i][j] : null;
        const display = v == null ? '' : v.toFixed(4);
        html += `<td><div class="corr-cell" style="background:${heatColor(v)}">${display}</div></td>`;
      }
      html += '</tr>';
    }
    html += '</table>';
    html += `<div style="margin-top:8px;font-size:11px;color:#888;">
      <span>蓝 (${vmin.toFixed(4)})</span>
      <span style="display:inline-block;width:120px;height:10px;background:linear-gradient(to right, rgb(100,100,240), rgb(220,220,220), rgb(240,100,100));margin:0 6px;vertical-align:middle;border-radius:2px;"></span>
      <span>红 (${vmax.toFixed(4)})</span>
    </div>`;
    heatmapContainer.innerHTML = html;
  }

  // ── Hierarchy ──────────────────────────────────────────
  const hierFactorA    = $('#mf-hier-factor-a');
  const hierFactorB    = $('#mf-hier-factor-b');
  const hierNGroupsA   = $('#mf-hier-n-groups-a');
  const hierNGroupsB   = $('#mf-hier-n-groups-b');
  const hierReturnFreq = $('#mf-hier-return-freq');
  const runHierBtn     = $('#mf-run-hierarchy-btn');
  const hierStatus     = $('#mf-hier-status');
  const hierContainer  = $('#mf-hierarchy-container');

  function populateHierSelects() {
    const aliases = getSelectedAliases();
    const options = allFactors
      .filter(f => selectedFactors.has(f.alias))
      .map(f => `<option value="${f.alias}">${f.alias}</option>`)
      .join('');
    hierFactorA.innerHTML = '<option value="">— 选择因子 —</option>' + options;
    hierFactorB.innerHTML = '<option value="">— 选择因子 —</option>' + options;
  }

  async function runHierarchy() {
    const id = submissionSel.value;
    const family = familySel.value;
    const aAlias = hierFactorA.value;
    const bAlias = hierFactorB.value;
    const nA = parseInt(hierNGroupsA.value) || 3;
    const nB = parseInt(hierNGroupsB.value) || 5;

    if (!id) { alert('请选择提交'); return; }
    if (!family) { alert('请选择因子家族'); return; }
    if (!aAlias || !bAlias) { alert('请选择因子A和因子B'); return; }
    if (aAlias === bAlias) { alert('请选择两个不同的因子'); return; }

    hierStatus.textContent = '运行中...';
    hierStatus.style.color = '#888';
    runHierBtn.disabled = true;

    try {
      const resp = await fetch('/run_mfa_hierarchy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          submission_id: id,
          factor_family_alias: family,
          factor_a_alias: aAlias,
          factor_b_alias: bAlias,
          n_groups_a: nA,
          n_groups_b: nB,
          return_freq: hierReturnFreq.value || null
        })
      });
      const data = await resp.json();
      if (data.success) {
        renderHierarchy(data);
        hierStatus.textContent = '✓ 完成';
        hierStatus.style.color = '#2e7d32';
      } else {
        hierContainer.innerHTML = `<div style="color:#d40000;padding:20px;">${data.error || '运行失败'}</div>`;
        hierStatus.textContent = '✗ 失败';
        hierStatus.style.color = '#d40000';
      }
    } catch (e) {
      console.error('runHierarchy', e);
      hierStatus.textContent = '✗ 网络错误';
      hierStatus.style.color = '#d40000';
    } finally {
      runHierBtn.disabled = false;
    }
  }

  function renderHierarchy(data) {
    if (typeof Highcharts === 'undefined') {
      hierContainer.innerHTML = '<div style="color:#888;padding:20px;">Highcharts 未加载</div>';
      return;
    }

    let html = '';

    // 因子 A 参考分组图表
    if (data.factor_a_groups && data.factor_a_groups.length) {
      html += `<h4 style="font-size:14px;margin:12px 0 8px;">因子A (${data.factor_a}) 分组参考</h4>`;
      html += `<div id="hier-chart-a" class="mf-chart-container" style="height:300px;"></div>`;
    }

    // 整理 A 组的数据用于汇总表
    let summaryRows = '';

    // 每个 A 层一个子图
    const layers = data.layers || [];
    const validLayers = layers.filter(l => l.sub_groups && l.sub_groups.length > 0);
    
    for (let li = 0; li < layers.length; li++) {
      const layer = layers[li];
      const chartId = `hier-chart-${li}`;
      
      if (!layer.sub_groups || layer.sub_groups.length === 0) {
        html += `<div style="margin:8px 0;padding:12px;background:#fff3e0;border-radius:6px;font-size:12px;color:#e65100;">
          <strong>${layer.label_a}</strong>: ${layer.error || '品种数不足，无法子分层'}
        </div>`;
        continue;
      }

      html += `<div style="margin:16px 0;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">`;
      html += `<div style="background:#f8fafc;padding:10px 16px;font-weight:600;font-size:14px;border-bottom:1px solid #e2e8f0;">
        ${layer.label_a} (因子A: ${data.factor_a})
      </div>`;
      html += `<div style="padding:12px;">`;

      // 绩效指标表
      const hasMetrics = layer.sub_groups.some(g => g.metrics && Object.keys(g.metrics).length > 0);
      if (hasMetrics) {
        html += `<table class="corr-table" style="margin-bottom:12px;font-size:11px;">
          <tr style="background:#f1f5f9;">
            <td class="label-cell" style="font-weight:600;">子组</td>
            <td class="label-cell" style="font-weight:600;">累计收益</td>
            <td class="label-cell" style="font-weight:600;">年化收益</td>
            <td class="label-cell" style="font-weight:600;">夏普</td>
            <td class="label-cell" style="font-weight:600;">最大回撤</td>
          </tr>`;
        for (const sg of layer.sub_groups) {
          const m = sg.metrics || {};
          html += `<tr>
            <td class="label-cell">${sg.name}</td>
            <td class="label-cell">${m.TotalReturn != null ? (m.TotalReturn*100).toFixed(2)+'%' : '-'}</td>
            <td class="label-cell">${m.AnnualReturn != null ? (m.AnnualReturn*100).toFixed(2)+'%' : '-'}</td>
            <td class="label-cell">${m.Sharpe != null ? m.Sharpe.toFixed(2) : '-'}</td>
            <td class="label-cell">${m.MaxDrawdown != null ? (m.MaxDrawdown*100).toFixed(2)+'%' : '-'}</td>
          </tr>`;
        }
        html += `</table>`;
      }

      // 子组图表
      html += `<div id="${chartId}" class="mf-chart-container" style="height:250px;"></div>`;
      html += `</div></div>`;

      // 构建汇总行
      const s = data.summary && data.summary[layer.group_a] ? data.summary[layer.group_a] : {};
      summaryRows += `<tr>
        <td class="label-cell">${layer.label_a}</td>
        <td class="label-cell">${s.mean_ret != null ? (s.mean_ret*100).toFixed(2)+'%' : '-'}</td>
        <td class="label-cell">${s.mean_sharpe != null ? s.mean_sharpe.toFixed(2) : '-'}</td>
        <td class="label-cell">${s.best_group || '-'}</td>
      </tr>`;
    }

    // 汇总表
    if (summaryRows) {
      html = `<h4 style="font-size:14px;margin:0 0 8px;">📊 分层汇总</h4>
        <table class="corr-table" style="margin-bottom:16px;font-size:11px;">
          <tr style="background:#f1f5f9;">
            <td class="label-cell" style="font-weight:600;">A组</td>
            <td class="label-cell" style="font-weight:600;">B子组平均收益</td>
            <td class="label-cell" style="font-weight:600;">B子组平均夏普</td>
            <td class="label-cell" style="font-weight:600;">最佳B子组</td>
          </tr>${summaryRows}
        </table>` + html;
    }

    hierContainer.innerHTML = html;

    // 延迟渲染 Highcharts 图表
    setTimeout(() => {
      // 因子 A 参考图
      if (data.factor_a_groups && data.factor_a_groups.length) {
        const aChartDiv = document.getElementById('hier-chart-a');
        if (aChartDiv) {
          renderHierarchyChart('hier-chart-a', data.factor_a_groups, `因子A (${data.factor_a}) 分组表现`);
        }
      }

      // 每个 A 层的子图表
      for (let li = 0; li < layers.length; li++) {
        const layer = layers[li];
        if (!layer.sub_groups || layer.sub_groups.length === 0) continue;
        const chartId = `hier-chart-${li}`;
        const chartDiv = document.getElementById(chartId);
        if (chartDiv) {
          renderHierarchyChart(chartId, layer.sub_groups, `${layer.label_a} → 因子B (${data.factor_b}) 子组表现`);
        }
      }
    }, 50);
  }

  function renderHierarchyChart(divId, groups, title) {
    const series = groups.map(g => ({
      name: g.name,
      data: (g.timestamps || []).map((t, i) => [t * 1000, (g.cumulative_returns || [])[i]]),
      type: 'line',
      lineWidth: 1.5,
      marker: { enabled: false }
    }));

    Highcharts.stockChart(divId, {
      chart: { animation: false },
      title: { text: title, style: { fontSize: '13px' } },
      xAxis: { type: 'datetime', title: { text: '' } },
      yAxis: { title: { text: '' } },
      series: series,
      credits: { enabled: false },
      rangeSelector: { enabled: false },
      navigator: { enabled: false },
      scrollbar: { enabled: false }
    });
  }

  // ── Bootstrap ─────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
