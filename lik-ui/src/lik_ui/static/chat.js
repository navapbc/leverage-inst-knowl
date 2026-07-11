// Minimal SSE chat client. Sends a message, streams normalized events from the server,
// and renders assistant text, tool activity, and connection-error nudges.
(function () {
  const transcript = document.getElementById("transcript");
  const composer = document.getElementById("composer");
  const input = document.getElementById("message");
  const sessionId = transcript.dataset.sessionId;
  const agentId = transcript.dataset.agentId;

  function bubble(cls, text) {
    const el = document.createElement("div");
    el.className = "card " + cls;
    el.textContent = text;
    transcript.appendChild(el);
    return el;
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

  // Maps a tool_use id to its rendered bubble so a later tool_result can nest under its call.
  const toolCalls = {};

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
    // "ask" means the call is paused for the user's approval. Offer Approve/Deny inline and
    // force the bubble visible ("awaiting") even if its kind is toggled off — you can't
    // approve what you can't see. The row is cleared once the call resolves (see
    // toolResultBubble). A missing id means we couldn't route an answer, so no prompt.
    if (event.permission === "ask" && event.id) {
      b.classList.add("awaiting");
      b.appendChild(confirmActions(event.id, event.session_thread_id));
    }
    return b;
  }

  // The Approve/Deny prompt appended to a paused tool call. Clicking sends the decision and
  // streams the resumed turn back into the transcript; the tool's result then nests under this
  // same bubble. Buttons disable on click so a decision can't be sent twice.
  function confirmActions(toolUseId, sessionThreadId) {
    const row = document.createElement("div");
    row.className = "tool-actions";
    const mk = function (label, cls, result) {
      const btn = document.createElement("button");
      btn.className = "btn " + cls;
      btn.textContent = label;
      btn.addEventListener("click", function () {
        row.querySelectorAll("button").forEach(function (x) { x.disabled = true; });
        confirmTool(toolUseId, result, sessionThreadId);
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
      // A result means the call is resolved: drop any lingering Approve/Deny prompt and the
      // forced-visible flag so it obeys the tool-visibility toggles again.
      const actions = call.querySelector(".tool-actions");
      if (actions) actions.remove();
      call.classList.remove("awaiting");
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
    const b = bubble("error", "Connection issue" + (event.mcp_server_name ? " with " + event.mcp_server_name : "") + ". Reconnect that source and retry.");
    const link = document.createElement("a");
    link.href = "/connections?agent_id=" + encodeURIComponent(agentId);
    link.textContent = " Fix connections";
    b.appendChild(link);
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
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (events) {
        if (!Array.isArray(events)) return;
        resetTranscript();
        events.forEach(function (event) {
          if (event.type === "user") {
            bubble("user", "You: " + event.text);
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
          } else if (event.type === "error") {
            errorBubble(event);
          }
        });
      })
      .catch(function () { /* history is best-effort; a blank transcript is fine */ });
  }

  // Consume one turn's SSE stream from `url` into the transcript. Shared by sending a message
  // and by answering a paused tool call (both stream the same normalized vocabulary), so the
  // rendering and reconcile logic lives in one place. `initial` is the first activity label.
  function streamTurn(url, initial) {
    // One persistent activity indicator for the whole turn. It stays visible from start
    // through tool calls and intermediate output — so the user always knows the agent is
    // still working — and is removed only when the turn finishes (`done`), pauses for approval
    // (`awaiting_confirmation`), or the connection drops. Kept pinned to the bottom as bubbles
    // stream in.
    let activity = bubble("pending", initial);
    function setActivity(text) { if (activity) activity.textContent = text; }
    function endActivity() { if (activity) { activity.remove(); activity = null; } }
    function keepActivityLast() { if (activity) transcript.appendChild(activity); }

    let assistant = null;
    // Did the live stream render anything for this turn? If not, the reply was persisted but
    // the stream missed it (dropped connection) — reconcile from history so it still appears
    // without a manual refresh.
    let produced = false;
    const source = new EventSource(url);

    source.onmessage = function (ev) {
      const event = JSON.parse(ev.data);
      if (event.type === "status") {
        // Advance the indicator queued -> running; it stays put until the turn ends.
        if (event.state === "running") setActivity("⚙ Working — the agent is running…");
        return;
      }
      if (event.type === "text") {
        produced = true;
        if (!assistant) { assistant = bubble("assistant", ""); assistant._raw = ""; }
        assistant._raw += event.text;
        renderMarkdown(assistant, assistant._raw);
      } else if (event.type === "tool_use") {
        produced = true;
        toolBubble(event);
      } else if (event.type === "tool_result") {
        produced = true;
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
        // The turn paused on one or more tool calls needing approval. The Approve/Deny prompts
        // are already rendered on those tool bubbles (via toolBubble); leave a standing hint
        // and close the stream — a decision reopens it via confirmTool. If the pausing tool_use
        // wasn't seen live (e.g. we subscribed late), pull it from history so its prompt shows.
        source.close();
        if (!produced) { endActivity(); loadHistory(); return; }
        setActivity("⏸ Waiting for your approval on the tool call above.");
        keepActivityLast();
        return;
      } else if (event.type === "done") {
        endActivity();
        source.close();
        if (!produced) loadHistory();  // stream ended without output -> pull the persisted reply
        return;
      }
      keepActivityLast();  // a new bubble was appended above; move the indicator back to the end
    };

    source.onerror = function () {
      endActivity();
      source.close();
      // The connection dropped mid-turn; the agent keeps running server-side. Pull whatever
      // was recorded so a completed reply isn't stranded behind a refresh.
      loadHistory();
    };
  }

  // Send an allow/deny decision for a paused tool call and stream the resumed turn.
  function confirmTool(toolUseId, result, sessionThreadId) {
    let url = "/chat/" + sessionId + "/confirm?tool_use_id=" + encodeURIComponent(toolUseId) +
      "&result=" + encodeURIComponent(result);
    if (sessionThreadId) url += "&session_thread_id=" + encodeURIComponent(sessionThreadId);
    streamTurn(url, result === "allow" ? "⚙ Approved — resuming…" : "Denied — resuming…");
  }

  composer.addEventListener("submit", function (e) {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    bubble("user", "You: " + message);
    input.value = "";
    streamTurn("/chat/" + sessionId + "/stream?message=" + encodeURIComponent(message),
               "⏳ Queued — waiting for the agent…");
  });

  loadHistory();
})();
