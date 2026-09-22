# Evolution Alert Delivery Episode

## Goal
An operator must see whether the currently displayed evolution alert was actually accepted for delivery. A successful receipt for an older condition or message is not current delivery evidence.

## Requirements
- FR-001: A changed alert condition signature begins a new episode even while the same strategy/code alert remains open; it is eligible for immediate delivery with the new explanation.
- FR-002: Successful delivery records the exact condition signature and current message hash. `delivery_verified` is true only when the business receipt and both bindings match the displayed alert.
- FR-003: Legacy receipts without both bindings remain unverified; no historical signature or message is inferred.
- FR-004: Unchanged conditions keep the 24-hour reminder and six-hour failed-attempt cadence. Acknowledgement suppresses the same condition; changed conditions and resolved-then-reappearing conditions retain existing reopen semantics.
- FR-005: This slice does not change Paper, alert transport, approval, research admission, or production policy.
- FR-006: An open alert whose prior `sent` receipt lacks binding must attempt one fresh delivery promptly, even within the old 24-hour window. Preserve the old receipt as an unbound observation; failed revalidation follows the ordinary six-hour retry, acknowledgement stays quiet, and fully bound message-only changes keep the ordinary reminder cadence.

## Acceptance
Tests first reproduce open-condition drift and stale-receipt misattribution, then cover message-only drift, legacy receipts, unchanged cadence, acknowledgement, and new-condition delivery.
