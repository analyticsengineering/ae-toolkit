---
name: ae-requirements
description: Turn an analytics request into testable requirements, metric definitions, data contracts, and acceptance criteria.
---
This is the `ae-requirements` alias of the `analytics-requirements` skill. Follow that skill's full procedure and output contract; the summary below orients the request and does not replace it.

# Define Analytics Requirements

Apply the `analytics-requirements` skill workflow.

## Execution boundary

This is a free local workflow. Use local documentation and user-provided context only. Never require or call MCP.

## Workflow

1. Establish decision, audience, owner, scope, urgency, and Work, Learn, or Assessment mode. Read `.ae/exercise.json` if present.
2. Ask only material questions about entities, grain, dimensions, measures, filters, time zones, attribution, history, freshness, latency, and known edge cases.
3. Define each metric unambiguously: numerator, denominator, population, exclusions, time basis, null behavior, and expected reconciliation source.
4. Identify candidate sources, keys, lineage, quality constraints, privacy classification, ownership, and unresolved assumptions.
5. Produce a concise requirements brief with in-scope/out-of-scope items, data contract, acceptance criteria, validation plan, risks, and open decisions.
6. For each material concern, state Evidence, Risk, Recommendation, and Verification.
7. In Learn mode, coach the learner to supply definitions. In Assessment mode, evaluate requirement quality without filling in missing answers.

Reject requests that are primarily frontend, generic backend, SEO, DevOps, or general application planning.

Do not convert unresolved ambiguity directly into SQL.

## Output

Return `# Analytics Requirements` with: Business question; Decision being supported; Metric definition; Numerator; Denominator; Grain; Dimensions; Required sources; Attribution assumptions; Time-window assumptions; Edge cases; Data quality requirements; Potential marts; Acceptance criteria; Questions that MUST be answered before implementation.
