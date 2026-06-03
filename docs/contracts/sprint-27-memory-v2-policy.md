# Sprint 27 Contract: Memory v2 Policy And Audit

## Goal

Upgrade Memory from basic audited writes to policy-shaped, searchable, deduplicated memory.

## Scope

- Add `importance`, `tags`, `confidence`, `last_used_at`, and `usage_count`.
- Deduplicate exact same active memory content by kind.
- Support memory search by query, kind, and tag.
- Add CLI `/memory search <query>` and `/memory disable <id>`.
- Extend API `/api/memory` query parameters.
- Keep source run/tool audit fields.

## Acceptance

- Repeated identical memory writes return the existing item and increment usage.
- Memory search updates usage metadata.
- API, CLI, and frontend expose search/filter/disable paths.
- Memory records retain source run/tool provenance.

## Verification

```bash
uv run pytest tests/test_rag_memory.py tests/test_cli.py tests/test_api.py -q
./scripts/check.sh
```

