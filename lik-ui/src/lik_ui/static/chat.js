// Minimal SSE chat client. Sends a message, streams normalized events from the server,
// and renders assistant text, tool activity, and connection-error nudges.
(function () {
  const transcript = document.getElementById("transcript");
  const composer = document.getElementById("composer");
  const input = document.getElementById("message");
  const sessionId = transcript.dataset.sessionId;
  const agentId = transcript.dataset.agentId;
  // False for a read-only viewer of a shared session: suppress write affordances (composer is
  // absent, and paused tool calls render without Approve/Deny buttons the viewer can't use).
  const canWrite = transcript.dataset.canWrite !== "false";

  function bubble(cls, text) {
    const el = document.createElement("div");
    el.className = "card " + cls;
    el.textContent = text;
    transcript.appendChild(el);
    return el;
  }

  // Session activity indicator. Lives OUTSIDE #transcript (so a history reload's transcript
  // reset never removes it) and is pinned in view, so the user always knows when the agent is
  // not idle — queued, working, waiting for approval, or reconnecting after a dropped stream.
  // Hidden whenever the session is idle. One element, one source of truth, set from the turn
  // lifecycle below.
  const statusEl = document.getElementById("agent-status");
  function setStatus(text) { if (statusEl) { statusEl.textContent = text; statusEl.hidden = false; } }
  function clearStatus() { if (statusEl) { statusEl.hidden = true; statusEl.textContent = ""; } }

  // A detail label for the activity indicator describing what the agent is doing right now, so
  // "working" becomes concrete during the long silent stretches that are mostly tool calls. MCP
  // tools name their server (matching the tool bubble's plug icon); built-in tools use the gear.
  // ``count`` is the run length of back-to-back calls to this same tool — the agent fans out
  // batches of identical calls (e.g. 10 page fetches at once), so surfacing "(×10)" tells the
  // user one tool is being hammered rather than one slow call hanging.
  function toolActivityLabel(event, count) {
    const name = event.name || "a tool";
    const times = count > 1 ? " (×" + count + ")" : "";
    return event.server
      ? "🔌 Using " + event.server + " · " + name + times + "…"
      : "⚙ Running " + name + times + "…";
  }

  // Render accumulated markdown to sanitized HTML; fall back to plain text if the CDN
  // libs didn't load (offline / blocked).
  function renderMarkdown(el, raw) {
    if (window.marked && window.DOMPurify) {
      el.innerHTML = window.DOMPurify.sanitize(window.marked.parse(raw));
    } else {
      el.textContent = raw;
    }
  }

  // Tool-visibility toggles. Default unchecked -> tools hidden; the container carries the
  // hide-* classes and the CSS keys off the per-bubble kind, so bubbles added later (live
  // stream or history) inherit the current state without re-checking each one.
  const toggleTools = document.getElementById("toggle-tools");
  const toggleMcp = document.getElementById("toggle-mcp");
  function applyToolVisibility() {
    transcript.classList.toggle("hide-builtin-tools", !toggleTools.checked);
    transcript.classList.toggle("hide-mcp-tools", !toggleMcp.checked);
  }
  toggleTools.addEventListener("change", applyToolVisibility);
  toggleMcp.addEventListener("change", applyToolVisibility);
  applyToolVisibility();

  // Per-server auto-approve. Each checked server's gated ("ask") tool calls are approved
  // automatically for the rest of this session; unchecked servers still prompt. The agent
  // gates every call server-side regardless — this just answers the pause with "allow" via
  // the same /confirm path a manual click uses. The trusted set persists in sessionStorage
  // (keyed by session id) so a refresh keeps the choices.
  const autoServersKey = "lik-auto-servers:" + sessionId;
  const serverBoxes = document.querySelectorAll(".auto-server");
  const storedServers = sessionStorage.getItem(autoServersKey);
  // Default to trusting every declared server; once the user changes anything, their explicit
  // set is stored and used verbatim (so unticking one, or all, sticks across a refresh).
  const autoServers = new Set(
    storedServers !== null
      ? JSON.parse(storedServers)
      : Array.prototype.map.call(serverBoxes, function (cb) { return cb.value; })
  );
  function isAutoServer(server) { return autoServers.has(server); }
  Array.prototype.forEach.call(serverBoxes, function (cb) {
    // A disabled box is a server that always-allows server-side: it's trusted no matter what a
    // stale stored set says, and can't be toggled off.
    if (cb.disabled) autoServers.add(cb.value);
    cb.checked = autoServers.has(cb.value);
    cb.addEventListener("change", function () {
      if (cb.checked) autoServers.add(cb.value); else autoServers.delete(cb.value);
      sessionStorage.setItem(autoServersKey, JSON.stringify(Array.from(autoServers)));
      // Trusting a server now clears anything from it already waiting for approval.
      if (cb.checked) autoApproveNext(pendingCallIds());
    });
  });

  // Remembered decisions ({toolUseId: {result, auto, server}}), persisted so the on-screen
  // "Approved / Auto-approved / Denied" tags survive a page refresh (history replay can't
  // otherwise tell an approved gated call apart from an auto-approved one).
  const decisionsKey = "lik-decisions:" + sessionId;
  const decisions = JSON.parse(sessionStorage.getItem(decisionsKey) || "{}");
  function recordDecision(id, result, auto, server) {
    decisions[id] = { result: result, auto: auto, server: server };
    sessionStorage.setItem(decisionsKey, JSON.stringify(decisions));
  }

  // Maps a tool_use id to its rendered bubble so a later tool_result can nest under its call.
  const toolCalls = {};

  // Tool-use ids that still show a live Approve/Deny prompt (unresolved "ask" calls).
  function pendingCallIds() {
    return Object.keys(toolCalls).filter(function (id) {
      return toolCalls[id].querySelector(".tool-actions");
    });
  }

  // Approve the first still-pending call among `ids` whose server is trusted. One at a time:
  // the resumed turn re-prompts for any remaining blocked calls and that pause routes back
  // here, so a chain clears without stacking concurrent streams. Calls from untrusted servers
  // are left with their manual prompt.
  function autoApproveNext(ids) {
    const id = (ids || []).find(function (x) {
      const c = toolCalls[x];
      return c && c.querySelector(".tool-actions") && isAutoServer(c._server);
    });
    if (!id) return;
    const call = toolCalls[id];
    recordDecision(id, "allow", true, call._server);
    stampDecision(call, "allow", true, call._server);
    confirmTool(id, "allow", call._sessionThreadId);
  }

  // True if any of `ids` is a call from an untrusted server still awaiting a manual decision.
  function anyManualPending(ids) {
    return (ids || []).some(function (x) {
      const c = toolCalls[x];
      return c && c.querySelector(".tool-actions") && !isAutoServer(c._server);
    });
  }

  // Replace a gated call's prompt with a decision tag (idempotent). Removes the awaiting flag
  // so the bubble obeys the tool-visibility toggles again once it's been decided.
  function stampDecision(call, result, auto, server) {
    call.classList.remove("awaiting");
    const actions = call.querySelector(".tool-actions");
    if (actions) actions.remove();
    if (call.querySelector(".tool-decision")) return;
    const tag = document.createElement("div");
    tag.className = "tool-decision " + (result === "allow" ? "ok" : "no");
    tag.textContent = result === "allow"
      ? (auto ? "✓ Auto-approved · " + server : "✓ Approved")
      : "✕ Denied";
    call.appendChild(tag);
  }

  // Enable/disable every visible Approve/Deny button — used to keep a manual click from
  // opening a second confirm stream while one is already resuming a turn.
  function setPromptsEnabled(on) {
    Array.prototype.forEach.call(transcript.querySelectorAll(".tool-actions button"),
      function (b) { b.disabled = !on; });
  }

  function collapsible(summaryText, body) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = summaryText;
    const pre = document.createElement("pre");
    pre.textContent = body;
    details.appendChild(summary);
    details.appendChild(pre);
    return details;
  }

  function toolBubble(event) {
    // Tag the bubble so the "Show tool use" / "Show MCP tool use" checkboxes can hide it by
    // kind. MCP tools carry a server; built-in agent tools don't.
    const kind = event.server ? "mcp" : "builtin";
    // Distinct icon per kind: a plug for MCP (external server) tools, a gear for built-in ones.
    const icon = event.server ? "🔌" : "⚙";
    const b = bubble("tool " + kind, icon + " using " + (event.server ? event.server + " · " : "") + event.name);
    // Show the tool-call arguments in a collapsible block so the transcript stays scannable
    // but the detail is one click away. Omitted when there are no arguments.
    if (event.input && Object.keys(event.input).length) {
      b.appendChild(collapsible("arguments", JSON.stringify(event.input, null, 2)));
    }
    if (event.id) toolCalls[event.id] = b;
    // "ask" means the call is paused for the user's approval. A missing id means we couldn't
    // route an answer, so no prompt is shown.
    if (event.permission === "ask" && event.id) {
      // "gated" keeps the bubble visible through the tool-visibility toggles for its whole
      // life — both while awaiting a decision (you can't approve what you can't see) and after,
      // so the approved/denied trail stays on screen. "awaiting" adds the pending highlight.
      b.classList.add("gated");
      b._server = event.server;  // matched against the trusted-server set (null for built-ins)
      b._sessionThreadId = event.session_thread_id;  // echoed back on approval; see confirmTool
      const prior = decisions[event.id];
      if (prior) {
        stampDecision(b, prior.result, prior.auto, prior.server);  // refresh replay
      } else {
        b.classList.add("awaiting");
        if (canWrite) b.appendChild(confirmActions(b, event));
      }
    }
    return b;
  }

  // The Approve/Deny prompt appended to a paused tool call. Clicking records and stamps the
  // decision, then streams the resumed turn back in; the tool's result nests under this same
  // bubble. Buttons disable on click so a decision can't be sent twice.
  function confirmActions(call, event) {
    const row = document.createElement("div");
    row.className = "tool-actions";
    const mk = function (label, cls, result) {
      const btn = document.createElement("button");
      btn.className = "btn " + cls;
      btn.textContent = label;
      btn.addEventListener("click", function () {
        recordDecision(event.id, result, false, event.server);
        stampDecision(call, result, false, event.server);
        confirmTool(event.id, result, event.session_thread_id);
      });
      return btn;
    };
    row.appendChild(mk("Approve", "secondary", "allow"));
    row.appendChild(mk("Deny", "danger", "deny"));
    return row;
  }

  // Pretty-print as JSON when the content parses as such (MCP results are usually a JSON
  // string on one line); otherwise show the raw text unchanged.
  function prettyJson(text) {
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch (e) {
      return text;
    }
  }

  // A tool's returned output. Nest it under the matching call bubble when we have it;
  // otherwise (result seen before its call, or id missing) render it standalone.
  function toolResultBubble(event) {
    const label = (event.is_error ? "error" : "result");
    const body = event.content ? prettyJson(event.content) : "(empty)";
    const call = event.tool_use_id && toolCalls[event.tool_use_id];
    if (call) {
      // A result means the call is resolved. If it was a gated call still showing a prompt
      // (e.g. approved in another browser session, so no local decision was recorded), tag it
      // approved; otherwise just drop the awaiting flag so it obeys the toggles again.
      if (call.classList.contains("awaiting") && !call.querySelector(".tool-decision")) {
        stampDecision(call, "allow", false, call._server);
      } else {
        const actions = call.querySelector(".tool-actions");
        if (actions) actions.remove();
        call.classList.remove("awaiting");
      }
      call.appendChild(collapsible(label, body));
    } else {
      bubble("tool" + (event.is_error ? " error" : ""), "⚙ " + label)
        .appendChild(collapsible(label, body));
    }
  }

  // Marks where the session summarized older turns, so a sparse replayed history isn't
  // mistaken for the whole session.
  function compactedDivider() {
    bubble("compacted", "— earlier context compacted —");
  }

  // "took 4m 6s" / "took 12s" / "took 0.8s" — a compact human duration.
  function humanizeDuration(seconds) {
    if (seconds < 1) return (Math.round(seconds * 10) / 10) + "s";
    const whole = Math.round(seconds);
    if (whole < 60) return whole + "s";
    const m = Math.floor(whole / 60), s = whole % 60;
    return s ? m + "m " + s + "s" : m + "m";
  }

  // A small meta line under an agent reply showing how long that turn took (the agent's working
  // time), computed server-side from the platform's processed_at timestamps.
  function durationLine(seconds) {
    bubble("duration", "⏱ took " + humanizeDuration(seconds));
  }

  // Append the just-finished live turn's duration under its reply, using the same server-computed
  // value that replay renders (it's the last event history returns for the completed turn). We use
  // the server value rather than a client wall-clock timer because the timer can't survive the
  // drop→resume and pause→confirm paths (the turn spans several streams), and it must match what a
  // later reload shows. Best-effort: on a transient miss the line simply appears on the next load.
  function appendTurnDuration() {
    fetch("/chat/" + sessionId + "/history")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        const events = (data && Array.isArray(data.events)) ? data.events : [];
        const last = events[events.length - 1];
        if (last && last.type === "turn_duration") durationLine(last.seconds);
      })
      .catch(function () { /* best-effort; the duration shows on the next history render */ });
  }

  // Running token total across every model request in the session (history + live),
  // shown once as a footer below the transcript and updated in place.
  const usage = { input: 0, output: 0, cache_read: 0, cache_creation: 0 };
  let usageEl = null;
  function addUsage(event) {
    usage.input += event.input || 0;
    usage.output += event.output || 0;
    usage.cache_read += event.cache_read || 0;
    usage.cache_creation += event.cache_creation || 0;
    if (!usageEl) {
      usageEl = document.createElement("div");
      usageEl.className = "usage";
      transcript.parentNode.appendChild(usageEl);
    }
    usageEl.textContent = "Tokens — in " + usage.input + " · out " + usage.output +
      " · cache read " + usage.cache_read + " · cache write " + usage.cache_creation;
  }

  function errorBubble(event) {
    // Always surface the platform's own error text — never a synthesized message, which
    // can mislead (e.g. telling the user to "reconnect" when the model was just
    // overloaded). Fall back to the raw error type only if no message was provided.
    // A credential error additionally names the MCP server to reconnect, so append the
    // Fix-connections link — but the wording stays the original error.
    const b = bubble("error", event.message || event.error_type || "Unknown error");
    if (event.mcp_server_name) {
      const link = document.createElement("a");
      link.href = "/connections?agent_id=" + encodeURIComponent(agentId);
      link.textContent = " Fix connections";
      b.appendChild(link);
    }
  }

  // Wipe the rendered transcript back to empty so it can be re-rendered from an
  // authoritative source. Clears the per-turn/tool/usage bookkeeping too, but leaves the
  // container's tool-visibility classes alone (they aren't children of #transcript).
  function resetTranscript() {
    transcript.replaceChildren();
    for (const id in toolCalls) delete toolCalls[id];
    usage.input = usage.output = usage.cache_read = usage.cache_creation = 0;
    if (usageEl) { usageEl.remove(); usageEl = null; }
  }

  // Replay prior events into the transcript before the composer is used. Each history
  // event is its own bubble (consecutive assistant messages aren't merged — the merge
  // in the live stream is only to accumulate a single reply's text deltas).
  //
  // Doubles as the reconcile path: history is the source of truth for what the session
  // actually recorded, so re-running this after a turn recovers a reply the live stream
  // missed (e.g. it subscribed after a fast turn already ended) without a manual refresh.
  function loadHistory() {
    return fetch("/chat/" + sessionId + "/history")
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (data) {
        const events = (data && Array.isArray(data.events)) ? data.events : [];
        resetTranscript();
        events.forEach(function (event) {
          if (event.type === "user") {
            bubble("user", event.text);
          } else if (event.type === "text") {
            const el = bubble("assistant", "");
            renderMarkdown(el, event.text);
          } else if (event.type === "tool_use") {
            toolBubble(event);
          } else if (event.type === "tool_result") {
            toolResultBubble(event);
          } else if (event.type === "compacted") {
            compactedDivider();
          } else if (event.type === "usage") {
            addUsage(event);
          } else if (event.type === "turn_duration") {
            durationLine(event.seconds);
          } else if (event.type === "error") {
            errorBubble(event);
          }
        });
        return (data && data.status) || "idle";
      })
      .catch(function () { return "idle"; /* history is best-effort; a blank transcript is fine */ });
  }

  // Reload persisted history, then clear any trusted-server call left waiting — e.g. a pause
  // that predates a page refresh, which history replays with its prompt intact.
  function reconcile() {
    return loadHistory().then(function (status) {
      autoApproveNext(pendingCallIds());
      return status;
    });
  }

  // Consume one turn's SSE stream from `url` into the transcript. Shared by sending a message
  // and by answering a paused tool call (both stream the same normalized vocabulary), so the
  // rendering and reconcile logic lives in one place. `initial` is the first activity label.
  function streamTurn(url, initial) {
    // Show the activity indicator for the whole turn: from start (`initial` label) through tool
    // calls and intermediate output — so the user always knows the agent is still working — and
    // clear it only when the turn finishes (`done`), pauses for approval (`awaiting_confirmation`
    // with nothing left to auto-approve), or the connection drops without an in-flight turn to
    // re-attach to.
    setStatus(initial);

    let assistant = null;
    // Track a run of back-to-back calls to the same tool so the indicator can show "(×N)". Reset
    // whenever anything other than another matching tool_use streams (text, a result, etc.), so a
    // later batch of the same tool starts its count fresh rather than continuing an old run.
    let toolRunKey = null;
    let toolRunCount = 0;
    // Did the live stream render anything for this turn? If not, the reply was persisted but
    // the stream missed it (dropped connection) — reconcile from history so it still appears
    // without a manual refresh.
    let produced = false;
    // Disable any visible Approve/Deny prompts while this turn streams, so a manual click
    // can't open a second confirm stream on the same session (which would duplicate output).
    // Re-enabled when the turn ends or pauses.
    setPromptsEnabled(false);
    const source = new EventSource(url);

    source.onmessage = function (ev) {
      const event = JSON.parse(ev.data);
      if (event.type === "status") {
        // Advance the indicator queued -> running; it stays put until the turn ends.
        if (event.state === "running") setStatus("⚙ Working — the agent is running…");
        return;
      }
      if (event.type === "text") {
        produced = true;
        toolRunKey = null; toolRunCount = 0;  // a reply broke the tool run
        setStatus("✍️ Responding…");  // reflects text streaming, even after an intervening tool call
        if (!assistant) { assistant = bubble("assistant", ""); assistant._raw = ""; }
        assistant._raw += event.text;
        renderMarkdown(assistant, assistant._raw);
      } else if (event.type === "tool_use") {
        produced = true;
        toolBubble(event);
        // Reflect the tool being called in the indicator, counting a run of back-to-back calls to
        // the same tool. A gated ("ask") call is about to pause the turn, so leave its "waiting
        // for approval" wording to the awaiting_confirmation branch rather than flashing "Using…".
        if (event.permission !== "ask") {
          const key = (event.server || "") + "·" + (event.name || "");
          toolRunCount = key === toolRunKey ? toolRunCount + 1 : 1;
          toolRunKey = key;
          setStatus(toolActivityLabel(event, toolRunCount));
        }
      } else if (event.type === "tool_result") {
        produced = true;
        toolRunKey = null; toolRunCount = 0;  // results came back; the next batch counts fresh
        toolResultBubble(event);
      } else if (event.type === "compacted") {
        produced = true;
        compactedDivider();
      } else if (event.type === "usage") {
        produced = true;
        addUsage(event);
      } else if (event.type === "error") {
        // A streamed error isn't necessarily terminal (e.g. an unconnected MCP source errors
        // first and the agent still answers), so surface it but keep the indicator running.
        produced = true;
        errorBubble(event);
      } else if (event.type === "awaiting_confirmation") {
        // The turn paused on one or more tool calls needing approval. Close the stream (a
        // decision reopens it via confirmTool) and re-enable prompts. Auto-approve any blocked
        // call from a trusted server; if a call from an untrusted server is left, leave its
        // Approve/Deny prompt and a standing hint. If the pausing tool_use wasn't seen live
        // (e.g. we subscribed late), pull it from history first so its prompt/decision shows.
        source.close();
        setPromptsEnabled(true);
        if (!produced) { reconcile().then(resumeIfInFlight); return; }
        autoApproveNext(event.event_ids);
        // An auto-approve reopens the stream (its own indicator takes over); otherwise show a
        // standing "waiting for you" state for a call left needing a manual decision, or clear
        // the indicator when nothing is pending.
        if (anyManualPending(event.event_ids)) {
          setStatus("⏸ Waiting for your approval on the tool call above.");
        } else if (!pendingCallIds().length) {
          clearStatus();
        }
        return;
      } else if (event.type === "done") {
        source.close();
        setPromptsEnabled(true);
        clearStatus();
        // A completed turn has nothing paused, so no auto-approve here — just recover a reply
        // the stream may have missed. (awaiting_confirmation, not done, signals a pause.)
        // When the stream missed the reply we reload history, which renders the server-computed
        // duration itself; otherwise the reply is already on screen, so just append this turn's
        // duration under it — the authoritative server value, matching how replay renders it.
        if (!produced) { loadHistory(); return; }
        appendTurnDuration();
        return;
      }
    };

    source.onerror = function () {
      source.close();
      setPromptsEnabled(true);
      // The connection dropped mid-turn; the agent keeps running server-side. Keep the indicator
      // up as "reconnecting" so the page never looks idle while work continues, then pull
      // whatever was recorded so a completed reply isn't stranded behind a refresh — and, if the
      // turn is still in flight, re-attach to it so its remaining output streams without a manual
      // refresh. Re-attaching loops: if the resume stream also drops, this same handler fires
      // again, so a turn survives no matter how long it runs or how many times an intermediary
      // culls the (idle) connection. resumeIfInFlight clears the indicator if the turn had ended.
      setStatus("⚙ Reconnecting to the agent…");
      reconcile().then(resumeIfInFlight);
    };
  }

  // Attach to a turn still in flight (per the status from history) via the send-free /resume
  // path, so its queued/running state shows and it streams to completion. A no-op when the
  // session is idle (the turn already finished — history alone has the reply). Shared by the
  // initial page load and the mid-turn drop-recovery above; never uses /stream, which would
  // re-send the user message and duplicate the turn.
  function resumeIfInFlight(status) {
    if (status && status.toLowerCase() !== "idle") {
      const label = status.toLowerCase().indexOf("queue") !== -1
        ? "⏳ Queued — waiting for the agent…"
        : "⚙ Working — the agent is running…";
      streamTurn("/chat/" + sessionId + "/resume", label);
    } else {
      clearStatus();  // turn already finished — the reply is in the transcript; nothing pending
    }
  }

  // Send an allow/deny decision for a paused tool call and stream the resumed turn.
  function confirmTool(toolUseId, result, sessionThreadId) {
    let url = "/chat/" + sessionId + "/confirm?tool_use_id=" + encodeURIComponent(toolUseId) +
      "&result=" + encodeURIComponent(result);
    if (sessionThreadId) url += "&session_thread_id=" + encodeURIComponent(sessionThreadId);
    streamTurn(url, result === "allow" ? "⚙ Approved — resuming…" : "Denied — resuming…");
  }

  // The composer is absent for a read-only viewer of a shared session (owner-only in the
  // template). History replay and resume below still run so the viewer sees the transcript.
  if (composer) {
    composer.addEventListener("submit", function (e) {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      bubble("user", "You: " + message);
      input.value = "";
      streamTurn("/chat/" + sessionId + "/stream?message=" + encodeURIComponent(message),
                 "⏳ Queued — waiting for the agent…");
    });
  }

  // A turn already in flight when the page loads (e.g. the user reopened the tab while the agent
  // was still working) has no live stream attached yet, so history alone renders it silently.
  // Show a loading indicator immediately, then re-attach so an in-flight turn streams to
  // completion without a manual refresh; resumeIfInFlight clears the indicator if it was idle.
  setStatus("⏳ Loading session…");
  reconcile().then(resumeIfInFlight);
})();
