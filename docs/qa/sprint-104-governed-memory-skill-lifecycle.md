# Sprint 104 Governed Memory and Skill Lifecycle QA

## Verdict

LOCAL PASS; production deployment acceptance pending. Assertion lifecycle, code-free
Skill policy, signed isolated evaluation boundary, immutable release/rollback and all
operator review surfaces satisfy the Sprint contract locally.

## Scope Checked

- Evidence V2 source requirements, review idempotency, conflict, supersede and expiry;
- normal Memory list/search fail-closed behavior and legacy projection compatibility;
- malicious content, unknown/write tools, role permission expansion and hash tamper;
- HMAC evaluation attestation issuance/verification, privacy projection and missing-key denial;
- administrator approval, version/diff, active pointer, rollback and role prompt loading;
- authenticated API, CLI, TUI and Web reason-required review surfaces;
- PostgreSQL migration reversibility and the existing Agent/eval/tool-policy regressions.

## Evidence

- Full `./scripts/check.sh`: frontend lint, 8 tests and build; Ruff; strict mypy over
  138 source files; 464 Python tests.
- PostgreSQL `0017_memory_skills` upgrade, downgrade to `0016_research_triggers`, and
  re-upgrade passed; all eight expected tables were inspected.
- Focused Memory/Skill/role/API/CLI/TUI suites passed, including forged attestation,
  missing verifier secret, expired Evidence V2, conflict, malicious Skill and release
  hash-tamper cases.

## Findings Fixed During QA

- Normal Memory reads now refresh governed source lifecycle, preventing stale linked
  `MemoryItem` use when Evidence expires between governance-page visits.
- Isolated evaluation metadata is now HMAC-authenticated; administrator authentication
  alone cannot forge a passing evaluation import.
- Assertion decisions use PostgreSQL row locks, while Skill decisions combine proposal
  row locks with a skill-key transaction advisory lock so concurrent first releases
  cannot both mint version 1.
- CLI reason parsing preserves multi-word audit reasons; TUI/Web controls remain thin
  clients over the server state machine.

## Boundaries

- Skill V1 never executes code, installs packages, adds endpoints or registers tools.
- A Skill cannot widen a role allowlist or any BitPro/paper/live permission.
- Memory confidence never overrides source expiry, conflict or explicit rejection.
- Production without `SKILL_EVAL_ATTESTATION_SECRET` intentionally cannot accept an
  isolated evaluation; the secret must exist only in server-managed production/eval env.

## Next

Deploy and verify migration/API/runtime fail-closed behavior, then close Sprint 104 and
activate Sprint 105 Portfolio Strategy Lifecycle.
