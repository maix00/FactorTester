import { assetURL } from "./assets.ts";
const mobile = window.matchMedia("(max-width: 760px)").matches;
const prefix = "/research-static/vendor/web-app";
const link = document.createElement("link");
link.rel = "stylesheet";
link.href = assetURL(`${prefix}/${mobile ? "mobile" : "desktop"}.css`);
document.head.append(link);
const script = document.createElement("script");
script.src = assetURL(`${prefix}/${mobile ? "mobile" : "desktop"}.js`);
document.body.append(script);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => undefined);
}
