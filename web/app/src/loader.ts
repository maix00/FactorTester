import { assetURL } from "./assets.ts";
import { mobileLayout } from "./layout-mode.ts";
const mobile = mobileLayout(window.matchMedia("(max-width: 760px)").matches,
  navigator.userAgent, navigator.platform, navigator.maxTouchPoints);
document.documentElement.classList.toggle("tr-mobile-runtime", mobile);
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
