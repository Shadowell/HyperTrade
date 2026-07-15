# Desktop Floating Mission Bot

## Boundary

The HyperTrade desktop bot is a small always-on-top macOS client for the existing Mission Runtime.
It is not a browser overlay and does not replace `/harness`. The Harness remains the full operator
workbench; the bot is a focused entry point for short governed research questions and compact
evidence-bound answers.

```text
Tauri window and tray
  -> React conversation projection
  -> typed Tauri IPC channel
  -> Rust HTTP/SSE adapter
  -> HyperTrade /api/health and /api/agent/runs/stream
  -> Mission Runtime
```

The WebView has no arbitrary network permission. The Rust adapter validates the configured HTTP(S)
origin, rejects embedded credentials, bounds prompts, idempotency keys and SSE frames, and forwards
only parsed public stream events. Provider credentials, trading credentials and execution authority
remain server-side. The client introduces no paper, live, order, approval or capital mutation path.

## Window and interaction model

- The collapsed window is a 64 logical-pixel transparent, frameless, always-on-top surface anchored
  near the lower-right screen edge. A tray menu can show, hide or quit the app.
- Expanding produces a 420 by 640 logical-pixel research panel. Logical dimensions are converted at
  the active display scale factor so Retina displays do not halve the intended UI.
- HT conclusions are left-aligned with a teal evidence rail. User questions are right-aligned with
  a restrained brass edge, preserving normal two-party conversation direction.
- The product symbol is an original non-human precision-instrument mark designed to remain legible at
  34–52 pixels. It does not use a person, mascot or third-party chat-product likeness.

## Failure behavior

Connection and Mission failures remain visible as bounded assistant errors. HTTP failures, invalid
stream frames and oversized events fail closed; they cannot be interpreted as research completion.
The browser preview uses deterministic sample events only for design and component tests. Packaged
desktop execution always routes through the Rust adapter to the configured HyperTrade service.
