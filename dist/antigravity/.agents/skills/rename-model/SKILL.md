---
name: rename-model
description: Coordinates renaming an analytical model and every repository reference to it while preserving its data contract. Use when asked to rename a model, relation, source, metric, or model file and update refs, tests, docs, exposures, semantic or BI references, orchestration, and compatibility aliases; use migration-plan when behavior or schema will also change.
---

# Rename Model

Change a model's identity without silently changing the data it publishes or leaving consumers behind.

## When to use

- Rename a model, source, relation, metric, semantic object, or model file.
- Inventory and update references coordinated across analytics artifacts.
- Design a temporary alias or deprecation period for consumers that cannot move atomically.
- Do not combine a rename with intentional grain, row, schema, or meaning changes.

## Mode and context

Read `.ae/exercise.json` when present and honor its mode and constraints. Otherwise default silently to **Work**. In Learn mode, explain the dependency search progressively. In Assessment mode, evaluate the submitted rename without editing or completing it.

Obtain the old identity, intended new identity, project root, desired compatibility window when one is stated, and any known external consumers. Ask only whether a breaking rename is acceptable and on what timeline when repository evidence cannot answer it.

## Procedure

1. Establish repository conventions first. Read `.ae/project.yml` when present; otherwise run `python3 ".agents/ae-toolkit/scripts/infer_conventions.py" <project-root> --json`. Record naming, model paths, YAML layout, alias patterns, adapter, and transformation tool with evidence strength.
2. Read the model, configuration, documentation, tests, macros, and project configuration that establish its logical name, physical relation, aliases, schemas, and database.
3. Confirm the rename does not also change grain, rows, columns, types, meanings, keys, materialization, or freshness. Route intentional contract changes to `migration-plan`.
4. Trace upstream and downstream identities using both logical and physical names. Search:
   - model and source references, SQL strings, macros, and package-qualified references;
   - YAML tests, contracts, documentation, groups, access, versions, and selectors;
   - exposures, metrics, semantic models, saved queries, LookML, and other BI artifacts;
   - orchestration, freshness checks, grants, monitoring, exports, seeds, snapshots, Python, and other scripts.
5. List every searched directory and file type. Mark external systems or formats that local files cannot verify rather than treating them as clear.
6. Classify consumers as atomic, compatibility-dependent, external/unknown, or generated. Never edit generated artifacts or distribution copies unless explicitly requested as source files.
7. Choose a coordination strategy supported by repository and platform evidence:
   - atomic rename when every consumer can move together;
   - temporary compatibility alias/view when old and new names must coexist;
   - versioned or staged migration when ownership or release timing differs.
8. Define ordering, ownership, deprecation date, monitoring signals, and removal criteria. Account for case-only renames and physical aliases on case-folding filesystems or warehouses.
9. Before editing, deleting, or renaming any existing file, show the exact path map and reference diff, disclose the blast radius across models, tests, exposures, metrics, BI artifacts, schedules, grants, and external consumers, and obtain explicit approval. Stop before writing until approval arrives.
10. After approval, apply only the approved path and reference changes. List each newly created path and each old path removed.
11. Re-run the same static searches against old and new identities, then report unresolved consumers and compatibility obligations.

## Evidence required

Cite the definition of the old identity, the convention supporting the new identity, and every discovered reference by file and exact token. Distinguish **Observed** repository consumers, **Inferred** physical dependencies, and **Unknown** external consumers.

Every actionable finding includes severity and confidence plus **Evidence**, **Risk**, **Recommendation**, and **Verification**.

## Failure modes

- Renaming only the SQL file or only the `ref` calls.
- Assuming the logical model name equals its physical relation name.
- Missing string-based SQL, selectors, grants, monitors, exports, or BI references.
- Mixing cleanup or schema changes into a supposedly name-only operation.
- Dropping the old identity before compatibility consumers have moved.
- Keeping an alias indefinitely without owner, deadline, or removal criteria.
- Treating generated manifests or distribution copies as source-of-truth files.
- Editing first and asking for approval afterward.

## Output contract

Before approval, return `# Rename Plan` with: Old and new identities; Contract-preservation check; Convention evidence; Reference inventory; External unknowns; Compatibility strategy; Ordered path and reference diff; Blast radius; Verification plan; Approval needed.

After an approved rename, return `# Rename Result` with: Paths created, changed, renamed, and removed; References updated; Compatibility retained; Static verification; Unresolved external consumers; Follow-up commands not run.

If the request also changes behavior or schema, return `# Migration Required` and name each changed contract element.

## Verification

- Search the full declared scope for the old logical name, relation name, aliases, and qualified forms.
- Confirm every new reference resolves to an existing local definition.
- Confirm tests, contracts, documentation, selectors, exposures, and semantic objects use the intended identity.
- Check that temporary aliases preserve columns, grain, permissions intent, and deprecation ownership.
- Propose the smallest targeted compile, build, or consumer validation commands, but do not execute them.
- Never claim external consumers are migrated without direct local evidence.

## Safety

- Local-only: use repository files, local static tools, and existing artifacts.
- Never call MCP, execute dbt, query a warehouse, or run pipelines.
- Never issue DDL, mutate production relations, or alter grants.
- Never expose credentials, PII, or sensitive values found in configuration.
- New files may be created without approval and every path must be reported.
- Existing-file edits, deletions, and renames always require preview, blast-radius disclosure, and explicit approval immediately before the change.

## What not to assume

Do not assume references use only `ref`, filenames define relation names, aliases are portable, external BI is searchable, consumers deploy atomically, grants follow a renamed relation, or a case-only rename behaves consistently across platforms.
