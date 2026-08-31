---
name: api-pipeline
description: Designs and reviews reliable API-to-analytics ingestion pipelines with architecture-first plans for extraction, state, schemas, security, and operations. Use when planning or implementing ingestion from REST, GraphQL, webhook, or third-party APIs.
---

# API Pipeline

Plan architecture and contracts before writing connector code. Never request, embed, print, or invent credentials.

## When to use

- Design a new API ingestion pipeline or review an existing connector.
- Plan full, incremental, CDC-like, polling, or webhook ingestion into an analytics platform.
- Use before implementation when API behavior and operational guarantees are incomplete.

## Required context

Obtain without soliciting secrets:

- Business use case, required entities/fields, destination, consumers, latency, volume, retention, and backfill needs.
- API documentation/version, resource relationships, pagination, rate limits, quotas, filtering, ordering, update/delete semantics, and terms.
- Authentication **method and secret reference mechanism only**, not credential values.
- Runtime/orchestrator, storage layers, network constraints, observability, ownership, and recovery objectives.

Default silently to Work mode and produce an implementation-ready architecture and phased plan. In Learn mode, explain reliability tradeoffs. In Assessment mode, evaluate the learner's submitted design against failure scenarios without showing a reference answer.

## Inspection procedure

1. Define the data product: consumers, entities, grain, freshness, completeness, history, and service objectives.
2. Read authoritative API behavior and record unknowns. Do not infer pagination, ordering, or deletion behavior from one response.
3. Design architecture before code:
   - trigger/orchestration;
   - authentication via runtime secret reference;
   - extractor and request policy;
   - raw immutable landing;
   - normalization/modeling;
   - state/checkpoint store;
   - observability, quarantine, replay, and ownership.
4. Specify extraction mode per endpoint: initial load, incremental cursor/watermark, overlap window, webhook plus reconciliation, and periodic full comparison.
5. Specify pagination termination, stable ordering, rate limiting, bounded retries with jitter, timeout, idempotency, and resumability.
6. Define schema contract, raw payload retention, versioning, type drift, nullable/new/removed fields, and malformed-record handling.
7. Define update/delete semantics, deduplication key, event versus extraction time, late data, and backfill isolation.
8. Threat-model secret handling, least privilege, logging redaction, data minimization, retention, and vendor terms.
9. Define tests, metrics, alerts, runbooks, cost controls, deployment, and rollback.
10. Only after approval of architecture and unresolved tradeoffs, produce implementation steps or code.

Documentation inspection is read-only. Calling the API, connected services, secret managers, clouds, warehouses, or deployment systems requires an explicit user trigger; obtain approval before any request that may consume quota, reveal data, create resources, or mutate state.

## Decision framework

Choose patterns based on guarantees:

- Prefer a server-provided cursor/change token over timestamps.
- Use timestamp watermarks only with stable semantics and an overlap/dedup strategy.
- Use webhooks for latency, paired with polling/reconciliation for loss recovery.
- Land raw responses before destructive normalization when replay/audit value justifies retention.
- Reject an architecture that cannot resume, detect silent loss, handle rate limits, or represent deletes required by the use case.

Trade off freshness, completeness, cost, complexity, and recoverability explicitly.

## Failure modes

- Coding against a happy-path sample before defining state and replay.
- Passing credentials in prompts, source, commands, URLs, logs, or examples.
- Assuming page number pagination is stable under concurrent updates.
- Retrying non-idempotent requests indiscriminately.
- Advancing a checkpoint before durable persistence.
- Ignoring deletes, schema drift, quota resets, backfills, or webhook loss.

## Evidence required

For each architectural claim, cite API documentation, observed approved response metadata, destination constraint, or explicit assumption. Record endpoint/version and retrieval date when documentation can change. For every unresolved API behavior, provide a safe validation test and expected outcomes.

## Output contract

Return `# API Pipeline Plan` with: Source; Authentication; Extraction strategy; Pagination; Incremental strategy; Raw schema; Warehouse landing architecture; Transformation handoff; Retry/error strategy; Secrets; Validation; Scheduling; Risks; Implementation steps.

Do not include credential values or runnable calls containing secrets.

## Verification

- Test pagination boundaries, empty pages, duplicate pages, and changing datasets.
- Test timeout, 429, 5xx, invalid payload, expired auth, restart, and checkpoint failure.
- Reconcile API totals or sampled IDs when available.
- Verify idempotent replay, overlap deduplication, delete handling, schema drift, and backfill isolation.
- Confirm logs/metrics contain no secrets or sensitive payloads.

## Safety/privacy

- Refer to secrets only by environment variable or secret-manager reference.
- Apply least privilege, TLS, log redaction, minimization, encryption, retention, and access controls.
- Never make test calls against production or consume quota without approval.
- Respect API terms, data residency, deletion obligations, and protected-data constraints.

## What not to assume

Do not assume credentials exist, APIs are stable, docs are current, ordering is deterministic, timestamps are reliable cursors, retries are safe, deletes are exposed, quotas are generous, raw retention is permitted, or the destination can accept schema drift.
