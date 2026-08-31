---
name: ae-validate
description: Plan and run the smallest approval-gated dbt validation for changed or named resources.
---
This is the `ae-validate` alias of the `validate-dbt` skill. Follow that skill's full procedure and output contract; the summary below orients the request and does not replace it.

# Validate dbt Work

Apply the `validate-dbt` skill. Default to Work mode without asking the user to name a mode.

## Execution boundary

This is a free local workflow. Never require or call MCP.

Inspect and plan statically first. Preview the exact selector, explicit local/development target, command, and side effects before requesting approval for warehouse-capable dbt execution. Never use a production-like target, global selector, or `--full-refresh`.

Use the planner's `recommended_intent` as a deterministic over-validation guard: metadata-only changes stay static, singular/model/source test changes stay on targeted `dbt test`, and source freshness changes stay on targeted `dbt source freshness`. Macro or project-config changes need explicit affected scope before warehouse work. Do not use `--allow-broader-intent` without explaining why broader warehouse work is necessary.

If the request explicitly includes fixing failures, apply reversible project-owned SQL/YAML/test repairs without a second approval. Otherwise preview the repair because validation alone does not authorize edits. Contract changes, renames, deletions, and scope expansion still require approval. Re-plan and revalidate only the affected scope.
