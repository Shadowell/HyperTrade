# Sprint 97 Research Evidence Contract QA

## Verdict

Final verdict: **PASS**. Local gates, production deployment, PostgreSQL migration,
authenticated mutations, public reads, filters, graphs, and lifecycle smokes all
completed successfully.

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

### Not Checked

- No real strategy claim was promoted or modified during the smoke. Production
  writes were explicitly labelled synthetic QA evidence and prove contract wiring,
  not trading performance.
- High-concurrency hash-race behavior was not load-tested on production; unique-key
  race recovery is covered by the service boundary and deterministic tests.

## Verification Evidence

- Focused Evidence V2 plus existing strategy/RAG/BitPro adapter regression:
  `25 passed`.
- Migration `0013_research_evidence_v2` on a temporary SQLite database stamped at
  `0012`: upgrade, downgrade, and upgrade passed.
- Full `./scripts/check.sh`: frontend lint/test/build, Ruff, Mypy, and Python tests
  passed (`361 passed`).
- Implementation commit `a8484b3` deployed successfully in workflow `29340215236`;
  the API could immediately append/read records, proving PostgreSQL migration
  `0013` was applied.
- Production fact `evi_1b69534e27be4c49a555` replayed to the same ID with
  `idempotency_replayed=true`. Counter-evidence `evi_65b614d49dc4430ea814`
  was expired explicitly, and replacement `evi_1acf40f0bc9a401e8cfb` linked by
  `supersedes` while the original remained queryable as `superseded`.
- The bounded graph returned three nodes with `challenges` and `supersedes` edges;
  Task/type filtering returned both historical and active facts, public GET showed
  the Trace source still available, and production health returned OK.

## Next

Activate Sprint 98 and require every research role output to pass through this
Evidence V2 service before it can advance the research graph.
