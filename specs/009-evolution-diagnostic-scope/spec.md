# Evolution Diagnostic Scope and Read Failure

## Goal
The configured strategy scope must govern both successful and unavailable inventory rows and the alerts derived from current or older continuations. A missing upstream read must not claim a Paper session lost its identity or start time.

## Requirements
- FR-001: With a nonempty `strategy_ids` scope, only those strategy IDs appear in scan diagnostics and current strategy alerts. An empty scope retains all running strategies.
- FR-002: An unavailable inventory row or failed snapshot read produces a fixed, retryable upstream-read explanation. It does not produce `session_identity` or `session_start` blockers without a returned snapshot.
- FR-003: A returned snapshot with missing identity or start fields keeps the existing operator blockers and all cost, trade, window, budget, and review gates.
- FR-004: Existing out-of-scope strategy alerts resolve through the established alert lifecycle. No Paper or production configuration is mutated by this fix.
- FR-005: Missing, invalid, or nonpositive inventory strategy IDs remain unattributed coverage gaps; they cannot abort scans or be assigned to a different strategy.
- FR-006: A received snapshot rejected by identity or shape validation is a fixed operator-visible contract mismatch, distinct from a transport failure. Missing version fields in a returned snapshot retain the original identity blocker.

## Acceptance
Tests reproduce the false alerts before the fix, prove scoped diagnostics and alert resolution, distinguish read failure from a returned incomplete snapshot, and preserve the original eligibility rules.
