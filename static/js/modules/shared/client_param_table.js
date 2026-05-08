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

    function buildAlias(familyAlias, aliases, row) {
        const parts = [];
        aliases.forEach(alias => {
            const value = row[alias] == null ? '' : String(row[alias]);
            if (value !== '') parts.push(alias + '_' + value);
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
                html += '<td><input type="text" id="param-new-' + escHtml(alias) + '" value="' +
                    escHtml(getDefaultValue(pd)) + '"></td>';
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

            tbody.querySelectorAll('#add_row input').forEach(input => {
                input.addEventListener('keydown', event => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        callbacks.add?.();
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
                row[alias] = input && input.value ? input.value : getDefaultValue(pd);
            });
            return row;
        },
    };
})();
