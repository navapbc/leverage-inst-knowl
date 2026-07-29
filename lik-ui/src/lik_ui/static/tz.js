// Time-zone display. Mirrors theme.js: a single client-side preference in localStorage is the
// one source of truth for how timestamps render. The server emits every instant as UTC in a
// `data-utc` attribute (with a plain-UTC fallback in the element body for no-JS); this script
// rewrites each element's text into the user's effective zone. Display only — no form is touched.
(function () {
  var STORAGE_KEY = "lik-tz";

  // Curated zones offered on the Settings page (populated by the selector wiring below). "auto"
  // means "detect from the browser". Kept here so the list lives in exactly one place.
  var ZONES = [
    { value: "auto", label: "Auto (detected)" },
    { value: "America/New_York", label: "US Eastern" },
    { value: "America/Chicago", label: "US Central" },
    { value: "America/Denver", label: "US Mountain" },
    { value: "America/Los_Angeles", label: "US Pacific" },
    { value: "UTC", label: "UTC" },
  ];

  function getStored() {
    try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
  }

  // The concrete IANA zone to format in: the stored choice, or the browser's own zone when the
  // user hasn't chosen (or chose "auto"). Falls back to UTC if the Intl lookup is unavailable.
  function getEffectiveZone() {
    var stored = getStored();
    if (stored && stored !== "auto") return stored;
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch (e) { return "UTC"; }
  }

  function parts(date, zone) {
    var map = {};
    new Intl.DateTimeFormat("en-US", {
      timeZone: zone, hourCycle: "h23",
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", timeZoneName: "short",
    }).formatToParts(date).forEach(function (p) { map[p.type] = p.value; });
    return map;
  }

  function ymd(date, zone) {
    var p = parts(date, zone);
    return p.year + "-" + p.month + "-" + p.day;
  }

  function utcHm(date) {
    var p = parts(date, "UTC");
    return p.hour + ":" + p.minute;
  }

  // "2026-07-28 09:00 EDT (13:00 UTC)" — the parenthetical UTC is dropped when the effective
  // zone already is UTC (it would just repeat the main value).
  function formatDateTime(date, zone) {
    var p = parts(date, zone);
    var main = p.year + "-" + p.month + "-" + p.day + " " + p.hour + ":" + p.minute + " " + p.timeZoneName;
    return p.timeZoneName === "UTC" ? main : main + " (" + utcHm(date) + " UTC)";
  }

  // Rewrite every [data-utc] element into the effective zone, per its data-format hint.
  function applyAll() {
    var zone = getEffectiveZone();
    var nodes = document.querySelectorAll("[data-utc]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var date = new Date(el.getAttribute("data-utc")); // ISO carries a UTC offset — zone-safe
      if (isNaN(date.getTime())) continue;
      el.textContent = el.getAttribute("data-format") === "datetime"
        ? formatDateTime(date, zone)
        : ymd(date, zone);
    }
  }

  // Settings-page selector (absent on other pages): fill options, mark the stored choice, and
  // persist + re-render on change. Persisting an empty/"auto" choice clears to browser-detected.
  function wireSelector() {
    var sel = document.getElementById("tz-select");
    if (!sel) return;
    var stored = getStored() || "auto";
    var zones = ZONES.slice();
    // If a previously-stored zone isn't in the curated list (e.g. set by an older build), show it
    // as its own option so the dropdown reflects the zone actually being applied, not a stale "Auto".
    if (!zones.some(function (z) { return z.value === stored; })) {
      zones.push({ value: stored, label: stored });
    }
    zones.forEach(function (z) {
      var opt = document.createElement("option");
      opt.value = z.value;
      opt.textContent = z.label;
      if (z.value === stored) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", function () {
      try { localStorage.setItem(STORAGE_KEY, sel.value); } catch (e) { /* session-only */ }
      applyAll();
    });
  }

  wireSelector();
  applyAll();
})();
