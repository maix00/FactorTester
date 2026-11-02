/** Adapt chart event coordinates inside the CSS-rotated mobile panel. */
export function adaptRotatedChartInput(host: HTMLElement): () => void {
  if (!host.closest(".ant-modal")) return () => {};
  const types = ["mousedown", "mousemove", "mouseup", "click", "dblclick", "contextmenu", "wheel",
    "pointerdown", "pointermove", "pointerup", "pointercancel", "touchstart", "touchmove", "touchend", "touchcancel"];
  let activeTarget: Element | null = null;
  const normalize = (event: Event): void => {
    if (!host.closest(".tr-landscape-table-modal")) { activeTarget = null; return; }
    const actual = event.target;
    const inside = actual instanceof Element && host.contains(actual);
    if (inside && ["mousedown", "pointerdown", "touchstart"].includes(event.type)) activeTarget = actual;
    const target = inside ? actual : activeTarget;
    if (!target) return;
    const rect = target.getBoundingClientRect();
    const point = (value: {clientX: number; clientY: number; pageX: number; pageY: number; screenX: number; screenY: number}): void => {
      const x = rect.left + value.clientY - rect.top;
      const y = rect.top + rect.right - value.clientX;
      const pageX = x + value.pageX - value.clientX, pageY = y + value.pageY - value.clientY;
      const screenX = x + value.screenX - value.clientX, screenY = y + value.screenY - value.clientY;
      try {
        Object.defineProperties(value, {clientX:{value:x,configurable:true}, clientY:{value:y,configurable:true},
          pageX:{value:pageX,configurable:true},pageY:{value:pageY,configurable:true},
          screenX:{value:screenX,configurable:true},screenY:{value:screenY,configurable:true}});
      } catch { /* An event that cannot be extended is left unchanged. */ }
    };
    if (event instanceof MouseEvent) point(event);
    if (typeof TouchEvent !== "undefined" && event instanceof TouchEvent) {
      // WebKit can manufacture a new Touch wrapper on every TouchList access.
      // Replace the event's lists with stable copies rather than mutating an
      // ephemeral wrapper which the chart may never observe.
      for (const key of ["touches", "targetTouches", "changedTouches"] as const) {
        const list = Array.from(event[key], touch => {
          const copy = {identifier:touch.identifier, target:touch.target, clientX:touch.clientX, clientY:touch.clientY,
            pageX:touch.pageX, pageY:touch.pageY, screenX:touch.screenX, screenY:touch.screenY,
            radiusX:touch.radiusX, radiusY:touch.radiusY, rotationAngle:touch.rotationAngle, force:touch.force};
          point(copy); return copy;
        });
        try { Object.defineProperty(event, key, {value:list, configurable:true}); } catch { /* browser does not allow overriding lists */ }
      }
    }
    if (["mouseup", "pointerup", "pointercancel", "touchend", "touchcancel"].includes(event.type)) activeTarget = null;
  };
  for (const type of types) document.addEventListener(type, normalize, {capture:true, passive:true});
  return () => { for (const type of types) document.removeEventListener(type, normalize, true); };
}
