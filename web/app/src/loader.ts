const mobile = window.matchMedia("(max-width: 760px)").matches;
const prefix = "/static/vendor/web-app";
const link = document.createElement("link");
link.rel = "stylesheet";
link.href = `${prefix}/${mobile ? "mobile" : "desktop"}.css`;
document.head.append(link);
const script = document.createElement("script");
script.src = `${prefix}/${mobile ? "mobile" : "desktop"}.js`;
document.body.append(script);
