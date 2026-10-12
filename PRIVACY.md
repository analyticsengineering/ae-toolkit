# Privacy

Last updated: October 9, 2026

Analytics Engineering Toolkit runs locally and ships no server. This document separates behavior provided by the plugin from behavior provided by Cursor or another host, a selected model provider, a database client, or an MCP server you add yourself.

## Commitment

- **Anonymous telemetry: zero.** The toolkit contains no anonymous product analytics, usage beacons, tracking pixels, crash reporting, or background telemetry.
- **Uploads to AnalyticsEngineering.com: zero.** The toolkit has no remote service and configures no MCP server. Installing it does not upload a workspace, scan a repository in the background, or submit course work, and no shipped code opens a network connection.
- **Product feedback is user-carried.** The project profile workflow can surface where its own inference disagreed with a human correction, because that is the most useful defect report this project can receive. It is written into the local output only. The plugin never transmits it, never stores it for later delivery, and never asks for permission to send it; a person who chooses to share one copies it themselves, having read it.
- **Connected actions require preview and explicit approval.** When you ask for work against a warehouse, API, or other service you have configured, you see what will run or be sent, and why, before each request.
- **Database access is not implicit.** A request to review or propose SQL is not approval to execute it.

Your host and the AI/model provider you select may process prompts and project context according to their own settings and policies. That processing is outside this plugin's control. "Local" means the workflow ships with this plugin and needs no external service; it does not promise that the model runs on-device.

## Local workflows

Every shipped skill, command, and agent—including project profiling, model/source/test/documentation work, lineage, validation planning, review, profiling, requirements, semantic/BI modeling, refactoring, investigations, and the course commands—operates on context made available in the active editor session.

Depending on the request and host permissions, local context can include:

- prompt text and follow-up answers;
- files, selections, diffs, directory structure, and repository metadata;
- SQL, dbt models, schemas, tests, documentation, logs, query plans, and sample data the user selects;
- locally generated findings, plans, proposed queries, and patches;
- command output from actions the user permits.

The plugin does not independently retain or transmit this context. Files and generated artifacts remain where the user or the host writes them. Avoid including secrets or sensitive row-level values; use redacted, sampled, synthetic, or aggregated evidence.

## MCP servers you add

The toolkit configures no MCP server. If you add one, such as the dbt MCP server, the host dials it and that server's own terms apply. The toolkit's MCP gate holds dbt MCP tools that execute against the warehouse or change state on the dbt platform (`build`, `run`, `test`, `show`, `execute_sql`, `query_metrics`, job triggers, and similar) for your approval, the same way it holds `dbt run` in the shell, and refuses a request in which it detects a credential. Tools that read project metadata pass through. Calls to other servers are not governed by the toolkit.

There is no approval inferred from installing or enabling the plugin, configuring an MCP server, opening a repository, entering Learn or Assessment mode, or having `.ae/exercise.json` in a workspace.

## Course work

The course commands read `.ae/exercise.json` and the learner's files locally. Hints, self-checks, diagnostics, and capstone checks never submit, record, or send anything. A local self-check is a practice signal against the rubric the exercise supplies; it is never an official grade, acceptance, or receipt.

## Database and warehouse data

The plugin should prefer repository metadata, schemas, aggregates, bounded samples, and synthetic fixtures over raw production rows. It must never automatically execute a query or forward query results.

The toolkit denies destructive and mutating database statements. Recognized `SELECT` or `EXPLAIN` commands require explicit approval and confirmation of an approved local or development target.

The local dbt validation workflow performs static planning first. It may run one bounded dbt command only after showing the selector, explicit local/development target, and likely side effects and receiving approval. It never infers a target, validates against production, runs globally, or uses `--full-refresh`.

Do not provide production credentials to the plugin. Use least-privilege, read-only, non-production credentials when database access is explicitly needed.

## Retention and deletion

The toolkit stores nothing outside your workspace. For local files and conversations, use the deletion and retention controls of the filesystem, source-control host, your editor, and the selected model provider. For an MCP server or service you configure, consult its operator's terms.

## Sensitive data

Do not send secrets, access tokens, private keys, passwords, connection strings, raw personal data, payment data, health data, or regulated production records. Redact protected identifiers and use the minimum evidence necessary. If sensitive data is discovered in a proposed payload, stop and narrow or sanitize it before requesting approval.

## Changes and questions

Material privacy changes will be documented in [CHANGELOG.md](CHANGELOG.md). Privacy or security concerns can be reported using [SECURITY.md](SECURITY.md).
