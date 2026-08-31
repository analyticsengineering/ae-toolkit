---
name: ae-build-model
description: Build a dbt model from existing upstream models using this repository's naming, key, testing, documentation, and SQL conventions.
---

# Build a Model

Apply the `build-model` skill workflow and the `senior-ae-reviewer` agent perspective.

## Execution boundary

This is a free local workflow. Use local project files only. Never require or call MCP, connect to a warehouse, or run dbt.

## Workflow

1. Confirm the project root, requested model, and upstream inputs. Read `.ae/exercise.json` if present; otherwise silently default to Work.
2. Load conventions from `.ae/project.yml`, or run `python3 "${CURSOR_PLUGIN_ROOT}/scripts/infer_conventions.py" <project-root> --json` when it is absent. Never ask for a convention the inference already supplies.
3. Run `python3 "${CURSOR_PLUGIN_ROOT}/scripts/inspect_dbt.py" <project-root>` to inventory models, sources, tests, and existing documentation.
4. Read every upstream model named in the request, plus its documented columns and tests, before selecting a single field.
5. Determine each input's grain and candidate keys, then determine the target grain. When two grains are genuinely plausible, stop and ask, presenting the candidates concretely and writing no model file. A request to create files does not settle the grain.
6. Identify fanout between inputs of different grain and resolve it in the SQL: omit the coarser measure, allocate it by a documented rule, or carry it on one row per coarser key. A warning beside an unchanged column is not a fix.
7. Write the model in the repository's SQL style, using its layer prefix, directory, materialization, and surrogate key implementation.
8. Document the model where this repository documents models, and add the tests it attaches to a primary key, plus any test a specific risk justifies.
9. Validate every `ref`, `source`, and selected column against files that exist in this project.
10. Read the `dbt_project.yml` block for the directory you are writing into. A new model inherits that materialization and its platform settings, so confirm any partition, cluster, sort, or incremental key names a column the model actually has, and override explicitly what does not fit. Overriding the materialization does not clear the rest of the block.
11. Create new files and apply explicitly requested reversible SQL/YAML/test/documentation edits directly. Preview and request approval only for contract changes, renames, deletions, or edits outside the requested scope.
12. In Assessment mode, do not write files. In Learn mode, explain each modeling decision as it is made.

## Output

When the grain is resolved, return `# Model Build` with: Changed; Why, including grain, inputs, keys, and conventions; Verified, including tests and static reference checks; Remaining uncertainty. Never print `Mode: Work` or internal skill routing.

When two grains survive, return `# Grain Decision Needed` instead, with: The question, naming both candidates; What each choice implies for the requested measures; Conventions already inferred, with support counts; Inputs and their keys; What will be built once the grain is chosen. Write no files in this branch.
