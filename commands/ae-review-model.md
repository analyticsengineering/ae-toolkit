---
name: ae-review-model
description: Review an analytical data model's grain, semantics, contracts, lineage, tests, and change impact.
---

# Review an Analytical Model

Apply the `data-model-review` skill workflow and the `senior-ae-reviewer` agent perspective.

## Execution boundary

This is a free local workflow. Inspect local SQL, YAML, manifests, catalogs, docs, requirements, source schemas, and diffs. Never require or call MCP.

## Workflow

1. Require the business process, decisions/use cases, consumers, grain, natural/business keys, update cadence, and upstream/downstream scope. Do not turn missing business context into an assumed model. Read `.ae/exercise.json` if present.
2. Trace lineage and verify facts, dimensions, entity boundaries, join cardinality, many-to-many bridges, slowly changing dimensions, event/snapshot strategy, time semantics, null handling, metric compatibility, and incremental/backfill logic.
3. Review contracts, naming, documentation, ownership, tests, freshness, observability, and compatibility with downstream consumers.
4. Assess change impact, warehouse cost, migration needs, and rollback or reconciliation strategy.
5. Report supported findings using Evidence, Risk, Recommendation, Verification, severity, and confidence.
6. In Learn mode, use questions and partial guidance. In Assessment mode, apply only the supplied rubric and do not provide a replacement design.
7. Never equate normalization with quality; choose architecture based on business use and change behavior.

## Output

Return `# Data Model Review` with: Business process; Proposed grain; Facts; Dimensions; Relationships; Risks; SCD strategy; Metric implications; Recommended architecture; Questions for stakeholder.
