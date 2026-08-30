---
name: ae-review-sql
description: Review analytical SQL for correctness, grain, safety, maintainability, performance, and test coverage.
---

# Review Analytical SQL

Apply the `sql-review` skill workflow and the `senior-ae-reviewer` agent perspective.

## Execution boundary

This is a free local workflow. Review local files, diffs, compiled SQL, or pasted SQL only. Never require or call MCP. Do not execute SQL unless the user separately requests an approved `SELECT` or `EXPLAIN` against a local/development connection.

## Workflow

1. Confirm dialect, intended grain, business purpose, and review scope. Read `.ae/exercise.json` if present.
2. Inspect CTEs, joins and cardinality, filters, nulls, types, time zones and boundaries, aggregations, windows, deduplication, determinism, and incremental behavior.
3. Check readability, portability, likely scan cost, and whether tests cover keys, accepted values, relationships, freshness, and edge cases.
4. Do not execute SQL merely to understand it; reason from local evidence first.
5. Report only supported findings, ordered by severity. For each give Evidence, Risk, Recommendation, Verification, severity, and confidence.
6. In Learn mode, explain and prompt before rewriting. In Assessment mode, evaluate without revealing corrected SQL or editing the submission.
7. Never call SQL correct merely because it parses. Always state `Expected grain`, `Actual/possible grain`, and `Cardinality risk` when evidence permits.

## Output

Use exactly these top-level sections:

```text
# SQL Review
## Summary
## Critical Issues
## Warnings
## Grain & Cardinality
## Correctness
## Performance
## Maintainability
## Recommended Changes
## Verification Queries
## Learning Note
```

Use `BLOCKER`, `HIGH`, `MEDIUM`, `LOW`, or `INFO`. Every BLOCKER/HIGH claim must identify the exact evidence, impact, and verification.
