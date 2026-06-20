function _factorWorkspaceOverlay() {
    return document.getElementById('factor-workspace-overlay');
}

function openFactorWorkspaceOverlay() {
    const overlay = _factorWorkspaceOverlay();
    if (!overlay) return;
    overlay.classList.add('open');
    if (typeof loadFactorSourceRoot === 'function') {
        loadFactorSourceRoot();
    }
}

function closeFactorWorkspaceOverlay() {
    const overlay = _factorWorkspaceOverlay();
    if (!overlay) return;
    overlay.classList.remove('open');
}
