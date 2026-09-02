(() => {
  // The workbench does not own a second factor editor.  This adapter keeps the
  // existing call site stable while embedding the catalog component used by
  // the left navigation's Factor library tab.
  function open(context, state, onSaved, factor = null) {
    return FTTestLazyCode.openObjectEditor(context, {
      kind: "factor",
      mode: factor ? "edit" : "create",
      ref: factor ? FTTestFactorSelection.factorID(factor) : "new",
      initialValue: factor,
      testState: state,
      temporary: true,
      onSaved,
    });
  }

  window.FTStrategyEditorFactorOverlay = Object.freeze({open});
})();
