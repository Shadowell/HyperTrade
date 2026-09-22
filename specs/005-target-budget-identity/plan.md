# Plan

1. Keep the existing `EvolutionCycle` receipt and `ArcMission` transaction. Normalize target/strategy/instance into one source key and preserve old missing-target records as BitPro.
2. Expose one source-key helper for R7's evolution status lookup. Keep existing budget public entrypoints and global counters.
3. Add failing budget tests for cross-target and cross-strategy collisions, legacy records, opaque IDs, wrong-target admission, replay conflict, and shared limits. Then make the narrow ledger change.
4. Run targeted budget/evolution tests, Ruff, mypy, and GitNexus change detection. Total project check and integration run in the controller's exclusive window.

Integration dependency: R7 changes the evolution reader from a bare instance lookup to `source_key(target_id, strategy_id, instance_id)` and updates non-BitPro fixtures to string strategy IDs. The R8-only branch keeps those R7 files untouched.
