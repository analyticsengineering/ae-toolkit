---
name: ae-diagnostic
description: Run a short local skills diagnostic across analytics-engineering domains and point to what to practise next.
---
# Analytics Engineering Diagnostic

Apply the `learning-coach` agent in Assessment mode. This runs locally, sends nothing anywhere, and its result is a practice signal, not a certification or official score.

## Workflow

1. Ask which domains to cover, defaulting to all: SQL; Modeling; dbt; Quality; Python/APIs; Engineering Workflow; AI Data Workflows.
2. Ask one or two short questions per domain, one at a time. Prefer questions grounded in the open repository when it has relevant models, and otherwise use small self-contained scenarios.
3. Do not give answers or hints while the diagnostic is running. Preserve the learner's answers exactly; do not repair them before evaluating.
4. Evaluate each answer for correctness first, then reasoning. Say when an answer is partly right and what part.
5. Never claim the result is official, and never present it as a grade.

## Output

Return `# Diagnostic` with:

- a first line stating this is a local practice diagnostic;
- per domain: strength, gap with the evidence from the learner's answer, and one next practice action;
- the two domains to work on first.
