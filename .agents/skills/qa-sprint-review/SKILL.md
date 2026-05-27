---
name: "qa-sprint-review"
description: "Review a completed sprint against its contract and write a QA report with pass/fail findings."
---

# QA Sprint Review

## Purpose

Evaluate whether a sprint satisfies its contract without assuming implementation success.

## Instructions

1. Read the active sprint contract.
2. Read `docs/progress.md`.
3. Run the relevant checks, starting with `./scripts/check.sh`.
4. Compare observed behavior against the contract.
5. Write a QA report under `docs/qa/`.
6. Be explicit about:
   - what passed
   - what failed
   - what was not checked
   - what should happen next

## Output

- the QA report path
- the verdict
- the most important blocking issue, if any
