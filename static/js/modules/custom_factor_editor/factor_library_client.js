(function() {
    'use strict';

    var factors = [];
    var selectedRef = null;
    var endpoint = '/custom-factors/api/client/factor-library';

    async function loadJSON(url) {
        var response = await fetch(url, {
            method: 'GET',
            headers: {'Accept': 'application/json'},
        });
        var payload = await response.json();
        if (!response.ok || payload.success === false) {
            throw new Error(payload.error || ('HTTP ' + response.status));
        }
        return payload;
    }

    function text(id, value) {
        document.getElementById(id).textContent = value || '—';
    }

    async function loadFactors() {
        var include = document.getElementById('include-subordinates').checked;
        var url = endpoint + (include ? '?include_subordinates=1' : '');
        try {
            var payload = await loadJSON(url);
            factors = payload.factors || [];
            renderList();
        } catch (error) {
            document.getElementById('factor-list').innerHTML =
                '<div class="empty">因子库加载失败</div>';
        }
    }

    function renderList() {
        var query = document.getElementById('factor-filter')
            .value.trim().toLowerCase();
        var list = document.getElementById('factor-list');
        list.innerHTML = '';
        factors.filter(function(item) {
            var haystack = [
                item.factor_alias,
                item.factor_family_alias,
                item.factor_family_name,
                item.chinese_name,
                item.category,
                item.owner_alias,
                item.owner_username,
                item.product_group,
            ].join(' ').toLowerCase();
            return !query || haystack.indexOf(query) >= 0;
        }).forEach(function(item) {
            var button = document.createElement('button');
            button.className = 'factor-item' +
                (item.factor_ref === selectedRef ? ' active' : '');
            var name = document.createElement('span');
            name.className = 'factor-name';
            name.textContent = item.chinese_name
                ? item.chinese_name + ' · ' + item.factor_alias
                : item.factor_alias;
            var subtitle = document.createElement('span');
            subtitle.className = 'factor-subtitle';
            subtitle.textContent = [
                item.factor_family_alias,
                item.category || '未分类',
                item.owner_alias || item.owner_username,
            ].filter(Boolean).join(' / ');
            button.appendChild(name);
            button.appendChild(subtitle);
            button.addEventListener('click', function() {
                selectFactor(item);
            });
            list.appendChild(button);
        });
        if (!list.childNodes.length) {
            list.innerHTML = '<div class="empty">没有匹配的因子</div>';
        }
    }

    function selectFactor(item) {
        selectedRef = item.factor_ref;
        renderList();
        document.getElementById('metadata-empty').hidden = true;
        document.getElementById('metadata-view').hidden = false;
        text('factor-title', item.factor_alias);
        text('factor-category', item.category || '未分类');
        text('factor-meta', item.chinese_name || '已登记因子');
        text(
            'factor-family',
            item.factor_family_name || item.factor_family_alias
        );
        text('factor-owner', item.owner_alias || item.owner_username);
        text('factor-product-group', item.product_group);
        text('factor-kind', item.factor_kind);
        var params = document.getElementById('factor-params');
        params.innerHTML = '';
        (item.params || []).forEach(function(param) {
            var row = document.createElement('div');
            row.className = 'param-row';
            var alias = document.createElement('span');
            alias.className = 'param-alias';
            alias.textContent = param.alias;
            var value = document.createElement('span');
            value.className = 'param-value';
            value.textContent = param.redacted ? '本地值已隐藏' : param.value;
            row.appendChild(alias);
            row.appendChild(value);
            params.appendChild(row);
        });
        if (!params.childNodes.length) {
            params.innerHTML = '<div class="empty">无参数</div>';
        }
    }

    document.getElementById('factor-filter')
        .addEventListener('input', renderList);
    document.getElementById('include-subordinates')
        .addEventListener('change', loadFactors);
    loadFactors();
})();
