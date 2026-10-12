---
name: data-model-review
description: Reviews analytical data models against business use cases, grain, dimensional design, history, relationships, and metric semantics. Use when evaluating schemas, marts, facts, dimensions, ERDs, or model proposals.
---

# Data Model Review

Judge the model by the decisions it must support, not by diagram aesthetics.

## When to use

- Review conceptual, logical, or physical analytical models.
- Evaluate facts, dimensions, marts, semantic models, SCDs, bridges, snapshots, and metric implications.
- Use before implementation or when existing models produce ambiguous analytics.

## Required context

Obtain or mark missing:

- Business use cases, users, decisions, required metrics, dimensions, and service expectations.
- Entity definitions, event/process boundaries, model DDL/ERD, source behavior, and sample cardinalities.
- Declared grain for every fact-like model and keys for every model.
- Required history, correction, deletion, latency, and late-arriving-data behavior.

Default silently to Work mode and recommend a decision-ready design. In Learn mode, explain grain and tradeoffs with examples. In Assessment mode, grade submitted reasoning against stated requirements and never supply the design answer.

## Inspection procedure

1. Restate each business use case as a question, metric, slice, time horizon, and freshness need.
2. Inventory models and classify their role without relying only on names.
3. Write one grain statement per fact, event, snapshot, bridge, and aggregate: “one row per …”.
4. Trace natural, surrogate, and foreign keys; validate uniqueness/cardinality evidence.
5. Map measures to additive, semi-additive, or non-additive behavior and identify safe aggregation dimensions.
6. Inspect conformed dimensions, role-playing dimensions, degenerate dimensions, and unknown/not-applicable members.
7. Evaluate history explicitly: SCD type, effective intervals, current flags, corrections, deletes, and late-arriving facts/dimensions.
8. Evaluate many-to-many relationships. Require a bridge grain, allocation/weight semantics, validity dates when needed, and double-count controls.
9. Trace each required metric through joins and history rules; identify denominator, fanout, restatement, and comparability implications.
10. Evaluate physical choices only after logical correctness: partitioning, clustering, materialization, incremental strategy, and cost.

Read-only artifacts may be inspected. Connected catalogs, warehouses, diagram services, model execution, or edits require explicit user trigger; costly or mutating actions require approval.

## Decision framework

For each use case, rate:

- **Supported** — grain, keys, history, and metric path are explicit and correct.
- **Supported with constraints** — usable only under named filters, time rules, or allocation logic.
- **At risk** — plausible design, but missing evidence can materially change results.
- **Unsupported** — model cannot answer the use case without ambiguity or double counting.

Prioritize defects that violate grain, permit fanout, erase required history, or change metric meaning. Prefer the simplest model that preserves required semantics; do not force star, wide-table, Data Vault, or normalized patterns by ideology.

## Failure modes

- Starting from tables instead of business use cases.
- Accepting “one row per entity” without defining entity identity and time.
- Recommending SCD Type 2 without query semantics or source-change evidence.
- Introducing a bridge without weights or duplicate-control rules.
- Treating surrogate keys as proof of uniqueness.
- Reviewing dimensions while ignoring metric denominators and restatement.

## Evidence required

Each finding includes affected use case, model and grain, observed schema/cardinality/history evidence, failure scenario, metric or consumer impact, and recommendation. Label assumptions and name the query or stakeholder decision needed to resolve each unknown.

For SCD findings, show interval/current-row behavior. For bridge findings, show relationship cardinality and aggregation behavior. For metric findings, trace numerator, denominator, join path, and time semantics.

## Output contract

Return `# Data Model Review` with: Business process; Proposed grain; Facts; Dimensions; Relationships; Risks; SCD strategy; Metric implications; Recommended architecture; Questions for stakeholder.

Scale the report to the model under review: when a section has nothing to say about a single small model, omit the heading instead of printing it empty, and keep every section when the review covers a full mart, a published contract, or an explicitly requested formal review. Lead with a short fit-for-purpose decision and the few grain/cardinality failures that drive it. Use one compact model inventory for proposed grains, keys, and roles; reference that inventory instead of repeating the same design in Facts, Relationships, Risks, and Architecture. Default to the five highest-impact risks and the stakeholder questions that can change the architecture. Ask nothing the submitted model or the repository already answers, and leave the question section empty with a line saying so when the design is unambiguous. Put deeper edge-case scenarios in Verification only when they discriminate between designs.

## Verification

- Confirm every fact-like model has one unambiguous grain.
- Walk at least one normal and one boundary scenario per critical use case.
- Reconcile joins using observed or requested cardinality checks.
- Test historical “as was” versus current-state queries where required.
- Demonstrate that bridge joins cannot silently double count.
- Recalculate representative metrics from the proposed path.

## Safety/privacy

- Use metadata and aggregate cardinalities before row-level data.
- Do not expose sensitive dimensions, identifiers, or business metrics unnecessarily.
- Never query production or modify models without explicit approval.
- Flag models that broaden access to protected attributes or enable re-identification.

## What not to assume

Do not assume names reveal grain, source keys are stable, relationships are one-to-many, history is unnecessary, facts arrive in order, all measures are additive, dimensions are conformed, bridge weights sum to one, or stakeholders share a metric definition.
