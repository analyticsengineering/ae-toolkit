---
name: ae-validate
description: Plan and run the smallest approval-gated dbt validation for changed or named resources.
---
# Validate dbt Work

Apply the `validate-dbt` skill. Default to Work mode without asking the user to name a mode.

## Execution boundary

This is a free local workflow. Never require or call MCP.

Inspect and plan statically first. Preview the exact selector, explicit local/development target, command, and side effects before requesting approval for warehouse-capable dbt execution. Never use a production-like target, global selector, or `--full-refresh`.

If a failure requires editing an existing file, show the diff and blast radius and obtain approval before applying it. Re-plan and revalidate only the affected scope.
