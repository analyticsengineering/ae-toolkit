---
name: ae-debug
description: Debug an analytics data, SQL, dbt, or pipeline failure through evidence and testable hypotheses.
---
# Debug Analytics Engineering Failures

Apply the `data-quality-investigation` skill workflow and the `data-quality-investigator` agent perspective.

## Execution boundary

- **Local Basic (default/free):** Use local code, logs, artifacts, fixtures, and reproducible commands. Never require or call MCP.
- **Connected Advanced:** Only after explicit user request. Authenticate, preview the redacted logs, metadata, or bounded query, obtain approval, then use least-privilege read-only access.

## Workflow

1. Capture and independently verify the exact symptom, expected result, last known good state, affected scope, and reproduction. Read `.ae/exercise.json` if present.
2. Investigate in this order unless evidence justifies a documented deviation: metric definition; source freshness; extraction completeness; row counts; schema changes; null changes; duplicate changes; join/cardinality changes; transformation changes; dbt/test failures; metric/business-rule changes; BI/report filtering.
3. Track every candidate as `Hypothesis`, `Evidence`, `Status`, and `Next test`; run one discriminating test at a time and update the state.
4. Do not randomly inspect files or infer root cause from correlation. Claim root cause only when a proven mechanism connects the evidence to the symptom.
5. In Learn mode, guide the next diagnostic step without taking over. In Assessment mode, evaluate debugging reasoning without disclosing the answer.
6. Do not implement a fix, backfill, rerun, or repair unless separately requested and approved.

## Output

Return `# Data Incident Investigation` with: Observed symptom; Most likely causes; Evidence checked; Ruled-out hypotheses; Remaining hypotheses; Root cause, if proven; Recommended fix; Prevention; Tests/alerts to add.
