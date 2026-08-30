---
name: sql-review
description: Reviews analytical SQL for correctness, safety, performance, maintainability, and business-logic risk. Use when the user asks to review a query, SQL model, migration, or SQL diff.
---

# SQL Review

Produce an evidence-based review; do not rewrite or execute SQL unless the user asks.

## When to use

- Review SQL files, pasted queries, dbt models, warehouse transformations, or SQL changes.
- Assess correctness, grain, joins, null handling, temporal logic, portability, cost, and readability.
- Do not use as a substitute for incident investigation or full dimensional-model review.

## Required context

Obtain, or explicitly mark missing:

- SQL text or diff and SQL dialect/warehouse.
- Intended business result, output grain, keys, and time semantics.
- Source schemas, constraints, representative cardinalities, and materialization context.
- Runtime/query-plan evidence when performance is in scope.
- Operating mode: **Work**, **Learn**, or **Assessment**.

If mode is unstated, infer from the request and state the inference. In Work mode, prioritize actionable findings. In Learn mode, explain reasoning and use progressive hints; show a solution only after attempts and an explicit request. In Assessment mode, evaluate independently without revealing or constructing the answer.

## Inspection procedure

1. Establish intent, output grain, dialect, and execution context.
2. Read the complete query and directly referenced definitions before judging a fragment.
3. Trace CTEs and subqueries from sources to output; record grain changes.
4. Inspect filters, three-valued logic, type coercion, timestamps/time zones, and boundary conditions. Treat every hard-coded reporting horizon, start date, end date, and rolling window as an output-scope decision: tie it to the stated requirement or flag it for removal or explicit authorization and parameterization.
5. Inspect joins for key completeness, fanout, dropped rows, many-to-many behavior, and null matching.
6. Inspect aggregations, windows, deduplication, ordering determinism, and metric definitions.
7. Inspect incremental logic, late-arriving data, idempotency, and destructive statements when present.
8. Assess performance only from defensible signals: scan shape, repeated work, predicates, join strategy, query plan, or runtime.
9. Separate verified defects from risks and questions. Consolidate duplicate findings.
10. Report using [the standard report](references/report-format.md).

Read-only inspection is allowed. Execution, database access, query-plan generation, connected warehouse use, or edits require an explicit user trigger; any potentially costly or mutating action requires approval immediately before it.

## Decision framework

Assign the lowest defensible severity:

- **BLOCKER** — likely data corruption, destructive behavior, security/privacy exposure, or materially wrong production output across normal inputs; merging/running must stop.
- **HIGH** — probable material correctness, grain, metric, or reliability defect with significant business impact.
- **MEDIUM** — bounded correctness, maintainability, portability, or performance risk worth fixing.
- **LOW** — minor robustness or clarity issue with limited impact.
- **INFO** — question, observation, or optional improvement; not a defect.

Every BLOCKER/HIGH finding must include concrete evidence: exact location, triggering input or logical path, expected versus actual behavior, impact, and why the severity follows. Without that evidence, lower the severity or state a question. Style alone is never BLOCKER/HIGH.

## Failure modes

- Reviewing syntax without validating business grain.
- Assuming keys are unique, joins are one-to-one, or timestamps share a zone.
- Calling a hypothetical edge case a production defect.
- Giving generic performance advice without a plan, runtime, or scan-based rationale.
- Treating dialect-specific valid SQL as invalid.
- Hiding several defects inside one broad finding.

## Evidence required

Each finding identifies file/CTE and line or unique snippet, the violated invariant, evidence, impact, and smallest safe remediation. Distinguish:

- **Observed**: directly shown by SQL, schema, plan, test, or output.
- **Inferred**: follows from stated constraints.
- **Unknown**: requires a named check.

BLOCKER/HIGH findings require observed or strongly constrained evidence, never preference.

## Output contract

Return `# SQL Review` with these sections, in order: Summary; Critical Issues; Warnings; Grain & Cardinality; Correctness; Performance; Maintainability; Recommended Changes; Verification Queries; Learning Note.

Within Grain & Cardinality, state `Expected grain`, `Actual/possible grain`, and `Cardinality risk` when evidence permits. Use `BLOCKER`, `HIGH`, `MEDIUM`, `LOW`, and `INFO`. A clean review must still state inspected scope and residual uncertainty.

Keep one primary home for each finding and cross-reference it instead of repeating it across sections. Prioritize material correctness over style. Default to the 3–5 verification queries that best distinguish the major risks, each with an expected result. Do not include a full rewritten query unless the user asks for one.

## Verification

Before finalizing:

- Re-trace each finding against the actual SQL and intended grain.
- Reconcile every literal date/window restriction with the declared reporting scope; acknowledging a missing requirement is insufficient if the recommendation silently preserves the restriction.
- Ensure every BLOCKER/HIGH has the required evidence.
- Check severity consistency and remove duplicates.
- Confirm suggested SQL matches the declared dialect.
- Label all unexecuted checks and unresolved assumptions.

## Safety/privacy

- Never execute mutating SQL, production queries, or expensive scans without explicit approval.
- Prefer metadata, sampled, bounded, or dry-run evidence.
- Do not expose credentials, raw sensitive values, or unnecessary row-level data.
- Redact secrets and protected identifiers in excerpts and reports.

## What not to assume

Do not assume source uniqueness, referential integrity, stable ordering, complete history, UTC, non-null keys, warehouse optimizer behavior, acceptable cost, metric definitions, or that passing syntax means correct analytics.
