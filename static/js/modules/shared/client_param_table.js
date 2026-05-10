(function() {
    function escHtml(value) {
        const d = document.createElement('div');
        d.textContent = value == null ? '' : String(value);
        return d.innerHTML;
    }

    function getDefaultValue(paramDef) {
        if (!paramDef) return '';
        const value = paramDef.default_value ?? '';
        return value == null ? '' : String(value);
    }

    function getParamOptions(paramDef) {
        return Array.isArray(paramDef?.options) ? paramDef.options : [];
    }

    function renderAddControl(paramDef, prefix) {
        const alias = paramDef.alias;
        const mode = paramDef.input_mode || 'text';
        const options = getParamOptions(paramDef);
        const def = getDefaultValue(paramDef);
        const values = options.map(opt => String(opt.value));
        if (options.length && mode === 'enum') {
            return '<div class="param-input-stack"><select id="' + prefix + escHtml(alias) + '" class="param-input-control">' +
                options.map(opt => '<option value="' + escHtml(opt.value) + '"' + (String(opt.value) === def ? ' selected' : '') + '>' + escHtml(opt.label || opt.value) + '</option>').join('') +
                '</select></div>';
        }
        if (options.length && mode === 'enum_custom') {
            const custom = values.indexOf(def) === -1;
            return '<div class="param-input-stack"><select id="' + prefix + escHtml(alias) + '" class="param-input-control" data-custom-input-id="' + prefix + 'custom-' + escHtml(alias) + '">' +
                options.map(opt => '<option value="' + escHtml(opt.value) + '"' + (String(opt.value) === def ? ' selected' : '') + '>' + escHtml(opt.label || opt.value) + '</option>').join('') +
                '<option value="__custom__"' + (custom ? ' selected' : '') + '>其他...</option></select>' +
                '<input type="text" id="' + prefix + 'custom-' + escHtml(alias) + '" class="param-input-control" value="' + (custom ? escHtml(def) : '') + '" style="' + (custom ? '' : 'display:none;') + '">' +
                (paramDef.type === 'FactorParam' ? '<button type="button" class="param-btn factor-param-picker-btn" data-param-prefix="' + escHtml(prefix) + '" data-param-alias="' + escHtml(alias) + '">选择因子</button>' : '') +
                '</div>';
        }
        return '<div class="param-input-stack"><input type="text" id="' + prefix + escHtml(alias) + '" class="param-input-control" value="' + escHtml(def) + '"></div>';
    }

    function buildAlias(familyAlias, aliases, row) {
        if (row && row.__factor_alias) return row.__factor_alias;
        const parts = [];
        aliases.forEach(alias => {
            const value = row[alias] == null ? '' : String(row[alias]);
            if (value !== '') parts.push(alias + ':' + value);
        });
        return parts.length ? familyAlias + '|' + parts.join('|') : familyAlias;
    }

    window.ClientParamTable = {
        render(options) {
            const tbody = document.getElementById(options.tbodyId);
            const thead = document.getElementById(options.theadId);
            if (!tbody) return;
            const familyAlias = options.familyAlias || '';
            const params = options.params || [];
            const aliases = params.map(p => p.alias);
            const rows = options.rows || [];
            const callbacks = options.callbacks || {};

            if (thead) {
                thead.innerHTML = '<tr>' +
                    '<th style="min-width:100px;">因子(家族)名</th>' +
                    params.map(p => '<th title="' + escHtml(p.desc || p.name || '') + '">' + escHtml(p.alias) + '</th>').join('') +
                    '<th style="min-width:80px;">操作</th>' +
                    '</tr>';
            }

            let html = '<tr id="add_row"><td>' + escHtml(familyAlias) + '</td>';
            aliases.forEach(alias => {
                const pd = params.find(p => p.alias === alias);
                html += '<td>' + renderAddControl(pd || { alias }, 'param-new-') + '</td>';
            });
            html += '<td><button class="param-btn" data-param-action="add">新增</button></td></tr>';

            rows.forEach((row, index) => {
                html += '<tr draggable="true" data-param-idx="' + index + '">';
                html += '<td>' + escHtml(buildAlias(familyAlias, aliases, row)) + '</td>';
                aliases.forEach(alias => {
                    html += '<td>' + escHtml(row[alias] == null ? '' : row[alias]) + '</td>';
                });
                html += '<td><button class="param-btn param-btn-danger" data-param-action="delete" data-param-idx="' + index + '">删除</button></td>';
                html += '</tr>';
            });
            tbody.innerHTML = html;

            tbody.querySelectorAll('#add_row input, #add_row select').forEach(control => {
                control.addEventListener('keydown', event => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        callbacks.add?.();
                    }
                });
                if (control.tagName === 'SELECT') {
                    control.addEventListener('change', () => {
                        const custom = document.getElementById(control.dataset.customInputId || '');
                        if (custom) custom.style.display = control.value === '__custom__' ? '' : 'none';
                    });
                }
            });
            tbody.querySelectorAll('.factor-param-picker-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const prefix = btn.dataset.paramPrefix || 'param-new-';
                    const alias = btn.dataset.paramAlias || '';
                    if (typeof window.openSharedFactorParamPicker === 'function') {
                        window.openSharedFactorParamPicker(alias, value => {
                            const select = document.getElementById(prefix + alias);
                            const custom = document.getElementById(prefix + 'custom-' + alias);
                            if (select) select.value = '__custom__';
                            if (custom) {
                                custom.value = value;
                                custom.style.display = '';
                            }
                        });
                    } else {
                        alert('因子选择面板未加载');
                    }
                });
            });
            tbody.querySelector('[data-param-action="add"]')?.addEventListener('click', () => callbacks.add?.());
            tbody.querySelectorAll('[data-param-action="delete"]').forEach(btn => {
                btn.addEventListener('click', () => callbacks.delete?.(Number(btn.dataset.paramIdx)));
            });

            let dragStartIdx = null;
            tbody.querySelectorAll('tr[draggable="true"]').forEach(row => {
                row.addEventListener('dragstart', event => {
                    dragStartIdx = Number(row.dataset.paramIdx);
                    row.style.opacity = '0.5';
                    event.dataTransfer.effectAllowed = 'move';
                });
                row.addEventListener('dragend', () => {
                    dragStartIdx = null;
                    row.style.opacity = '';
                    row.classList.remove('drag-over');
                });
                row.addEventListener('dragover', event => {
                    event.preventDefault();
                    row.classList.add('drag-over');
                });
                row.addEventListener('dragleave', () => row.classList.remove('drag-over'));
                row.addEventListener('drop', event => {
                    event.preventDefault();
                    row.classList.remove('drag-over');
                    const targetIdx = Number(row.dataset.paramIdx);
                    if (dragStartIdx !== null && dragStartIdx !== targetIdx) {
                        callbacks.reorder?.(dragStartIdx, targetIdx);
                    }
                });
            });
        },

        collectAddRow(prefix, aliases, params) {
            const row = {};
            aliases.forEach(alias => {
                const input = document.getElementById(prefix + alias);
                const pd = params.find(p => p.alias === alias);
                if (input && pd?.input_mode === 'enum_custom' && input.value === '__custom__') {
                    const custom = document.getElementById(prefix + 'custom-' + alias);
                    row[alias] = custom && custom.value ? custom.value : getDefaultValue(pd);
                } else {
                    row[alias] = input && input.value ? input.value : getDefaultValue(pd);
                }
            });
            return row;
        },
    };
})();
