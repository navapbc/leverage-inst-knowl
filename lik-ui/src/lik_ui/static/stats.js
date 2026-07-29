// Over-time chart for the stats pages. The server emits raw per-session {created_at (UTC ISO),
// tokens} in #tokens-over-time[data-series]; this buckets them into DAYS in the viewer's display
// zone and draws the bars. Day bucketing lives here (not in SQL) because the day boundary depends
// on the display zone, which is a client-only preference (see tz.js) — the server stays UTC-only.
(function () {
  var el = document.getElementById("tokens-over-time");
  if (!el) return;
  var series;
  try { series = JSON.parse(el.getAttribute("data-series") || "[]"); } catch (e) { return; }

  // The effective display zone — same rule as tz.js: the stored choice, else the browser's zone.
  function zone() {
    try { var s = localStorage.getItem("lik-tz"); if (s && s !== "auto") return s; } catch (e) {}
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch (e) { return "UTC"; }
  }
  var z = zone();

  // Local calendar day (YYYY-MM-DD) of a UTC instant, in the display zone. en-CA yields ISO order.
  var fmt = new Intl.DateTimeFormat("en-CA", { timeZone: z, year: "numeric", month: "2-digit", day: "2-digit" });
  function localDay(iso) { return fmt.format(new Date(iso)); }

  var byDay = {};
  series.forEach(function (s) {
    var k = localDay(s.created_at);
    if (!byDay[k]) byDay[k] = { tokens: 0, sessions: 0 };
    byDay[k].tokens += s.tokens;
    byDay[k].sessions += 1;
  });
  var days = Object.keys(byDay).sort();
  if (!days.length) { el.innerHTML = '<p class="stats-empty">No deleted sessions yet.</p>'; return; }

  var peak = days.reduce(function (m, k) { return Math.max(m, byDay[k].tokens); }, 0);
  var rows = days.map(function (k) {
    var b = byDay[k];
    var pct = peak ? Math.round((100 * b.tokens) / peak) : 0;
    return '<div class="bar-row"><span>' + k + "</span>"
      + '<span class="bar-track"><span class="bar-fill" style="width:' + pct + '%"></span></span>'
      + '<span class="bar-value">' + b.tokens.toLocaleString() + " · " + b.sessions + " sess</span></div>";
  });
  el.innerHTML = rows.join("");
})();
