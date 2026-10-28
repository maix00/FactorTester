/** Share gestures across price, factor and trade charts. Vertical touch scroll
 * belongs to the containing page; horizontal drag/pinch belong to the chart. */
export const chartInteraction = {
  handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
  handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
};
