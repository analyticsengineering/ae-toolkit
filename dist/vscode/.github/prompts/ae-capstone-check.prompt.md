---
description: Check capstone completeness, coherence, evidence, and readiness without completing assessed work.
agent: agent
---
# Check Analytics Engineering Capstone Readiness

Apply the `learning-coach`, `senior-ae-reviewer`, and `pipeline-architect` perspectives as relevant.

## Execution boundary

Inspect only local capstone artifacts and `.ae/exercise.json`. Never require or call MCP, and never run anything against a warehouse. This check submits nothing.

## Workflow

1. Require `.ae/exercise.json`; identify mode, authorized artifacts, deliverables, constraints, and supplied rubric. If criteria are missing, report the gap rather than inventing them.
2. Inventory repository architecture, dbt structure, grains, tests, incremental models, snapshots, documentation, visible scheduled jobs/config, dashboard requirements, README, and portfolio readiness.
3. Check cross-artifact consistency: grain and keys, metric definitions, source-to-model lineage, incremental and failure behavior, privacy, reproducibility, and acceptance criteria.
4. In Assessment mode, perform a read-only review. Do not edit, complete missing deliverables, expose hidden answers, or provide replacement SQL/code.
5. Map every conclusion to supplied criteria using Evidence, Risk or learning impact, Recommendation, Verification, severity, and confidence.
6. Separate blockers, incomplete evidence, and optional improvements. Do not confuse polish with correctness.
7. This is preflight only. Human review remains authoritative for submission and certification decisions.

Remain within analytics engineering.

## Output

Return `# Capstone Readiness` with:

- `Overall status: NOT READY`, `NEARLY READY`, or `READY TO SUBMIT`
- Categories
- Blocking issues
- Recommended improvements
- Next step before submitting
