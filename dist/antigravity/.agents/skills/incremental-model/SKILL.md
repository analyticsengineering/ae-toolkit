---
name: incremental-model
description: Designs, reviews, or safely proposes an incremental analytical model with correct unique keys, late-data handling, lookback boundaries, schema evolution, idempotency, and warehouse-portable strategy. Use for new or existing incremental models, backfills, merge or overwrite logic, or full-refresh risk; use build-model when incremental state is not central.
---

# Incremental Model

Design or review incremental state transitions so repeated and delayed inputs produce correct analytical output.

## When to use

- Design a new incremental model or convert an existing model to incremental materialization.
- Review merge, append, delete-and-insert, partition-overwrite, or equivalent state logic.
- Diagnose static risks involving late data, reprocessing windows, schema changes, backfills, or full refresh.
- Do not use when materialization state is incidental to an ordinary model build.

## Mode and context

Read `.ae/exercise.json` when present and honor its mode and constraints. Otherwise default silently to **Work**. In Learn mode, use progressive hints. In Assessment mode, evaluate the submission without editing or constructing the answer.

Obtain the target model, business grain, update and delete behavior, event and ingestion timestamps, expected lateness, history requirement, current materialization, and stated freshness promise. Ask only when grain, business meaning, freshness, or acceptable breaking behavior remains genuinely undecidable.

## Procedure

1. Establish repository conventions first. Read `.ae/project.yml` when present; otherwise run the local static convention-inference script. Record adapter and source, transformation tool, incremental strategies, configuration layout, macros, tests, and SQL style with evidence strength.
2. Read the complete model, inherited project configuration, direct inputs, keys, tests, snapshots, macros, hooks, and comparable incremental models. Never copy a strategy merely because it is common on another warehouse.
3. State the target grain and candidate `unique_key`. Require a stable, non-null key at that grain; for a composite key, use the repository's established implementation rather than introducing new hashing.
4. Classify source change behavior:
   - append-only or mutable;
   - in-order or late-arriving;
   - hard deletes, soft deletes, or no deletes;
   - corrections to old event time;
   - duplicate delivery and replay behavior.
5. Separate event time, source-updated time, and ingestion time. Choose a watermark only when repository or requirement evidence shows it detects every relevant change.
6. Derive the incremental boundary and lookback from the stated lateness or observed repository policy. Explain inclusive versus exclusive comparison, null handling, time zone, precision, and first-run behavior. Never invent an arbitrary lookback.
7. Choose a strategy supported by both adapter evidence and repository precedent. Evaluate key matching, destination pruning, source filtering, partition replacement, update semantics, and delete propagation.
8. Prove idempotency by tracing an identical batch twice and a corrected late row once. Describe the expected destination state, not only whether SQL compiles.
9. Evaluate schema evolution: added, removed, renamed, reordered, widened, or narrowed columns; contract enforcement; repository precedent for `on_schema_change`; target synchronization; historical defaults; and downstream compatibility.
10. Evaluate full-refresh and backfill risk: history availability, scan and write scope, table replacement, grants or metadata, downtime, non-reproducible sources, and divergence from incremental logic.
11. Check inherited partition, cluster, sort, strategy, and unique-key settings against actual model columns and the selected adapter.
12. Define targeted tests for key uniqueness and non-nullness, duplicate replay, late updates, boundary timestamps, deletes, schema change, empty batches, first run, and incremental-versus-full equivalence where valid.
13. For a review, report evidence-backed findings without editing. For a design or implementation request, propose the smallest configuration and SQL changes.
14. Apply explicitly requested, reversible model/configuration edits without asking for a second approval when grain, published contract, and stored-state behavior are preserved. Preview and obtain approval before changing those invariants, rewriting state, deleting or renaming files, or broadening scope.
15. Apply only authorized changes and repeat the static state-transition analysis.

## Correctness invariants

- One destination row, or the explicitly documented count, exists per business grain.
- Reprocessing the same source interval does not change the result.
- Every update that may arrive late eventually enters the processing window.
- Boundary rows are neither skipped nor duplicated by timestamp comparison.
- Deletes follow an explicit policy rather than disappearing from consideration.
- Incremental and full-refresh logic intentionally converge, or their difference is documented.
- Schema changes cannot silently reinterpret historical rows.

## Evidence required

Cite the grain, unique-key support, source change signals, lateness requirement, strategy precedent, adapter evidence, and inherited configuration by file and exact setting or expression. Label unsupported runtime properties as **Unknown**.

Every actionable finding includes severity and confidence plus **Evidence**, **Risk**, **Recommendation**, and **Verification**.

## Failure modes

- Using `max(event_time)` when corrections retain old event timestamps.
- Choosing a unique key that is nullable, unstable, or coarser than the model grain.
- Applying a lookback with no lateness evidence or replay-safe merge behavior.
- Using append for mutable data or ignoring hard deletes.
- Assuming `merge`, partition overwrite, or schema-sync options are portable.
- Filtering both source and destination in a way that cannot match older changed rows.
- Treating successful incremental runs as proof that full refresh is safe.
- Letting directory-level configuration name columns absent from the model.
- Changing stored-state behavior, a published contract, or scope before preview, blast-radius disclosure, and approval.

## Output contract

For implementation, return `# Incremental Model` with: Changed; Why, including grain, unique key, watermark/lookback, and adapter-supported strategy; Verified, including idempotency and late-data checks; Remaining uncertainty. For a review or risky migration, add evidence-backed findings, stored-state/full-refresh risk, blast radius, and approval gates.

For reviews, order findings by severity. For implementations, report Changed, Why, Verified, and Remaining uncertainty. List every new path; stop only at the risk gates above.

## Verification

- Trace first run, empty batch, repeated batch, boundary timestamp, delayed correction, duplicate, and delete scenarios.
- Confirm strategy and configuration are supported by the inferred adapter and used locally.
- Confirm unique-key columns exist, align with grain, and have repository-backed tests.
- Compare incremental and full-refresh semantics statically across the entire model.
- Propose the smallest targeted fixtures, compile/build selection, bounded reconciliation queries, and rollback check, but do not execute them.
- State all runtime properties that local artifacts cannot establish.

## Safety

- Local-only: use repository files, local static tools, and existing artifacts.
- Never call MCP, execute dbt, query a warehouse, run a pipeline, or perform a full refresh.
- Never execute DDL or DML, mutate target state, or expose credentials and row-level sensitive data.
- New files may be created without approval and every path must be reported.
- Explicitly requested reversible edits may proceed when contract and stored-state behavior are preserved. State rewrites, contract changes, renames, deletions, and scope expansion require preview, blast-radius disclosure, and approval.

## What not to assume

Do not assume sources are append-only, update timestamps advance, lateness is bounded, unique keys are unique, merges delete absent rows, schema synchronization is safe, full refresh can reproduce history, or warehouse strategies share semantics.
