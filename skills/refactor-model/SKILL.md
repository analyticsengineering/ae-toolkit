---
name: refactor-model
description: Refactors an existing analytical model while preserving its published output contract. Use when asked to simplify, reorganize, modularize, or improve model SQL without changing its grain, rows, columns, names, types, meanings, keys, or downstream behavior; use migration-plan instead when any contract change is intentional.
---

# Refactor Model

Improve an analytical model's implementation without changing what consumers receive.

## When to use

- Simplify CTEs, joins, filters, calculations, or repeated SQL in an existing model.
- Extract reusable logic or align a model with demonstrated repository conventions.
- Review whether a proposed refactor preserves the output contract.
- Do not use for model renames, intentional schema changes, or migrations.

## Mode and context

Read `.ae/exercise.json` when present and honor its mode and constraints. Otherwise default silently to **Work**. In Learn mode, use progressive hints. In Assessment mode, evaluate the submission without editing it or supplying a replacement.

Obtain the target model, requested improvement, project root, and any declared compatibility constraints. Treat missing business meaning, grain, or consumer guarantees as unknowns rather than inventing them.

## Procedure

1. Establish repository conventions first. Read `.ae/project.yml` when present; otherwise run the local static convention-inference script. Record the adapter, transformation tool, model layout, SQL style, tests, and materialization patterns with their evidence strength.
2. Read the complete model, its configuration, documentation, tests, macros, direct inputs, and relevant project configuration.
3. Define the current output contract from evidence:
   - row population and grain;
   - column names, order when contractually relevant, types, nullability, and meanings;
   - keys, accepted values, time semantics, units, and materialization behavior;
   - freshness, performance, and side effects only when documented or tested.
4. Trace downstream lineage across models, tests, exposures, metrics, semantic definitions, BI artifacts, and orchestration references. List searched locations and exclusions.
5. Compare the proposed implementation with the current one through each CTE. Check joins, fanout, filters, three-valued logic, aggregations, windows, deduplication order, casts, time zones, and incremental boundaries.
6. Reject the refactor framing if preserving the contract is impossible. Route a name-only change to `rename-model` and an intentional contract change to `migration-plan`.
7. Design the smallest change that removes the identified complexity while preserving every established invariant. Use only constructs and macros supported by repository and adapter evidence.
8. When the user explicitly requested this contract-preserving refactor, apply the smallest reversible edits without asking for a second approval and show the resulting diff. If contract preservation is uncertain, the scope expands, or a rename/deletion is needed, preview the change and blast radius and obtain approval first.
9. Change only files required by the request. New additive files may be created, but list every path.
10. Re-read the before and after logic against every invariant and report anything that remains unverified.

## Preservation checks

- The same logical input produces the same row set at the same grain.
- Joins retain the same cardinality and unmatched-row behavior.
- Filters retain boundaries, null behavior, and time anchors.
- Aggregations, windows, ties, and deduplication remain deterministic.
- Columns retain names, meanings, types, nullability, units, and defaults.
- Materialization, hooks, grants, tags, contracts, and incremental state retain behavior.

## Evidence required

Cite files and exact expressions for the current contract, each downstream dependency, and every proposed equivalence. Label facts as **Observed**, consequences as **Inferred**, and runtime questions as **Unknown**.

Every actionable finding includes severity and confidence plus **Evidence**, **Risk**, **Recommendation**, and **Verification**. Use the repository severity model and avoid presenting stylistic preference as a defect.

## Failure modes

- Calling changed rows, grain, schema, meaning, or materialization a refactor.
- Optimizing a fragment without reading the whole model and direct dependencies.
- Assuming algebraically similar SQL has identical null, duplicate, or time behavior.
- Removing a column because no SQL model references it while ignoring BI consumers.
- Introducing an adapter-specific function absent from the repository.
- Editing outside the explicit request or changing an uncertain contract without approval.
- Claiming equivalence from compilation or formatting alone.

## Output contract

For an explicitly requested contract-preserving refactor, return `# Refactor` with: Changed; Why, including the preservation argument; Verified; Remaining uncertainty.

When contract preservation is uncertain or the work crosses a rename, deletion, or scope boundary, return `# Refactor Proposal` instead with: Goal; Current output contract; Downstream blast radius; Proposed diff; Failure risks; Verification plan; Approval needed.

After an approved implementation, return `# Refactor Result` with: Files changed; Contract preserved; Evidence; Verification performed; Residual uncertainty; Follow-up commands not run.

If evidence shows a contract change, return `# Not a Refactor` and identify the changed invariant plus the appropriate rename or migration workflow.

## Verification

- Perform static before/after tracing for grain, row population, columns, and semantics.
- Check that references, selected columns, tests, and configurations still resolve locally.
- Prefer existing fixtures, compiled artifacts, or saved bounded outputs when already present.
- Propose the smallest targeted compile, build, or equivalence checks, but do not execute them.
- Never claim data equivalence without result evidence; state the exact runtime check needed.

## Safety

- Local-only: use repository files, local static tools, and existing artifacts.
- Never call MCP, execute dbt, query a warehouse, or run pipelines.
- Never expose credentials, connection strings, PII, or unnecessary row-level values.
- Never execute mutating SQL or destructive version-control commands.
- New files may be created without approval and every path must be reported.
- Explicitly requested reversible refactor edits may proceed after contract preservation is established. Renames, deletions, uncertain contracts, and scope expansion require preview, blast-radius disclosure, and approval.

## What not to assume

Do not assume undocumented keys are unique, tests fully define the contract, output order is irrelevant, downstream searches cover proprietary BI formats, materialization changes are harmless, or matching column names imply matching meaning.
