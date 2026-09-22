# Plan

Use existing evolution scan, continuation, and alert projections. Filter unavailable inventory rows with the same strategy scope as successful rows. Mark a failed snapshot read explicitly and retain `readiness`'s existing behavior for a returned snapshot. Use the existing `recent_read_unavailable` category and fixed Chinese reason/action; never surface raw upstream errors as the operator diagnosis. Filter alert continuation inputs using the current control scope, allowing the normal desired-versus-existing alert reconciliation to resolve old out-of-scope records.

Touch `evolution.py`, `evolution_continuation.py`, `evolution_alerts.py`, targeted tests, and durable project status/docs. Verify focused regression, then `scripts/check.sh`.
