// Light/dark theme toggle. The correct theme is already applied to <html> by the inline
// bootstrap in base.html; this script only renders the toggle button and persists changes.
(function () {
  var STORAGE_KEY = "lik-theme";
  var root = document.documentElement;
  var btn = document.getElementById("theme-toggle");

  // Show the icon of the theme you'd switch TO: a sun while dark, a moon while light.
  function icon(theme) { return theme === "dark" ? "☀" : "☾"; }
  function label(theme) { return theme === "dark" ? "Switch to light mode" : "Switch to dark mode"; }

  function render(theme) {
    if (!btn) return;
    btn.textContent = icon(theme);
    btn.setAttribute("aria-label", label(theme));
    btn.setAttribute("title", label(theme));
  }

  function current() { return root.dataset.theme === "dark" ? "dark" : "light"; }

  render(current());

  if (btn) {
    btn.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem(STORAGE_KEY, next); } catch (e) { /* storage unavailable — session-only */ }
      render(next);
    });
  }
})();
