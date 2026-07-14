# Sprint 97 Research Evidence Contract QA

## Verdict

Local verdict: **PASS**. Production deployment: **PENDING** until the implementation
commit applies migration `0013` and the remote evidence API smokes complete.

## Contract Review

### Passed

- Four Pydantic discriminated evidence inputs normalize timezone-aware UTC,
  Decimal, scope/source ordering, identifiers, and claim whitespace before hashing.
- Canonical JSON and SHA-256 are stable across equivalent timezone, Decimal, and
  input-order representations; a unique content hash makes append idempotent.
- Facts require an available non-Memory source; unavailable sources fail closed or
  become explicit data gaps. Inferences require existing active support, and
  counter-evidence requires an existing challenged record.
- Evidence content is append-only. Expire, reject, and supersede update explicit
  lifecycle state and relation pointers without modifying historical claim/payload.
- Typed graph edges expose support, opposition, challenge, and supersession.
- TraceEvent, RAG, Memory, BitPro result, Paper Snapshot, and legacy experiment
  adapters emit bounded references with IDs, timestamps, and hashes only.
- Source deletion does not cascade; later reads retain the original reference and
  expose an unavailable source plus a remediation data-gap projection.
- Read APIs expose list/filter/get/graph and legacy projections. Append and lifecycle
  mutations require administrator authentication; no Agent mutation tool exists.
- Legacy experiment/StrategyEvidence/Memory records remain read-only and explicitly
  labelled; they are never backfilled as V2 facts.

### Failed

- None in the Sprint 97 implementation or focused regression suite.

### Not Checked Yet

- Production PostgreSQL migration and index creation, pending deployment.
- Production authenticated append, public read/filter/graph, and lifecycle smoke,
  pending deployment. The smoke will use synthetic QA evidence only.

## Verification Evidence

- Focused Evidence V2 plus existing strategy/RAG/BitPro adapter regression:
  `25 passed`.
- Migration `0013_research_evidence_v2` on a temporary SQLite database stamped at
  `0012`: upgrade, downgrade, and upgrade passed.
- Full `./scripts/check.sh`: frontend lint/test/build, Ruff, Mypy, and Python tests
  passed (`361 passed`).

## Next

1. Push the implementation commit and verify the deployment workflow.
2. Verify PostgreSQL-backed append/dedupe/read/filter/graph/lifecycle behavior and
   production health.
3. Record final PASS, close Sprint 97, then activate Sprint 98.
