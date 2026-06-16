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
    if (typeof startFactorWorkspaceAutoPush === 'function') {
        startFactorWorkspaceAutoPush();
    }
}

function closeFactorWorkspaceOverlay() {
    const overlay = _factorWorkspaceOverlay();
    if (!overlay) return;
    overlay.classList.remove('open');
    if (typeof stopFactorWorkspaceAutoPush === 'function') {
        stopFactorWorkspaceAutoPush();
    }
}
