---
name: source-setup
description: Defines and reviews dbt source declarations from repository evidence. Use when adding a source, source table, source-column metadata, loader or freshness configuration, quoting, or source-level tests; when replacing a raw relation with source(); or when build-model needs an undeclared upstream source.
---

# Source Setup

Declare external relations as sources without inventing contracts the repository or request does not establish.

## When to use

- Add or review dbt source, table, or source-column declarations.
- Add loader, loaded-at, freshness, quoting, or source-level test configuration supported by local evidence.
- Replace a direct raw relation reference with `source()` when that edit is explicitly approved.
- When `build-model` discovers an undeclared upstream relation, perform this source-discovery work automatically; users do not need to invoke another skill.
- Do not use for model descriptions, model tests, or structural YAML cleanup unless those domains are independently triggered.

## Mode and conventions

Read `.ae/exercise.json` when present and honor its mode, constraints, rubric, allowed tools, and artifacts. Otherwise use a user-requested mode; if none is requested, silently use **Work**.

- **Work:** prepare source declarations and authorized changes.
- **Learn:** use progressively stronger hints and preserve learner agency.
- **Assessment:** evaluate submitted declarations read-only without supplying replacements or editing them.

Read `.ae/project.yml` first. Human-edited values are authoritative. If it is absent, run `python3 ".github/ae-toolkit/scripts/infer_conventions.py" <project-root> --json`; inspect representative source YAML and `dbt_project.yml` directly. Apply strong conventions silently, state weak assumptions, ask only about genuine splits, and choose a labeled defensible default when evidence is absent.

## Procedure

1. Identify the dbt project root and the exact external relations requested. Stop if no dbt project or relation identity can be established locally.
2. Inspect existing source declarations, naming, YAML placement, schema/database patterns, quoting, freshness, tests, and model references. Treat `loaded_at_field` and freshness thresholds as source/table contracts, not global house conventions; borrow them only from the same ingestion system or domain when evidence establishes that relationship.
3. Search for duplicate logical or physical relations before proposing a new source. Reuse an existing declaration when it names the same relation.
4. Derive source, table, and column names from the request and repository evidence. Do not infer columns from intuition.
5. Add descriptions, freshness, `loaded_at_field`, quoting, or tests only when local configuration, contracts, or neighboring sources justify them. Keep business promises such as freshness explicitly sourced.
6. Validate every proposed `source()` call against the declared source and table names and identify models affected by a rename or replacement.
7. If staging models are requested, compose with `build-model` and hand off the resolved `source()` names, relation grain, and evidenced columns; do not make the user start another workflow.
8. Apply explicitly requested, reversible source-YAML and staging-reference edits without asking for a second approval. Preview and ask before a rename, deletion, contract change, or broader edit outside the requested scope.
9. If composing with `build-model`, return control with the resolved `source()` name, declaration path, evidence, and any risk gate; do not redo model SQL, documentation, or model-test work.

## Evidence required

Cite the local file or user-provided requirement establishing each physical relation, identifier, column, freshness promise, and test. Report convention support counts where inference provides them. Mark unresolved database/schema values and unverified columns as assumptions, not facts.

## Failure modes

- Creating a duplicate source for a relation already declared.
- Guessing database, schema, table, columns, or freshness from common practice.
- Adding freshness without a supported load timestamp or availability promise.
- Treating model tests or descriptions as source setup merely because they share YAML.
- Renaming a source without tracing downstream `source()` calls.
- Editing outside the requested source scope or changing a contract without preview and approval.
- Running dbt or querying a warehouse to compensate for missing local evidence.

## Output contract

For ordinary creation or editing, return `# Source Setup` with: Changed; Why; Verified; Remaining uncertainty. Include paths and the source names created or updated. Use formal severity and evidence findings only when reviewing source quality or reporting a material risk.

## Verification

- Parse the proposed YAML with an available local parser.
- Confirm source and table names are unique in project-owned declarations.
- Confirm every proposed `source()` reference matches a declaration exactly.
- Confirm configured loaded-at, freshness, quoting, and test keys follow the repository's dbt version and demonstrated syntax.
- Propose the smallest relevant parse or build command without running dbt.
- State what remains unverifiable without warehouse access.

## Safety/privacy

- Local Basic only: read local files and use static local tools; never call MCP, execute dbt, or contact a warehouse.
- Never include credentials, connection strings, profile targets, PII, or sampled rows.
- New files are additive and may be created; list every path.
- Explicitly requested reversible source-YAML edits may proceed; renames, deletions, contract changes, and scope expansion require preview, blast radius, and approval.
- Never perform destructive version-control or database operations.
