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
        if (!assistant) assistant = bubble("assistant", "");
        assistant.textContent += event.text;
      } else if (event.type === "tool_use") {
        bubble("tool", "⚙ using " + (event.server ? event.server + " · " : "") + event.name);
      } else if (event.type === "error") {
        const b = bubble("error", "Connection issue" + (event.mcp_server_name ? " with " + event.mcp_server_name : "") + ". Reconnect that source and retry.");
        const link = document.createElement("a");
        link.href = "/connections?agent_id=" + encodeURIComponent(agentId);
        link.textContent = " Fix connections";
        b.appendChild(link);
      } else if (event.type === "done") {
        source.close();
      }
    };

    source.onerror = function () {
      source.close();
    };
  });
})();
