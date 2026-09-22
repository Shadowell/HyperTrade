# Plan

Keep the existing `EvolutionAlert` row, deterministic ID, and three alert rules. Treat a changed signature on an open row as a new episode using the same reset path as resolved or acknowledged changed rows. On business-success delivery, persist `delivery_signature` and `delivery_message_hash` in existing JSON payload. At list time, require those bindings to match the current signature and message, alongside the existing business-success receipt. Never synthesize bindings for old rows.

Touch only `evolution_alerts.py`, focused tests, Spec Kit artifacts, and durable alert contract/progress text. Verify focused pytest plus Ruff/mypy; the integration owner runs the combined full check.
