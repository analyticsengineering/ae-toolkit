# Privacy

Last updated: August 31, 2026

Analytics Engineering Toolkit is local-first. This document separates behavior provided by the plugin from behavior provided by Cursor, a selected model provider, a database client, or the optional AnalyticsEngineering.com MCP service.

## V1 commitment

- **Anonymous telemetry: zero.** V1 contains no anonymous product analytics, usage beacons, tracking pixels, crash reporting, or background telemetry.
- **Automatic AnalyticsEngineering.com uploads: zero.** Installing the plugin does not upload a workspace, scan a repository in the background, contact the optional MCP endpoint, or submit course work.
- **Product feedback is user-carried.** The project profile workflow can surface where its own inference disagreed with a human correction, because that is the most useful defect report this project can receive. It is written into the local output only. The plugin never transmits it, never stores it for later delivery, and never asks for permission to send it; a person who chooses to share one copies it themselves, having read it.
- **Connected actions require preview and explicit approval.** The user must see a meaningful description of what will be sent and why before each connected request or submission.
- **Database access is not implicit.** A request to review or propose SQL is not approval to execute it.

Cursor and the user-selected AI/model provider may process prompts and project context according to their own settings and policies. That platform processing is outside this plugin's control. “Local workflow” means the workflow ships with this plugin and does not require the AnalyticsEngineering.com MCP service; it does not promise that the model runs on-device.

## Local workflows

The shipped local skills—including project profiling, model/source/test/documentation work, lineage, validation planning, review, profiling, requirements, semantic/BI modeling, refactoring, and investigations—operate on context made available in the active editor session. Their local command aliases never require or call the AnalyticsEngineering.com MCP service.

Depending on the request and Cursor permissions, local context can include:

- prompt text and follow-up answers;
- files, selections, diffs, directory structure, and repository metadata;
- SQL, dbt models, schemas, tests, documentation, logs, query plans, and sample data the user selects;
- locally generated findings, plans, proposed queries, and patches;
- command output from actions the user permits.

The plugin does not independently retain or transmit this context to AnalyticsEngineering.com. Files and generated artifacts remain where the user or Cursor writes them. Avoid including secrets or sensitive row-level values; use redacted, sampled, synthetic, or aggregated evidence.

## Optional connected mode

The manifest can configure `https://mcp.analyticsengineering.com/mcp`. The server is separate from this repository and may not be implemented or available. A configured URL is structural readiness, not evidence that a remote capability exists.

Before any MCP request, the plugin must preview the purpose, destination, and applicable data classes. Only after explicit approval may the following exact classes be sent, and only to the extent needed for the approved action:

1. **Request content** — the user's approved prompt, question, selected mode, and requested operation.
2. **Selected project content** — specifically previewed file paths and excerpts, diffs, SQL or code, dbt configuration, documentation, schema or lineage excerpts, logs, query plans, and sample or aggregate data.
3. **Technical context** — SQL dialect, warehouse or dbt adapter type, tool/runtime versions, repository-relative identifiers, and non-secret error details needed to interpret the request.
4. **Generated work product** — specifically previewed findings, proposed requirements, pipeline designs, explanations, checks, answers, or other artifacts chosen for a connected operation.
5. **Course context** — course, lesson, exercise, attempt, or rubric identifiers read from approved workspace context such as `.ae/exercise.json`.
6. **Submission content** — the exact answer text, selected solution files or excerpts, test results, execution evidence, and learner notes shown in a submission preview.
7. **Account and authorization context** — credentials or account identifiers required by the service transport, if the user has configured them. Secrets must be handled by Cursor/service configuration and must not be copied into prompts, previews, logs, or repository files.

No other workspace content should be attached “just in case.” Approval for one request does not authorize later requests, broader files, database queries, or a course submission. The plugin must ask again when the scope or destination changes.

## Preview requirements

A connected preview should be specific enough to make an informed choice. It must identify:

- the destination (`https://mcp.analyticsengineering.com/mcp`);
- the operation or tool requested;
- the data classes above that apply;
- the named files, excerpts, identifiers, or generated artifacts in scope;
- whether personal, production, customer, or regulated data appears to be present;
- expected side effects, including whether the action is a course submission;
- a safer local or redacted alternative when one is practical.

There is no approval inferred from installing or enabling the plugin, configuring the MCP server, opening a repository, entering Learn or Assessment mode, or having `.ae/exercise.json` in a workspace.

## Course work and submissions

Course-aware behavior may read `.ae/exercise.json` locally when relevant. It must not treat that file as authorization to contact a server.

Before submission, show the exact exercise/attempt identifiers, solution files or answer text, test or execution evidence, and learner/account context proposed for transfer. Submit only after explicit approval. Drafting, saving, testing, and opening an exercise do not trigger a submission.

When connected, the course server is authoritative for enrollment, mode, rubric, allowed assistance, attempt state, grading, and receipt. When offline, the plugin can preserve local work and provide permitted local guidance, but it cannot claim to grade, accept, or record a submission.

## Database and warehouse data

The plugin should prefer repository metadata, schemas, aggregates, bounded samples, and synthetic fixtures over raw production rows. It must never automatically execute a query or forward query results.

V1 denies destructive and mutating database statements. Recognized `SELECT` or `EXPLAIN` commands require explicit approval and confirmation of an approved local or development target. Approval to execute a query is separate from approval to send its text or output to the MCP service.

The local dbt validation workflow performs static planning first. It may run one bounded dbt command only after showing the selector, explicit local/development target, and likely side effects and receiving approval. It never infers a target, validates against production, runs globally, or uses `--full-refresh`.

Do not provide production credentials to the plugin. Use least-privilege, read-only, non-production credentials when database access is explicitly needed.

## Retention and deletion

This repository does not implement the remote service and therefore cannot make a verified promise about server-side retention, access, deletion, residency, or subprocessors. Before using a connected feature with sensitive content, consult the privacy terms published by the operator of the active endpoint. If no applicable policy is available, do not send the content.

For local files and Cursor conversations, use the deletion and retention controls of the filesystem, source-control host, Cursor, and selected model provider.

## Offline behavior

If the optional endpoint is unavailable, the plugin should:

- clearly state that the connected operation did not occur;
- keep local workflows usable;
- preserve local course work;
- avoid retrying uploads in the background;
- avoid queueing submissions for later automatic delivery;
- never describe a local fallback as a server result, grade, or accepted submission.

## Sensitive data

Do not send secrets, access tokens, private keys, passwords, connection strings, raw personal data, payment data, health data, or regulated production records. Redact protected identifiers and use the minimum evidence necessary. If sensitive data is discovered in a proposed payload, stop and narrow or sanitize it before requesting approval.

## Changes and questions

Material privacy changes will be documented in [CHANGELOG.md](CHANGELOG.md). Privacy or security concerns can be reported using [SECURITY.md](SECURITY.md).
