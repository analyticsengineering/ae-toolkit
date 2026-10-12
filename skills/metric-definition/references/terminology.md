# Toolkit Terminology

## Modes

- **Work mode** — Deliver a production-oriented analysis or implementation. Inspect first, state assumptions, make only authorized changes, and verify.
- **Learn mode** — Teach through questions, explanations, and progressively stronger hints. Preserve the learner's agency; do not replace their work unless they explicitly leave Learn mode.
- **Assessment mode** — Evaluate submitted work against stated criteria. Do not reveal the answer, supply a replacement solution, or edit the submission.

When `.ae/exercise.json` exists, use it to determine exercise identity, mode, constraints, rubric references, allowed tools, and expected artifacts. Do not invent missing rubric criteria.

## Execution tiers

- **Local Basic** — Free, local-only behavior using repository files, user-provided content, and local tools. It never requires or calls MCP.
- **Connected Advanced** — An explicitly requested operation using an authenticated external data or content connection. It requires destination and content preview, secret redaction, and approval before access or transmission.

## Review terms

- **Evidence** — Reproducible fact supporting a conclusion.
- **Risk** — Potential impact and the conditions that trigger it.
- **Recommendation** — Proportionate action addressing the cause.
- **Verification** — Check that demonstrates the recommendation worked.
- **Analysis-first** — Understand artifacts, scope, and query behavior before any database execution or mutation.

## Scope

In scope: SQL, analytical data modeling, dbt, data profiling and quality, analytics requirements, warehouse behavior, and ingestion/API data pipelines.

Out of scope: frontend UI, generic backend services, SEO, DevOps/platform operations, and general application development. API work is in scope only when it designs or reviews data ingestion, extraction, contracts, lineage, or analytical delivery.
