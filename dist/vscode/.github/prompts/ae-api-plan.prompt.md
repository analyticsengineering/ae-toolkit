---
description: Plan a resilient API-based analytics ingestion pipeline with contracts, state, quality, and recovery.
agent: agent
---
# Plan an Analytics API Pipeline

Apply the `api-pipeline` skill workflow and the `pipeline-architect` agent perspective.

## Execution boundary

- **Local Basic (default/free):** Design from local specifications and user-provided examples. Never require or call MCP.
- **Connected Advanced:** Inspect an API or external catalog only after explicit user request, authentication, a redacted request and payload preview, and approval. Start with non-mutating discovery.

## Workflow

1. Confirm the analytical use case, source and destination, owners, expected volume, cadence, latency, history, retention, and compliance needs.
2. Define endpoint and data contracts, grain, keys, schema, timestamp semantics, pagination, versioning, and change policy.
3. Design authentication boundaries without handling raw secrets; define cursor or watermark state, incremental windows, deduplication, idempotency, late arrivals, backfills, and replay.
4. Specify rate-limit handling, retries and backoff, timeouts, partial responses, poison records, checkpoints, and recovery.
5. Define raw and modeled layers, lineage, quality tests, observability, cost controls, and acceptance criteria.
6. Present assumptions, alternatives, trade-offs, Evidence, Risk, Recommendation, and Verification.
7. In Assessment mode, critique the submitted plan without completing it.

Do not expand into frontend, generic backend, SEO, deployment infrastructure, or general app architecture.

Do not create production credentials or implement code until the user explicitly asks after reviewing the plan.

## Output

Return `# API Pipeline Plan` with: Source; Authentication; Extraction strategy; Pagination; Incremental strategy; Raw schema; Warehouse landing architecture; Transformation handoff; Retry/error strategy; Secrets; Validation; Scheduling; Risks; Implementation steps.
