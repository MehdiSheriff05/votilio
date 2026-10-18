(function () {
  try {
    var saved = localStorage.getItem("votilio-theme");
    var light = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
    document.documentElement.dataset.theme = saved || (light ? "light" : "dark");
  } catch (e) { document.documentElement.dataset.theme = "dark"; }
})();
