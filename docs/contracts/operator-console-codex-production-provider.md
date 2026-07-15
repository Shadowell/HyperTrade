# User-Directed Change - Operator Console and Codex Production Provider

## Goal

Replace the CLI's tool-shortcut-oriented welcome screen with a concise operator
console, and make the existing Codex provider the server's default chat/planner
provider without storing its OAuth credential in the repository or production
environment file.

## In scope

- Reframe the terminal welcome screen around the active model, execution safety
  boundary, natural-language research tasks, and a small set of operator control
  commands.
- Keep slash commands available through `/help`, but remove market shortcuts
  and mutating paper controls from the welcome screen.
- Describe control commands by operator outcome and governance boundary, rather
  than implementation detail or an implied unrestricted provider switch.
- Keep local readline history best-effort: an invalid, inaccessible, or
  directory-valued history path must not prevent an interactive session from
  starting, completing commands, or recalling commands in the current session.
- Preserve the final Agent conclusion when a market tool returns no matching
  instrument or empty data; an empty structured-tool renderer must never hide
  the operator-facing explanation and next-step guidance.
- Add a read-only Docker Compose secret mount for a server-local Codex auth
  file to the API and worker; an empty fallback must leave Codex unavailable
  rather than exposing a secret or weakening the default local setup.
- Configure the production server only after the released Compose definition is
  deployed: `ACTIVE_CHAT_PROVIDER=codex`, `CODEX_MODEL=gpt-5.4`, and a
  server-local `CODEX_AUTH_SOURCE_PATH`.

## Out of scope

- Changing tool permissions, enabling mainnet trading, adding new slash
  commands, changing the local-development default provider, or copying an
  OAuth token into the repository, CI, or `.env.example`.
- Altering Sprint 115 strategy-sandbox code or its feature flag.

## Done means

- A CLI welcome screen presents an Operator Console, model/risk state,
  natural-language task examples, and only status/review/approval controls.
- The production Compose runtime mounts `/root/.codex/auth.json` only as a
  read-only secret when explicitly configured; the API reports Codex enabled
  and default after server configuration.
- A read-only provider-backed production smoke completes, mainnet remains
  blocked, and the full project check and deployment health check pass.

## Verification

- Focused CLI and deployment configuration tests, then `./scripts/check.sh`.
- Focused CLI coverage for a directory-valued history path that skips disk
  persistence while retaining interactive completion and in-session history.
- A streamed market query with `found=false` still renders its final Agent
  explanation in both terminal animation and Rich rendering paths.
- `docker compose config -q` with no Codex source path and with the
  server-local source path.
- After deployment, verify `/api/harness/overview` reports `codex/gpt-5.4` as
  enabled/default, then run one read-only Agent prompt and confirm production
  health.

## Handoff

- This is a user-directed sidecar change alongside the active sandbox work; it
  does not close, re-scope, or activate the Sprint 115 strategy-sandbox flag.
- If Codex provider availability degrades, switch the server-only
  `ACTIVE_CHAT_PROVIDER` back to `deepseek` and recreate API/worker; no source
  secret rotation or repository change is needed.
