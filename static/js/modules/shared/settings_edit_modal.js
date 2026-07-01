/**
 * settings_edit_modal.js — 中立的"设置行编辑模态"公共组件（window.SettingsEditModal）。
 *
 * 配合 SettingsRowList：点击一行进入编辑模式时打开。组件负责编辑模态的**生命周期**
 * （遮罩、容器、保存/取消、点背景关闭、新增 vs 编辑），**表单字段由调用方注入**——
 * 组件不知道字段是 factor/产品路径/ic_correlation 等领域内容。
 *
 *   SettingsEditModal.open({
 *     title: '编辑 IC 配置',
 *     mode: 'edit' | 'new',
 *     saveLabel: '保存',                       // 可选，默认按 mode
 *     renderBody: function(host) { ... },       // 把表单字段渲染进 host
 *     collect: function(host) { return data; }, // 从 host 收集编辑结果；返回 false/抛错则不关闭
 *     onSave: function(data) {},                // collect 成功后回调
 *     onCancel: function() {},                  // 可选
 *   });
 *   SettingsEditModal.close();
 */
(function() {
    if (window.SettingsEditModal) return;

    var MODAL_ID = 'settings-edit-modal';

    function close() {
        var el = document.getElementById(MODAL_ID);
        if (el && el.parentNode) el.parentNode.removeChild(el);
    }

    function open(opts) {
        opts = opts || {};
        close();
        var mode = opts.mode === 'new' ? 'new' : 'edit';
        var saveLabel = opts.saveLabel || (mode === 'new' ? '新增' : '保存');

        var overlay = document.createElement('div');
        overlay.id = MODAL_ID;
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:10000;';

        var panel = document.createElement('div');
        panel.style.cssText = 'background:#fff;border-radius:10px;box-shadow:0 8px 40px rgba(0,0,0,0.18);width:520px;max-width:94vw;max-height:88vh;display:flex;flex-direction:column;overflow:hidden;';

        var header = document.createElement('div');
        header.style.cssText = 'padding:14px 18px;border-bottom:1px solid #eef2f7;font-size:15px;font-weight:700;color:#1a1a1a;';
        header.textContent = opts.title || (mode === 'new' ? '新增' : '编辑');

        var body = document.createElement('div');
        body.className = 'settings-edit-modal-body';
        body.style.cssText = 'padding:16px 18px;overflow:auto;flex:1;';

        var footer = document.createElement('div');
        footer.style.cssText = 'padding:12px 18px;border-top:1px solid #eef2f7;display:flex;justify-content:flex-end;gap:8px;';
        var cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.textContent = '取消';
        cancelBtn.style.cssText = 'padding:7px 16px;border:1px solid #d0d5dd;border-radius:6px;background:#fff;color:#475569;cursor:pointer;font-size:13px;';
        var saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.textContent = saveLabel;
        saveBtn.style.cssText = 'padding:7px 16px;border:none;border-radius:6px;background:#0078d4;color:#fff;cursor:pointer;font-size:13px;font-weight:600;';
        footer.appendChild(cancelBtn);
        footer.appendChild(saveBtn);

        panel.appendChild(header);
        panel.appendChild(body);
        panel.appendChild(footer);
        overlay.appendChild(panel);
        document.body.appendChild(overlay);

        if (typeof opts.renderBody === 'function') {
            try { opts.renderBody(body); }
            catch (e) { console.warn('[SettingsEditModal] renderBody 异常', e); }
        }

        function doCancel() {
            close();
            if (typeof opts.onCancel === 'function') opts.onCancel();
        }
        function doSave() {
            var data;
            if (typeof opts.collect === 'function') {
                try { data = opts.collect(body); }
                catch (e) { console.warn('[SettingsEditModal] collect 异常', e); return; }
                if (data === false || data === undefined) return;  // 校验失败：保持打开
            }
            close();
            if (typeof opts.onSave === 'function') opts.onSave(data);
        }

        cancelBtn.addEventListener('click', doCancel);
        saveBtn.addEventListener('click', doSave);
        overlay.addEventListener('click', function(e) { if (e.target === overlay) doCancel(); });

        return { close: close, body: body };
    }

    window.SettingsEditModal = { open: open, close: close };
})();
