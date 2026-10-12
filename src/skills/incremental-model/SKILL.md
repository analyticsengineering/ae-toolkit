---
name: incremental-model
description: Designs, reviews, or safely proposes an incremental analytical model with correct unique keys, late-data handling, lookback boundaries, schema evolution, idempotency, and warehouse-portable strategy. Use for new or existing incremental models, backfills, merge or overwrite logic, or full-refresh risk; use build-model when incremental state is not central.
---

# Incremental Model

Design or review incremental state transitions so repeated and delayed inputs produce correct analytical output.

## First decision: are lateness and deletes known?

Settle both before writing anything. Read the source's documentation and the project's variables.

**Lateness.** If the source can change or add rows for periods already loaded (late delivery, corrections, in-place updates), find the file and line that states how far back that happens for this source: a lateness variable, a documented delivery or correction window, or a comparable model reading the same source.

- Found: cite it and reference it with `var()` when it is a variable.
- Not found: the response is `# Lateness Window Needed` and no file is written, `dbt_project.yml` included. Ask the one question, and say what a short window, a long window, or "unbounded" would each mean for the design. A window documented for another source, a consumer's reporting period, a typical value, or a variable you would add yourself is not evidence, including when the request calls it the standard; say what the documented window actually covers.

**Deletes.** If the source documentation says the source applies deletes (a replica, CDC, a mirror of an application database) find the file and line that says whether rows in already-loaded periods are hard-deleted, soft-deleted with a flag, or never deleted.

- Found: design for it and cite it (a soft-delete flag filtered or carried; "never deleted" quoted).
- Not found: the response is `# Delete Behaviour Needed` (or one combined pause with the lateness question) and no file is written. An `updated_at` watermark finds changed rows; a deleted row has no row left to carry a new `updated_at`, so the destination keeps it forever. Ask whether rows are deleted, and say what each answer means: never (watermark design holds), soft (filter the flag), hard (periodic full rebuild of affected periods, or a delete feed).

An `updated_at` column, however reliable, settles neither question on its own: it says which rows changed, never whether rows vanish or how far back changes reach. Settle both from documentation before writing. If you would list hard deletes or late changes under Remaining uncertainty, you are in the pause branch: write no file and ask instead.

## When to use

- Design a new incremental model or convert an existing model to incremental materialization.
- Review merge, append, delete-and-insert, partition-overwrite, or equivalent state logic.
- Diagnose static risks involving late data, reprocessing windows, schema changes, backfills, or full refresh.
- Do not use when materialization state is incidental to an ordinary model build.

## Mode and context

Read `.ae/exercise.json` when present and honor its mode and constraints. Otherwise default silently to **Work**. In Learn mode, use progressive hints. In Assessment mode, evaluate the submission without editing or constructing the answer.

Obtain the target model, business grain, update and delete behavior, event and ingestion timestamps, expected lateness, history requirement, current materialization, and stated freshness promise. Ask one focused question when a correctness-critical runtime fact remains genuinely undecidable after inspecting repository evidence and authoritative local documentation. In particular, never guess whether existing rows can change or disappear, which timestamp advances on a correction, or how late changes can arrive.

## Procedure

1. Establish repository conventions first. Read `.ae/project.yml` when present; otherwise run `python3 "${CURSOR_PLUGIN_ROOT}/scripts/infer_conventions.py" <project-root> --json`. Record adapter and source, transformation tool, incremental strategies, configuration layout, macros, tests, and SQL style with evidence strength.
2. Read the complete model, inherited project configuration, direct inputs, keys, tests, snapshots, macros, hooks, and comparable incremental models. Never copy a strategy merely because it is common on another warehouse.
3. State the target grain and candidate `unique_key`. Require a stable, non-null key at that grain; for a composite key, use the repository's established implementation rather than introducing new hashing. A `unique_key` named in the request does not settle the key. Check the documentation first: when the model's description or a key column's description states a grain that its tests or SQL contradict, write nothing and ask which grain the model should have, even when the SQL, tests, and source agree with each other. Only when the documentation agrees with the SQL and tests, and the requested key is coarser than the key they establish, use the established key and say why: a merge on the coarser key collapses rows.
4. Classify source change behavior:
   - append-only or mutable;
   - in-order or late-arriving;
   - hard deletes, soft deletes, or no deletes;
   - corrections to old event time;
   - duplicate delivery and replay behavior.
5. Separate event time, source-updated time, and ingestion time. Choose a watermark only when repository or requirement evidence shows it detects every relevant change.
6. Derive the incremental boundary and lookback from the stated lateness or observed repository policy. When the project already defines that policy as a variable or config (for example a `*_late_arrival_days` or `*_lookback_*` var), reference it with `var()` rather than copying its value. Explain inclusive versus exclusive comparison, null handling, time zone, precision, and first-run behavior. Never invent an arbitrary lookback. Filter the input on the same expression that produces the destination's time key (the macro, time-zone conversion, or truncation that computes the date or period column), compared as the same type, so the window always covers whole destination periods. A raw timestamp compared with a converted or truncated key leaves the oldest rebuilt period partial, and a merge then replaces a complete row with part of it. Another model's filter is precedent only when its time key is computed the same way.
7. Choose a strategy supported by both adapter evidence and repository precedent. Evaluate key matching, destination pruning, source filtering, partition replacement, update semantics, and delete propagation. A source being append-only does not make the destination append-only: an aggregate whose periods can still receive late or re-sent rows changes rows it has already written, so `append` either duplicates or understates those periods, or must withhold the newest periods, which removes rows consumers receive today. When a requested strategy cannot keep the output correct and complete, implement the conversion with the strategy that can (preferring the one the project already uses), and say in the summary why the requested one was not used.
8. Prove idempotency by tracing an identical batch twice and a corrected late row once. Describe the expected destination state, not only whether SQL compiles.
9. Evaluate schema evolution: added, removed, renamed, reordered, widened, or narrowed columns; contract enforcement; repository precedent for `on_schema_change`; target synchronization; historical defaults; and downstream compatibility.
10. Evaluate full-refresh and backfill risk: history availability, scan and write scope, table replacement, grants or metadata, downtime, non-reproducible sources, and divergence from incremental logic.
11. Check inherited partition, cluster, sort, strategy, and unique-key settings against actual model columns and the selected adapter.
12. Define targeted tests for key uniqueness and non-nullness, duplicate replay, late updates, boundary timestamps, deletes, schema change, empty batches, first run, and incremental-versus-full equivalence where valid.
13. For a review, report evidence-backed findings without editing. For a design or implementation request, propose the smallest configuration and SQL changes.
14. A request to make a model incremental authorizes the conversion, including on a published model: its columns, types, and grain stay the same, so consumers receive the same table. The exception is lateness. When the source can change rows already loaded and nothing in the repository says how far back those changes land for this source (a lateness variable, a documented delivery or correction window, a comparable model reading the same source), the window is the open correctness-critical fact: write no files, ask that one question, and say what each answer would mean for the design. A window documented for a different source is not evidence for this one, even when the request calls it the standard, and neither is a consumer's reporting period or a typical value; say what the documented window covers and ask. Otherwise, write the change in this turn without asking for a second approval, then name the consumers and the late-data boundary in the summary. Preview and obtain approval only before changing grain, columns, or meaning, proposing an operation that rewrites existing stored state (a backfill, a delete, a table replacement), deleting or renaming files, or broadening scope. The first build after the change is a full build; say so rather than treating it as a gate.
15. Update the model's YAML description to say it is incremental, name the unique key, and state the lookback and what happens to data that arrives later than it, so a reader of the docs knows the table's freshness and correction behavior.
16. Apply only authorized changes and repeat the static state-transition analysis.

## Correctness invariants

- One destination row, or the explicitly documented count, exists per business grain.
- Reprocessing the same source interval does not change the result.
- Every update that may arrive late eventually enters the processing window.
- Boundary rows are neither skipped nor duplicated by timestamp comparison.
- Every destination period the window touches is rebuilt from all of its input rows.
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
- Treating an `updated_at` watermark as safe over a source that applies deletes, when nothing says whether rows are deleted.
- Building the model and then naming hard deletes, a needed periodic full refresh, or an unknown lateness as remaining uncertainty or a deploy note. Those are the questions; they come before any file.
- Using append for mutable data or ignoring hard deletes.
- Using append for an aggregate because its source is append-only, or holding back recent periods so append looks safe.
- Assuming `merge`, partition overwrite, or schema-sync options are portable.
- Filtering both source and destination in a way that cannot match older changed rows.
- Treating successful incremental runs as proof that full refresh is safe.
- Letting directory-level configuration name columns absent from the model.
- Changing a published contract, rewriting stored state, or expanding scope before preview, blast-radius disclosure, and approval.
- Stopping to ask before a requested conversion when grain and columns are preserved, or leaving the documentation describing a full rebuild.
- Hardcoding a lookback the project already defines as a variable.
- Converting with a lookback chosen for convenience, borrowed from another source's documented window, or matched to a dashboard's reporting period when nothing states how late this source's changes land.
- Filtering on a raw timestamp when the key is a date computed from it in another time zone or grain, or copying a neighbouring model's filter whose key is computed differently.

## Output contract

When the lateness window is not stated for this source, return `# Lateness Window Needed` with: the question; what the source documentation says about late or corrected rows, cited; any nearby window and what it actually covers; what each answer would mean for the design; and, last, one direct question for the requester. This is a complete response. When delete behaviour is the open fact, use `# Delete Behaviour Needed` with the same parts; when both are open, ask both in one pause.

For implementation, return `# Incremental Model` with: Changed; Why, including grain, unique key, the lateness evidence and the delete evidence, each by file and line (a document that says the source applies deletes is not evidence that rows are never deleted), watermark/lookback, and adapter-supported strategy; Verified, including idempotency and late-data checks; Remaining uncertainty. For a review or risky migration, add evidence-backed findings, stored-state/full-refresh risk, blast radius, and approval gates.

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
- Explicitly requested reversible edits, including the requested conversion itself, may proceed when the contract is preserved. Operations that rewrite existing state, contract changes, renames, deletions, and scope expansion require preview, blast-radius disclosure, and approval.

## What not to assume

Do not assume sources are append-only, update timestamps advance, lateness is bounded, unique keys are unique, merges delete absent rows, schema synchronization is safe, full refresh can reproduce history, or warehouse strategies share semantics.
