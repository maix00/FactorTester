(() => {
  // The workbench does not own a second factor editor.  This adapter keeps the
  // existing call site stable while embedding the catalog component used by
  // the left navigation's Factor library tab.
  function open(context, state, onSaved) {
    return FTTestObjectEditorOverlay.open(context, {
      kind: "factor",
      mode: "create",
      ref: "new",
      testState: state,
      onSaved,
    });
  }

  window.FTStrategyEditorFactorOverlay = Object.freeze({open});
})();
