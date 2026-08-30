---
name: ae-dbt-health
description: Assess local dbt project health across structure, dependencies, tests, documentation, and operational risk.
---
# Assess dbt Project Health

Apply the `dbt-health` skill workflow and the `senior-ae-reviewer` agent perspective.

## Execution boundary

This is a free local workflow. Use local project files and existing artifacts only. Never require or call MCP, connect to a warehouse, or run dbt by default.

## Workflow

1. Confirm project root, dbt version and adapter from local files, requested scope, and mode. Read `.ae/exercise.json` if present.
2. Run `python3 ".agents/ae-toolkit/scripts/inspect_dbt.py" <project-root>` when Python is available. Treat its current artifact-presence result as authoritative unless an exact file-existence check proves otherwise. Never cite artifact or runtime metadata remembered from another run.
3. Inspect `dbt_project.yml`, only the artifacts confirmed present, schema YAML, models, macros, snapshots, and tests. Inspect sources, staging/intermediate/marts, `ref`/`source` use, YAML and documentation coverage, uniqueness assumptions, incremental `unique_key`, packages, materializations, repeated SQL, direct raw-source access (including intentional singular-test access), coupling, and naming.
4. Use existing artifacts first. Run parse, compile, test, build, or any other dbt command only after a separate explicit request and target review.
5. Identify stale artifacts, cycles, untested critical paths, contract drift, fragile macros, full-refresh risk, and costly model patterns.
6. In Assessment mode, do not repair or complete the project. In Learn mode, explain why each health signal matters.

## Output

Return `# dbt Project Health` with: Health summary; Architecture; Testing; Documentation; Incremental/Snapshot risk; Dependency risks; Potential anti-patterns; Top 5 improvements.
