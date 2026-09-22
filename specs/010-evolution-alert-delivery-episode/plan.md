# Plan

Keep the existing `EvolutionAlert` row, deterministic ID, and three alert rules. Treat a changed signature on an open row as a new episode using the same reset path as resolved or acknowledged changed rows. On business-success delivery, persist `delivery_signature` and `delivery_message_hash` in existing JSON payload. At list time, require those bindings to match the current signature and message, alongside the existing business-success receipt. Never synthesize bindings for old rows.

Touch only `evolution_alerts.py`, focused tests, Spec Kit artifacts, and durable alert contract/progress text. Verify focused pytest plus Ruff/mypy; the integration owner runs the combined full check.

Upgrade boundary: treat an open row with an old delivery time but missing receipt bindings as needing revalidation. Bypass the old successful-delivery and attempt delay once, preserve the old acceptance metadata separately without inventing a historical signature, and after any failed revalidation let the existing six-hour attempt gate control retries. A successful revalidation writes the current bindings and restores normal 24-hour reminders.
