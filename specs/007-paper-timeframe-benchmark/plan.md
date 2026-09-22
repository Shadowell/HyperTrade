# Plan

1. Add a conservative timeframe resolver to the existing BitPro inventory/dashboard performance projection. Carry only the explicit config timeframe; compare it with the identity-checked dashboard and any top-level field.
2. Extend the read-only market klines adapter with optional bounded start/end arguments. For short strategy periods, choose a 1h benchmark period while keeping strategy_timeframe in the result.
3. Build the exact 337-point close-time grid from 337 completed hourly bars and fail closed on any missing, extra, duplicate, or misaligned bar. Require each portfolio member to have the same grid.
4. Add adapter-contract and benchmark regressions; run targeted tests and `./scripts/check.sh`, then inspect the diff and commit this branch.
