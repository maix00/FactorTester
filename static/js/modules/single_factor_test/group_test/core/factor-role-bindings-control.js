(function(global) {
    'use strict';

    var ROLE_LABELS = {
        ranking: '排序',
        screen: '筛选',
        entry: '入场',
        exit: '退出',
        sizing: '目标权重',
    };

    function factorAlias(value) {
        if (typeof value === 'string') return value;
        if (!value || typeof value !== 'object') return '';
        return String(value.factorAlias || value.factor_alias || value.alias || value.name || '');
    }

    function normalizeBindings(value) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
        var result = {};
        Object.keys(value).forEach(function(role) {
            var alias = factorAlias(value[role]).trim();
            if (alias) result[role] = alias;
        });
        return result;
    }

    function visibleRoles(setting, strategyKind) {
        var serialization = setting && setting.serialization || {};
        var byKind = serialization.roles_by_strategy_kind || {};
        return (byKind[strategyKind] || serialization.allowed_roles || []).slice();
    }

    function displayValue(value) {
        var bindings = normalizeBindings(value);
        var roles = Object.keys(bindings);
        if (!roles.length) return '全部使用主因子';
        return roles.map(function(role) {
            return (ROLE_LABELS[role] || role) + '=' + bindings[role];
        }).join(' · ');
    }

    function render(options) {
        var setting = options.setting || {};
        var bindings = normalizeBindings(options.value);
        var candidates = (options.candidates || []).map(function(item) {
            return { alias: factorAlias(item), label: String(item && (item.label || item.alias || item.name) || item) };
        }).filter(function(item) { return item.alias; });
        var root = document.createElement('div');
        root.className = 'gt-factor-role-bindings';
        root.style.cssText = 'display:grid;gap:6px;min-width:240px;';
        visibleRoles(setting, options.strategyKind || 'group').forEach(function(role) {
            var row = document.createElement('label');
            row.style.cssText = 'display:grid;grid-template-columns:72px 1fr;align-items:center;gap:8px;';
            var label = document.createElement('span');
            label.textContent = ROLE_LABELS[role] || role;
            var select = document.createElement('select');
            var primary = document.createElement('option');
            primary.value = '';
            primary.textContent = '使用主因子';
            select.appendChild(primary);
            candidates.forEach(function(candidate) {
                var option = document.createElement('option');
                option.value = candidate.alias;
                option.textContent = candidate.label;
                select.appendChild(option);
            });
            select.value = bindings[role] || '';
            select.disabled = !!options.disabled;
            select.addEventListener('change', function() {
                var next = normalizeBindings(bindings);
                if (select.value) next[role] = select.value;
                else delete next[role];
                options.onChange(next);
            });
            row.appendChild(label);
            row.appendChild(select);
            root.appendChild(row);
        });
        return root;
    }

    global.FactorRoleBindingsControl = {
        displayValue: displayValue,
        normalizeBindings: normalizeBindings,
        render: render,
        visibleRoles: visibleRoles,
    };
})(window);
