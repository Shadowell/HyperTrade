# Target-bound research budget identity

## Scope

Bind automatic research admission and source cooldown to a registered market target, strategy, and Paper instance. Preserve the existing shared daily, total, and active mission limits across every target. This slice changes only the budget ledger and its tests; market reads and evolution scheduling belong to R7.

## Requirements

- A source is identified by `(target_id, strategy_id, instance_id)`. A missing historical `target_id` means `bitpro`; no historical record is rewritten.
- BitPro strategy IDs remain strictly positive integers. Other targets accept a nonempty, bounded opaque string, preserving its spelling. Empty/malformed identities fail closed.
- Budget receipts expose target and strategy identity. Source busy/cooldown state and idempotent replay cannot collide when different targets or strategies reuse the same instance ID. A mission ID already bound to another source must not replay as accepted.
- Daily, total, and active usage count all automatic research missions globally, including pre-ledger and legacy BitPro missions. Changing the configured target cannot reset or bypass a limit.
- Admission accepts only a source for the currently configured target. A denied admission creates no mission or budget debit.

## Acceptance

1. Same instance and strategy IDs on BitPro and a non-BitPro target have separate source state, while both consume the same global budget.
2. Same-target, different-strategy reuse of an instance ID also has separate source state.
3. Historical missing-target missions and receipts remain BitPro and consume their existing global credit.
4. String strategies are accepted only for non-BitPro targets; invalid identities or target mismatch are rejected without a mission.
5. Replay with the same mission and source is idempotent; replay with a changed source is rejected.
6. PostgreSQL concurrent admission still admits no more than the shared limit.

## Boundaries

No external market write, production configuration change, Paper/Live action, push, or deployment in this slice.
