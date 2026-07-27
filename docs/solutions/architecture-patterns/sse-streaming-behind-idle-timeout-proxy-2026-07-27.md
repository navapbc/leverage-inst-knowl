---
title: SSE streaming behind a fixed idle-timeout proxy needs both a heartbeat and a resume-on-drop path
date: 2026-07-27
category: architecture-patterns
module: lik-ui chat streaming
problem_type: architecture_pattern
component: assistant
severity: high
root_cause: async_timing
resolution_type: code_fix
applies_when:
  - Streaming SSE (or any long-lived HTTP response) through a proxy or load balancer with a fixed idle timeout
  - The producer can be silent longer than that idle timeout (an agent thinking, a slow tool call, a long DB query)
  - The client tears down the stream on error instead of relying on native EventSource auto-reconnect
tags: [sse, streaming, idle-timeout, load-balancer, heartbeat, managed-agents, reconnect]
---

# SSE streaming behind a fixed idle-timeout proxy needs both a heartbeat and a resume-on-drop path

## Context

lik-ui streams an agent turn to the browser over Server-Sent Events. A user reported that the
Catalog Registration Agent's reply sometimes only appeared **after a manual page refresh**. The
turn had completed and the reply was persisted server-side — it just never rendered live.

The trigger is structural, not agent-specific: the app runs behind a Lightsail Container Service
load balancer whose idle timeout is fixed (~60s, not tunable). This agent legitimately goes
**silent for 60–90s between tool batches** while the model thinks or a slow tool runs. Only a
subset of platform events are normalized into SSE output, so a long think is pure silence on the
wire. Confirmed against live session `sesn_018y5APYNiTZe55RjosKUCVk` via the `anthropic` SDK: a
~90s window (`14:41:27.6` → `14:42:57.4`) with zero emitted events, inside a turn that ended
cleanly with a persisted 2022-char reply.

When no bytes cross the connection for longer than the idle timeout, the load balancer culls it.
The browser's `EventSource.onerror` then reloaded history — but the turn was still running, so
history had no reply yet — **and did not re-attach**. The finished reply streamed to nobody.

## Guidance

When streaming through a fixed-idle-timeout proxy where the producer can out-wait the timeout,
you need **two independent layers**. Neither alone is sufficient:

1. **Producer-side heartbeat (prevents the drop).** Emit a no-op keepalive on an interval well
   under the idle timeout so the connection is never idle long enough to be culled. For SSE, a
   comment line (`: keepalive\n\n`) is ideal — `EventSource` ignores it, so it never reaches
   `onmessage`. If the event source is a **blocking** generator (it was here — a synchronous SDK
   iterator), you cannot interleave a timed heartbeat inline. Drain the generator on a worker
   thread into a queue, and have the response body emit either the next event or, on a
   `queue.get(timeout=...)` miss, a heartbeat.

2. **Resume-on-drop (recovers if the drop still happens).** A heartbeat can still be defeated
   (a proxy that caps *total* duration regardless of activity, a genuine network blip), so the
   client must recover. On stream error, reconcile from server-side history and, **if the turn
   is still in flight, re-attach** to it — via a send-free "resume/attach" endpoint, never the
   original send endpoint (re-sending would duplicate the turn). Make it loop: if the resume
   stream also drops, the same handler re-attaches. This is what makes it survive *arbitrarily*
   long turns.

A third, UX layer earned its place here: **an activity indicator that lives outside the
scrollable content area** so a history reload (which rebuilds that area) can't wipe it, keeping
a visible "working / reconnecting" signal across the drop-and-reattach cycle.

## Why This Matters

- **A heartbeat alone is fragile.** It assumes the only failure is idle-timeout culling. Total-
  duration caps and network blips still strand the reply.
- **Resume-on-drop alone is janky.** It works, but for an agent that goes silent every 60–90s the
  connection drops and the transcript rebuilds several times per turn — correct but flickering.
- **The client tearing down on error is the trap.** Native `EventSource` auto-reconnects, but you
  usually `close()` it on error precisely because reconnecting to the *send* endpoint would
  re-dispatch the message. That's correct — but it means recovery is now *your* job, and "reload
  history" is not recovery if the turn hasn't finished. Recovery must re-attach to the live turn.
- **Verify against reality, not intuition.** The "silent window exceeds the idle timeout" link was
  the uncertain one; measuring the actual event timeline of the failing session (reply persisted +
  a ~90s zero-byte gap) turned a plausible guess into a confirmed cause before any code changed.

## When to Apply

- Any SSE / long-poll / chunked response behind a load balancer or reverse proxy you don't fully
  control the idle timeout of (Lightsail, ALB, nginx, Cloudflare).
- The upstream producer is an agent turn, a long job, or anything that can pause longer than that
  timeout without emitting output.
- Managed Agents session streaming specifically: a turn's `send`, `resume`, and `confirm` streams
  all share this exposure — apply the heartbeat at the shared SSE wrapper so every stream benefits.

## Examples

**Heartbeat over a blocking generator** (`lik-ui/src/lik_ui/chat.py`, `_sse`):

```python
def event_stream():
    q = queue.Queue()
    done = object()

    def produce():
        try:
            for event in events:            # the blocking SDK-backed generator
                q.put(("event", event))
        except Exception as exc:            # forward as a terminal error, don't crash the thread
            q.put(("error", str(exc)))
        finally:
            q.put((done, None))

    threading.Thread(target=produce, daemon=True).start()  # daemon: a disconnected client never blocks shutdown
    while True:
        try:
            kind, payload = q.get(timeout=_SSE_HEARTBEAT_SECONDS)   # 15s, well under the ~60s idle timeout
        except queue.Empty:
            yield ": keepalive\n\n"          # SSE comment — keeps the connection alive, ignored by EventSource
            continue
        if kind is done:
            break
        yield f"data: {json.dumps(payload)}\n\n"
```

**Resume-on-drop, looping** (`lik-ui/src/lik_ui/static/chat.js`):

```javascript
source.onerror = function () {
  source.close();
  setStatus("⚙ Reconnecting to the agent…");     // indicator lives outside #transcript, survives the reload
  reconcile().then(resumeIfInFlight);             // reload history, then re-attach if still running
};

function resumeIfInFlight(status) {
  if (status && status.toLowerCase() !== "idle") {
    streamTurn("/chat/" + sessionId + "/resume", label);  // send-free attach — never /stream (would re-send)
  } else {
    clearStatus();                                // turn finished; reply is already in the transcript
  }
}
```

The heartbeat is per-turn: it stops when the turn completes (stream closes) or the tab closes, so
an idle browser on a finished chat holds no connection and incurs no load.

## Related

- PR #33 (branch `fix/stranded-agent-response-on-long-turns`) — introduced all three layers.
- Prior regression fixed in the same area: the stream must subscribe **before** sending, or a fast
  turn finishes before the subscription attaches and its reply is likewise stranded (see
  `test_send_and_stream_subscribes_before_sending`). Same failure symptom (reply only on refresh),
  different cause (subscribe-after-send vs. idle-timeout cull) — both are timing races around the
  live stream's lifetime.
