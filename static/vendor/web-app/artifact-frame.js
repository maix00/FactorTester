// This document has an opaque sandbox origin. Only its parent can supply bytes;
// grants, cookies and the parent's document are never exposed to the report.
(() => {
  function receive(event) {
    if (event.source !== parent || event.data?.type !== "tr-artifact-html" || !(event.data.bytes instanceof ArrayBuffer)) return;
    removeEventListener("message", receive);
    let html = new TextDecoder().decode(event.data.bytes);
    // Nautilus' multi-column Plotly report is a wide analytical document.
    // Preserve its table geometry on phones instead of squeezing labels/cells.
    if(event.data.layout === "wide")html=html.replace("</head>","<style>@media(max-width:700px){body{min-width:960px;margin:0}}</style></head>");
    document.open(); document.write(html); document.close();
  }
  addEventListener("message", receive);
})();
