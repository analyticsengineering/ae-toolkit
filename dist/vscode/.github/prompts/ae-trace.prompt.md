---
description: Trace a column, metric, or business figure back to its source and explain what it actually measures.
agent: agent
---
# Trace a Figure

Apply the `trace-lineage` skill workflow. Answer what the figure measures; do not convert the trace into a review of the models it passes through.

## Execution boundary

This is a free local workflow. Use local project files only. Never require or call MCP, connect to a warehouse, or run dbt.

## Workflow

1. Confirm the project root, the figure to trace, where the requester met it, and mode. Read `.ae/exercise.json` if present.
2. Run `python3 ".github/ae-toolkit/scripts/inspect_dbt.py" <project-root>` to inventory models, sources, and documentation before searching.
3. Search for every definition of the name across models, macros, tests, exposures, metrics, semantic models, and BI artifacts. Report all of them; more than one definition is a finding.
4. Walk upstream through `ref` and `source` calls, recording the expression, filters, and joins at each hop, and stop at the source table.
5. Walk downstream to every consumer, and state which directories and file types were searched and which could not be.
6. Reconstruct what the figure measures in business terms, including every predicate that narrows the population.
7. Apply the semantic checks across the whole chain: inconsistent time anchors between combined facts, population drift, duplicate definitions, grain changes, unit or currency drift, and null handling.
8. Separate what the files establish from what only a warehouse could confirm.
9. This workflow writes nothing. Propose any repair as a separate change requiring approval.

## Output

Return `# Lineage Trace` with: What it measures; Definition site; Calculation chain; Upstream sources; Downstream consumers; Semantic risks; What the files cannot confirm.
