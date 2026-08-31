---
name: ae-validate
description: Plan and run the smallest approval-gated dbt validation for changed or named resources.
---

# Validate dbt Work

Apply the `validate-dbt` skill. Default to Work mode without asking the user to name a mode.

## Execution boundary

This is a free local workflow. Never require or call MCP.

Inspect and plan statically first. Preview the exact selector, explicit local/development target, command, and side effects before requesting approval for warehouse-capable dbt execution. Never use a production-like target, global selector, or `--full-refresh`.

If the request explicitly includes fixing failures, apply reversible project-owned SQL/YAML/test repairs without a second approval. Otherwise preview the repair because validation alone does not authorize edits. Contract changes, renames, deletions, and scope expansion still require approval. Re-plan and revalidate only the affected scope.
