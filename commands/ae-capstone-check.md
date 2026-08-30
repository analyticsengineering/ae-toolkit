---
name: ae-capstone-check
description: Check capstone completeness, coherence, evidence, and readiness without completing assessed work.
---

# Check Analytics Engineering Capstone Readiness

Apply the `learning-coach`, `senior-ae-reviewer`, and `pipeline-architect` perspectives as relevant.

## Execution boundary

- **Local Basic (default/free):** Inspect only local capstone artifacts and `.ae/exercise.json`. Never require or call MCP.
- **Connected Advanced:** Use external grading, catalog, or warehouse context only after explicit user request, authentication, a destination and redacted content preview, and explicit approval. Use read-only access.

## Workflow

1. Require `.ae/exercise.json`; identify mode, authorized artifacts, deliverables, constraints, and supplied rubric. If criteria are missing, report the gap rather than inventing them.
2. Inventory repository architecture, dbt structure, grains, tests, incremental models, snapshots, documentation, visible scheduled jobs/config, dashboard requirements, README, and portfolio readiness.
3. Check cross-artifact consistency: grain and keys, metric definitions, source-to-model lineage, incremental and failure behavior, privacy, reproducibility, and acceptance criteria.
4. In Assessment mode, perform a read-only review. Do not edit, complete missing deliverables, expose hidden answers, or provide replacement SQL/code.
5. Map every conclusion to supplied criteria using Evidence, Risk or learning impact, Recommendation, Verification, severity, and confidence.
6. Separate blockers, incomplete evidence, and optional improvements. Do not confuse polish with correctness.
7. This is preflight only. Human review remains authoritative for submission/certification decisions.

Keep connected checks in a separately approved section and remain within analytics engineering.

## Output

Return `# Capstone Readiness` with:

- `Overall status: NOT READY`, `NEARLY READY`, or `READY TO SUBMIT`
- Categories
- Blocking issues
- Recommended improvements
- Submission CTA
