---
name: migration-plan
description: Plans analytical migrations and intentional contract changes with compatibility, phased cutover, validation, ownership, and rollback. Use when changing grain, rows, columns, types, meanings, keys, metric semantics, materialization, or a published consumer interface—including a column rename that cannot move atomically; use refactor-model for contract-preserving rewrites and rename-model for coordinated internal name-only changes.
---

# Migration Plan

Turn an intentional analytical contract change into a staged, reversible delivery plan.

## When to use

- Change grain, row population, schema, types, nullability, keys, meanings, units, or time semantics.
- Replace a model, metric, source, semantic object, or materialization with incompatible behavior.
- Coordinate dual-publish, backfill, consumer migration, cutover, deprecation, and rollback.
- Produce a plan; implementation is a separately approved workflow.

## Mode and context

Read `.ae/exercise.json` when present and honor its mode and constraints. Otherwise default silently to **Work**. In Learn mode, teach trade-offs without taking decisions away from the learner. In Assessment mode, evaluate the submitted plan without completing or editing it.

Obtain the current and target contracts, business reason, owners, critical consumers, acceptable compatibility window, freshness promise, and deployment constraints. Ask one decisive question when breaking-change acceptance, grain, metric meaning, freshness, or timing genuinely remains unresolved.

## Procedure

1. Establish repository conventions first. Read `.ae/project.yml` when present; otherwise run `python3 ".github/ae-toolkit/scripts/infer_conventions.py" <project-root> --json`. Record adapter, transformation tool, naming, versioning, contract, test, and deployment patterns with evidence strength.
2. Read current definitions, configuration, documentation, tests, direct lineage, metrics, semantic objects, BI artifacts, orchestration, and existing migration patterns.
3. State current and target contracts side by side in prose, covering:
   - row population, grain, and keys;
   - columns, types, nullability, meanings, units, and time anchors;
   - materialization, history, freshness, access, and operational behavior;
   - consumer-facing names and physical relations.
4. Produce an explicit contract delta. Every changed invariant needs a business reason, affected consumers, acceptance criterion, and owner.
5. Trace downstream blast radius across models, tests, exposures, metrics, semantic and BI layers, exports, schedules, grants, monitors, and known external consumers. State search scope and gaps.
6. Select a compatibility approach based on evidence: versioned model, dual-publish, compatibility view, additive transition, translation layer, coordinated flag day, or another repository-supported pattern. Explain why it fits and when it ends.
7. Divide work into phases with entry and exit criteria:
   - prepare target contract and tests;
   - build or backfill safely;
   - validate old versus new where comparison is meaningful;
   - migrate consumers in dependency order;
   - cut over reads and operations;
   - observe a defined stabilization window;
   - deprecate and remove compatibility assets.
8. Define rollback for each irreversible boundary. Name the trigger, decision owner, latest safe rollback point, retained old asset or state, and restoration steps.
9. Address data-state transitions: history scope, backfill boundaries, late data, deletes, duplicates, schema evolution, cost, and reconciliation. Do not assert values without local evidence.
10. Assign each action an owner, dependency, verification, stop condition, and evidence artifact. Mark external actions as proposals only.
11. Before editing or deleting any existing file, show an exact diff or change preview, state blast radius across downstream models, tests, exposures, BI artifacts, operations, and data state, and obtain explicit approval. A plan does not itself authorize implementation.
12. Re-check that cutover, compatibility removal, and rollback can be understood and executed independently.

## Decision gates

- Contract and acceptance criteria approved.
- Target can coexist safely with current state, or a justified coordinated cutover exists.
- Backfill and validation scope have bounded cost and explicit ownership.
- Critical consumers have migration and sign-off criteria.
- Rollback remains possible through the stabilization window.
- Compatibility removal requires evidence that old consumers are gone.

## Evidence required

Cite files and exact expressions for current behavior, dependency paths, and repository precedents. Label target behavior supplied by stakeholders separately from inferred implementation details.

Every actionable finding includes severity and confidence plus **Evidence**, **Risk**, **Recommendation**, and **Verification**. Recompute and state denominators for any consumer counts or rollout percentages.

## Failure modes

- Calling a breaking change a refactor or rename.
- Listing implementation tasks without defining current and target contracts.
- Treating dual-publish as permanent instead of giving removal criteria.
- Scheduling cutover before backfill reconciliation or consumer sign-off.
- Naming rollback without preserving the old relation, data, code, or route.
- Assuming all consumers are repository-visible or deploy together.
- Proposing warehouse-specific behavior unsupported by repository evidence.
- Editing files or executing migration steps while producing the plan.

## Output contract

Return `# Migration Plan` with: Executive decision; Current contract; Target contract; Contract delta; Evidence and unknowns; Consumer blast radius; Compatibility strategy; Phased cutover; Backfill and reconciliation; Rollback matrix; Ownership and decision gates; Verification; Approval-required implementation changes; Open questions.

For each phase state prerequisites, actions, owner, evidence produced, success criteria, rollback trigger, and next gate. If no genuine question remains, say so rather than inventing one.

## Verification

- Trace every contract delta to at least one acceptance criterion.
- Confirm each critical consumer appears in a migration phase or is explicitly unknown.
- Confirm compatibility assets have owners, deadlines, and removal checks.
- Walk rollback backward from every cutover boundary and identify lost-state risks.
- Propose bounded comparison queries and targeted build or consumer checks, but do not execute them.
- State which runtime, warehouse, BI, and operational evidence remains unavailable.

## Safety

- Local-only: use repository files, local static tools, and existing artifacts.
- Never call MCP, execute dbt, query a warehouse, run pipelines, or perform the migration.
- Never issue DDL or DML, mutate grants, post external changes, or expose sensitive values.
- New plan artifacts may be additive; list every path created.
- Existing-file edits, deletions, and renames always require preview, blast-radius disclosure, and explicit approval immediately before the change.

## What not to assume

Do not assume backward compatibility, complete lineage, unlimited backfill capacity, stable source history, atomic deployment, consumer readiness, retained rollback state, identical old/new populations, or that passing tests proves business acceptance.
