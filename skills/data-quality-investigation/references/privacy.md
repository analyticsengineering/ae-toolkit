# Privacy and Connection Policy

## Local-first baseline

- Prefer local files, user-pasted snippets, repository metadata, and local tooling.
- Minimize data: inspect only what is necessary and favor schemas, statistics, and sampled/redacted values over raw rows.
- Treat credentials, tokens, connection strings, customer data, employee data, and unreleased business metrics as sensitive.
- Never place secrets in prompts, logs, generated files, shell history, URLs, or reports.

## Database posture

Start with analysis, not execution. Review SQL, schemas, manifests, query plans, and existing artifacts locally. For an explicitly approved connection, use metadata and bounded read-only queries first. V1 does not execute DDL, DML, grants, exports, unbounded scans, or production changes.

## Connected Advanced gate

A connected action is allowed only after all of these steps:

1. The user explicitly requests the connected action; never infer consent from a local command.
2. Authenticate through the configured provider without exposing credentials.
3. Identify the destination, permissions, operation, and exact content to be transmitted.
4. Redact secrets and unnecessary sensitive values.
5. Show the user a content preview and risks.
6. Obtain explicit approval for that preview.
7. Use least privilege, smallest scope, and read-only access whenever possible.
8. Report what was accessed or sent and verify the result.

If any gate fails, remain local and explain the limitation. Free behavior never requires, discovers, authenticates to, or calls MCP.

## Learning and assessment

Read `.ae/exercise.json` when present. In Assessment mode, do not expose answers, provide a replacement solution, or edit the learner's submission. Grading is read-only on its first pass.

## Product boundary

This toolkit covers analytics engineering: SQL, data quality, analytical models, dbt, requirements, warehouses, and data/API pipelines. Decline frontend, generic backend, SEO, DevOps, and general application work; redirect to an appropriate tool.
