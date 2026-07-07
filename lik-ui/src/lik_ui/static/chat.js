// Minimal SSE chat client. Sends a message, streams normalized events from the server,
// and renders assistant text, tool activity, and connection-error nudges.
(function () {
  const transcript = document.getElementById("transcript");
  const composer = document.getElementById("composer");
  const input = document.getElementById("message");
  const conversationId = transcript.dataset.conversationId;
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

  function toolBubble(event) {
    bubble("tool", "⚙ using " + (event.server ? event.server + " · " : "") + event.name);
  }

  function errorBubble(event) {
    const b = bubble("error", "Connection issue" + (event.mcp_server_name ? " with " + event.mcp_server_name : "") + ". Reconnect that source and retry.");
    const link = document.createElement("a");
    link.href = "/connections?agent_id=" + encodeURIComponent(agentId);
    link.textContent = " Fix connections";
    b.appendChild(link);
  }

  // Replay prior events into the transcript before the composer is used. Each history
  // event is its own bubble (consecutive assistant messages aren't merged — the merge
  // in the live stream is only to accumulate a single reply's text deltas).
  function loadHistory() {
    return fetch("/chat/" + conversationId + "/history")
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (events) {
        if (!Array.isArray(events)) return;
        events.forEach(function (event) {
          if (event.type === "user") {
            bubble("user", "You: " + event.text);
          } else if (event.type === "text") {
            const el = bubble("assistant", "");
            renderMarkdown(el, event.text);
          } else if (event.type === "tool_use") {
            toolBubble(event);
          } else if (event.type === "error") {
            errorBubble(event);
          }
        });
      })
      .catch(function () { /* history is best-effort; a blank transcript is fine */ });
  }

  composer.addEventListener("submit", function (e) {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    bubble("user", "You: " + message);
    input.value = "";

    let assistant = null;
    const url = "/chat/" + conversationId + "/stream?message=" + encodeURIComponent(message);
    const source = new EventSource(url);

    source.onmessage = function (ev) {
      const event = JSON.parse(ev.data);
      if (event.type === "text") {
        if (!assistant) { assistant = bubble("assistant", ""); assistant._raw = ""; }
        assistant._raw += event.text;
        renderMarkdown(assistant, assistant._raw);
      } else if (event.type === "tool_use") {
        toolBubble(event);
      } else if (event.type === "error") {
        errorBubble(event);
      } else if (event.type === "done") {
        source.close();
      }
    };

    source.onerror = function () {
      source.close();
    };
  });

  loadHistory();
})();
