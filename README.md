# Analytics Engineering Toolkit

> Make your AI coding agent think like an analytics engineer.

Install the toolkit, open a data project, and work normally. Ask for a model, source, test, metric, refactor, investigation, or review in plain language. The toolkit gives Cursor, VS Code, and Google Antigravity repository-aware analytics-engineering workflows, deterministic inspection, validation planning, and safety guardrails.

The local toolkit is genuinely useful without an AnalyticsEngineering.com account or remote service. It reads the repository before asking questions, learns the team's naming, testing, documentation, SQL, warehouse, semantic-layer, and BI conventions, then applies them. It asks only about what files cannot establish: intended grain, business meaning, promised freshness, or acceptance of a breaking change.

## Product boundary

The toolkit helps inspect, explain, review, and plan analytics work. It is analysis-first:

- it covers SQL, profiling, cleaning, modeling, metrics, dbt, data quality, APIs, data pipelines, analytics requirements, and AI-assisted data work;
- it explicitly excludes frontend development, website building, SEO, generic backend or app development, and generic DevOps;
- it reviews SQL and pull requests, profiles supplied data, assesses dbt projects and data models, and investigates data-quality incidents;
- it can propose queries, patches, tests, and runbooks, but execution or edits remain visible and user-controlled;
- it does not replace a warehouse, dbt, an orchestrator, source control, a BI tool, or a database administrator;
- it is not a credential manager, background monitoring agent, hosted query engine, or guarantee that analytics output is correct;
- it does not silently connect to a database, run expensive queries, mutate production data, submit coursework, or upload workspace content;
- its findings depend on the files, metadata, business definitions, and runtime evidence available in the current Cursor session.

The plugin includes configuration for the optional remote MCP endpoint at `https://mcp.analyticsengineering.com/mcp`. This repository does **not** implement or bundle that server. Connected features are structurally ready but are available only when that endpoint is deployed, reachable, supports the requested tool, and implements OAuth discovery/dynamic client registration compatible with Cursor. No client secret is embedded. Local workflows continue to work when it is absent.

## Install locally

Cursor's current local-development mechanism loads plugins from `~/.cursor/plugins/local`.

Clone this repository first:

```bash
git clone https://github.com/analyticsengineering/ae-toolkit.git
```

The Cursor plugin name is `analytics-engineering-toolkit`, so the install directory keeps that name even though the repository is `ae-toolkit`.

Install it as a real directory, from the repository root:

```bash
mkdir -p ~/.cursor/plugins/local
rsync -a --exclude '.git' ./ ~/.cursor/plugins/local/analytics-engineering-toolkit/
```

If that destination already exists, inspect it before replacing it. Do not create a second plugin with the same name.

A copy does not track the repository, so re-run that command after each change, then reload the window.

**Do not use a symlink**, even though Cursor's own documentation suggests one for faster iteration. Cursor 3.8.11 refuses to load a local plugin whose symlink resolves outside the plugins folder, and the refusal is quiet: the plugin is simply absent, and the reload still reports `failures=0`. The reason appears only in the log, as

```text
loadUserLocalPlugin analytics-engineering-toolkit rejected: symlink target
  <your clone> is outside ~/.cursor/plugins/local
```

The log prints both paths in full; search for `rejected: symlink target`.

If the toolkit does not appear after installing, read that log first: **Output** panel (`Cmd+Shift+U` on macOS), then choose the **Cursor Plugins** channel.

Then:

1. Restart Cursor, or run **Developer: Reload Window** from the Command Palette.
2. Open **Customize** in the Cursor sidebar.
3. Confirm **Analytics Engineering Toolkit** is present and its expected skills, rules, commands, hooks, and MCP server are visible.
4. Enable only the components and scopes you intend to use.

On Teams and Enterprise, local imports may be disabled by an administrator. The setting is **Allow Local Plugin Imports** under **Dashboard → Settings → Security & Identity → Marketplace and Plugins**; it is off by default on Enterprise. An installed marketplace plugin with the same name takes precedence over a local copy.

See Cursor's [Plugins guide](https://cursor.com/docs/plugins) and [Plugins reference](https://cursor.com/docs/reference/plugins).

## Install in VS Code or Antigravity

The toolkit is authored once, as a Cursor plugin, and generated into layouts for other hosts. The workflows, the rules, and the safety gates are the same files reaching the same verdicts; only the packaging differs, because skills are an open standard and both hosts read them.

Build the targets, then install one into your repository:

```bash
python3 scripts/build_targets.py
python3 scripts/install_target.py --host vscode --workspace /path/to/your/repo
```

Use `--host antigravity` for Antigravity, and add `--dry-run` to see what would change first.

The installer does three things a plain copy does not. It merges rather than overwrites, so an `AGENTS.md`, hook configuration, or MCP configuration you already maintain keeps its contents; the toolkit's rules land inside a marked block that a reinstall updates in place. It rewrites hook commands to absolute paths, which matters most on Antigravity, where a relative path is resolved against the directory the session started in and a hook that fails to launch does not block the call it was meant to gate. Finally it runs a command the gate is required to refuse and reports whether it was refused, so you learn at install time whether enforcement actually works on your machine.

What lands in your repository:

| | VS Code | Antigravity |
|---|---|---|
| Skills | `.github/skills/` | `.agents/skills/` |
| Commands | `.github/prompts/` as prompt files | `.agents/skills/` as skills |
| Agents | `.github/agents/` | `.agents/agents/` |
| Rules | `AGENTS.md` | `AGENTS.md` |
| Safety gates | `.github/hooks/ae-toolkit.json` | `.agents/hooks.json` |
| Scripts and references | `.github/ae-toolkit/` | `.agents/ae-toolkit/` |
| MCP | `.vscode/mcp.json` | `.agents/mcp_config.json` |

Everything under `dist/` is generated. Edit the plugin source and rebuild; `python3 scripts/build_targets.py --check` fails if the two have diverged, and CI runs it, so a rule tightened for Cursor cannot stay loose on another host.

One difference is worth knowing. Cursor gives shell execution and MCP calls their own hook events, while VS Code and Antigravity route every tool through a single `PreToolUse` event. Both gates are registered on that one event and each stands aside for traffic that is not its own, so the behaviour matches Cursor even though the wiring does not.

## Quick start

Open a data project and ask for the outcome:

```text
Build a payment fact from stg_stripe_payments and stg_stripe_refunds.
```

```text
Add appropriate tests and business documentation to this model.
```

```text
Rename customer_type to customer_segment without breaking downstream users.
```

```text
Why is yesterday's paid revenue not ready yet?
```

Work is the default. You do not need to select a mode, agent, skill, or slash command. The toolkit profiles the repository when conventions matter and composes the necessary capabilities silently. Provide business meaning or intended grain when you know it; otherwise the toolkit asks one focused question only when repository evidence leaves a real ambiguity.

Convention inference is ephemeral by default. The toolkit reads `.ae/project.yml` when a team has chosen to keep one, but it never adds that file to an unrelated model, source, test, documentation, or review change. Persisting a shared profile is an explicit choice.

## What it handles

The toolkit supports the day-to-day model lifecycle: project conventions, sources, staging/intermediate/fact/dimension models, tests, documentation, YAML maintenance, incremental design, metrics, semantic layers, LookML and other detected BI layers, lineage, safe refactors and renames, migrations, freshness incidents, data quality, SQL and PR review, profiling, requirements, and API-to-analytics pipelines.

Slash commands remain optional aliases for power users and repeatable automation.

### Local command aliases

These do not require the AnalyticsEngineering.com MCP service:

| Command | Purpose |
| --- | --- |
| `/ae-learn` | Infer this repository's own conventions from its existing models and propose a project profile. |
| `/ae-build-model` | Build a model from existing upstream models, following the conventions the repository already demonstrates. |
| `/ae-trace` | Trace a column, metric, or figure back to its source and explain what it actually measures. |
| `/ae-review-sql` | Review SQL for correctness, grain, joins, performance, and production risks. |
| `/ae-profile-data` | Compute a local CSV, JSON, or JSONL profile, then interpret quality risks. |
| `/ae-review-model` | Review or propose a data model from a business use case and source evidence. |
| `/ae-dbt-health` | Review the actual dbt project without blindly running dbt. |
| `/ae-requirements` | Turn an ambiguous analytics request into definitions, assumptions, questions, and acceptance criteria. |
| `/ae-explain` | Explain selected SQL, Python, dbt, YAML, or pipeline code at a chosen level. |
| `/ae-validate` | Plan and run the smallest approval-gated dbt validation against an explicit local/development target. |

Local means the workflow instructions are shipped in this repository. Cursor itself may still use the AI provider and settings selected by the user; “local” does not mean the language model necessarily runs on-device.

### Optional connected and course workflows

The first five commands have useful local basic behavior; their advanced or authoritative behavior can be connected. `/ae-hint` and `/ae-grade` require an implemented remote course service to return a hint or grade.

| Command | Local/offline behavior | Optional or required connected behavior |
| --- | --- | --- |
| `/ae-debug` | Investigate a data-quality or metric incident from local code, logs, artifacts, and fixtures. | May add specifically approved external evidence. |
| `/ae-api-plan` | Design API-to-warehouse ingestion from local specifications and examples. | May inspect specifically approved external documentation or account context. |
| `/ae-pr-review` | Review a local analytics branch and diff. | May add specifically approved remote PR or proprietary rubric context. |
| `/ae-diagnostic` | Run a short, explicitly non-authoritative local sample or show login guidance. | Required for the authoritative cross-domain diagnostic. |
| `/ae-capstone-check` | Check local capstone readiness against supplied criteria; not a certificate decision. | May use separately approved external grading, catalog, or warehouse context. |
| `/ae-hint` | Validate and preview the active exercise context; it does not produce a local hint. | Required to request one server-policy-controlled progressive hint. |
| `/ae-grade` | Validate and preview the selected submission; it does not assign a local grade. | Required for authoritative rubric-based grading. |

Availability is conditional. A configured MCP entry is not proof that the remote server or any particular tool exists. If the endpoint is unavailable or lacks a capability, the plugin must say so, avoid claiming a connected result, and fall back to repository-based guidance when useful. It must not silently substitute a local answer for a server-authoritative assessment or submission.

## Work, Learn, and Assessment behavior

- **Work** is automatic for ordinary requests: concise production work and the smallest safe verification.
- **Learn** activates when you ask to be taught and uses explanations and progressive hints.
- **Assessment** activates in an assessment workspace or when you explicitly request evaluation without help; it does not complete or repair the submission.

For local workflows, the mode shapes the response but is not an access-control boundary. For connected course or assessment features, the remote server is authoritative for enrollment, exercise state, rubric, allowed help, attempt state, grading, and submission acceptance. A local file or prompt cannot override server policy. If local and server state conflict, stop and surface the conflict.

## Privacy and approval

V1 has **zero anonymous telemetry**. The plugin does not contain background analytics, tracking pixels, usage beacons, or automatic workspace uploads.

An explicit request to create or edit project-owned SQL, YAML, documentation, tests, or local analytics configuration authorizes the smallest reversible file changes needed; the IDE diff remains visible. Renames, deletions, breaking contracts, broad migrations, warehouse access, production actions, destructive operations, and external transmission retain preview or explicit-approval gates appropriate to their risk.

Local workflows use context the user makes available to Cursor. Connected use is opt-in: before any request, submission, database query, or MCP action, the agent must show a useful preview of the proposed scope and obtain explicit approval. Nothing is sent to the AnalyticsEngineering.com endpoint automatically.

Do not put credentials, tokens, production row-level data, personal data, or regulated data into prompts or examples. Review [PRIVACY.md](PRIVACY.md) for the exact connected data classes and course-submission policy.

## Examples

### Review a model without executing it

```text
Review @models/marts/fct_subscriptions.sql before I merge it.
Expected grain is subscription_id by valid_from.
Use the project schema and tests as evidence. Do not query the warehouse.
```

### Plan a bounded profile

```text
Teach me how to profile @samples/orders.csv.
Explain every check, avoid exposing raw customer values, and write results locally.
```

### Investigate an incident

```text
Paid conversions dropped after the latest deploy. Investigate why.
Correlate the dbt diff, tests, and lineage first. Preview any query before asking to run it.
```

### Check project health

```text
Assess the health of this dbt project.
Do not run dbt. Separate observed issues from checks that require execution.
```

## Course integration: `.ae/exercise.json`

A course workspace may include `.ae/exercise.json`. Treat it as exercise metadata and a pointer to the applicable instructions—not as permission to submit or reveal answers. The plugin should:

```json
{
  "exercise_id": "sql-fanout-001",
  "module_id": "sql-review",
  "lesson_id": "join-cardinality",
  "mode": "Learn",
  "skills": ["sql-review", "grain-analysis"],
  "course_url": "https://analyticsengineering.com/courses/sql-review/join-cardinality"
}
```

1. read the file only when the user opens the course workspace or invokes a course-aware workflow;
2. validate and report unsupported or malformed fields rather than guessing;
3. use local exercise context for offline guidance where the exercise permits it;
4. ask before contacting the remote MCP endpoint;
5. defer to server-authoritative mode, rubric, attempt, entitlement, and submission state;
6. preview the exact files, answers, identifiers, and evidence proposed for submission and require explicit approval;
7. preserve local work and fail gracefully when offline.

No course submission is automatic. The presence of `.ae/exercise.json`, an MCP configuration, or Assessment mode is not consent to upload.

## Safety and database posture

V1 is deliberately conservative:

- `DROP` and `TRUNCATE` database statements are denied.
- `INSERT`, `UPDATE`, `DELETE`, `MERGE`, and `ALTER` database statements are denied.
- `SELECT` and `EXPLAIN` through recognized database clients require explicit approval and confirmation of an approved local or development target.
- warehouse-executing dbt commands require approval and target review.
- automated validation rejects production-like targets, unbounded selectors, and `--full-refresh`.
- proposed SQL is text for human review, not authorization to execute it.

Hooks are defense in depth, not a security sandbox. Review every command and use least-privilege, non-production credentials. See [SECURITY.md](SECURITY.md).

## Scripts

The plugin's executable support is standard-library Python and intentionally read-only:

Python 3 is required for deterministic inspectors, hook execution, and tests. The plugin never installs Python or packages. If `python3` is unavailable, free prompt workflows can still reason from supplied local context, but they must not guess computed statistics; security-critical hooks fail closed until Python is available or the user disables those hooks.

- `python3 scripts/inspect_repo.py [path] [--pretty]` detects analytics-engineering technologies and repository structure.
- `python3 scripts/inspect_git.py [path] [--base BRANCH] [--pretty]` reports branch, status, and diffs using read-only Git commands.
- `python3 scripts/inspect_dbt.py [path] [--pretty]` statically inspects a dbt project without executing dbt.
- `python3 scripts/infer_conventions.py [path] [--json] [--write] [--force]` derives the project's naming, key, test, documentation, and SQL conventions, each with the count of models supporting and contradicting it. `--write` creates `.ae/project.yml` and refuses to replace an existing profile without `--force`.
- `python3 scripts/plan_dbt_validation.py [path] [--model NAME] [--target TARGET] [--intent static|compile|test|run|build] [--pretty]` plans a bounded dbt selector and command sequence without executing it.
- `python3 scripts/interpret_dbt_results.py [--run-results PATH] [--log PATH] [--pretty]` classifies current dbt failures from local artifacts and redacts secret-shaped values.
- `python3 scripts/profile_dataset.py PATH [--format csv|json|jsonl|ndjson] [--encoding NAME] [--delimiter CHAR] [--pretty]` deterministically profiles a local dataset.
- `python3 scripts/redact_secrets.py ...` performs best-effort detection/redaction before optional cloud transmission.
- `hooks/safety_gate.py` classifies shell and database commands before execution.
- `hooks/cloud_data_gate.py` validates the AnalyticsEngineering.com host, blocks likely secrets, previews payload fields and approximate bytes, and asks before connected transfer.
- `hooks/host_contract.py` translates a gate decision into each host's hook reply shape. It holds no rules of its own, so every host reaches the same verdict from the same code.
- `python3 scripts/build_targets.py [--check] [--target NAME]` generates the VS Code and Antigravity layouts from the plugin source. `--check` reports drift instead of writing, and runs in CI.
- `python3 scripts/install_target.py --host NAME --workspace PATH [--dry-run]` installs a generated target, merging shared files rather than overwriting them, rewriting hook commands to absolute paths, and verifying that the safety gate denies a command it must deny.

Both gates accept `--host cursor|vscode|antigravity`, defaulting to `cursor`. An unrecognised host exits non-zero without printing a decision, so a misconfiguration cannot be mistaken for approval.

Run scripts from the plugin root so relative paths resolve correctly. Use `python3`; no script should require production credentials. Read a script before running it, especially after pulling changes.

## Testing

From the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Also perform the local Cursor smoke test:

1. install as a real directory under `~/.cursor/plugins/local`;
2. reload Cursor;
3. verify expected components in Customize;
4. invoke each local workflow on a fixture without enabling the remote MCP server;
5. confirm write/destructive commands are denied and approved read-only actions ask first;
6. disable or disconnect the remote endpoint and confirm local workflows still degrade gracefully.

Tests validate deterministic policy and structure; they do not prove analytics correctness or remote service availability. Behavioral evaluation is maintained separately so private prompts, expected findings, holdouts, and scoring controls cannot contaminate the guidance they test. Those internal results inform releases, but the evaluation assets are not part of this distributable plugin.

### Validating skills against the published standard

The test suite enforces the Agent Skills rules that matter most, because a skill whose `name` disagrees with its directory, whose name contains characters outside lowercase letters, numbers, and hyphens, or whose description runs past 1024 characters is dropped without an error message. The workflow would simply be missing.

Those rules are encoded in our own tests rather than pulled in as a dependency, since the toolkit ships standard-library Python only and the reference library is explicitly not meant for production use. To cross-check them against the reference implementation:

```bash
git clone --depth 1 https://github.com/agentskills/agentskills.git /tmp/agentskills
python3 -m venv /tmp/srvenv && /tmp/srvenv/bin/pip install -e /tmp/agentskills/skills-ref
for skill in skills/*/ dist/*/.*/skills/*/; do /tmp/srvenv/bin/skills-ref validate "$skill"; done
```

All authored and generated skills currently pass, and all sit inside the standard's recommended budgets of 500 lines and roughly 5000 tokens.

### Host smoke test

The generated layouts are checked against each host's published documentation and by the tests above. What those cannot show is whether the editor actually discovers the files, because that needs the editor. This is the checklist, and it takes a few minutes per host.

Install into a scratch repository rather than a real one, so a mistake costs nothing:

```bash
python3 scripts/build_targets.py
mkdir -p /tmp/ae-smoke && cd /tmp/ae-smoke && git init
python3 /path/to/ae-toolkit/scripts/install_target.py --host vscode --workspace .
```

The installer already reports whether the safety gate refuses a command it must refuse. If that line says FAILED, stop there: the rest of the checks are meaningless without it.

**In VS Code**, open the scratch repository and confirm four things:

1. **Chat: Open Customizations** lists the twenty-five skills, four agents, and seventeen prompts. A skill that loaded is present here; a skill that failed to load is silently absent, so a short list is the failure signal.
2. Right-click the Chat view and select **Diagnostics**. It should report no load errors.
3. Type `/` in chat. The skills and prompts should appear as slash commands; run `/ae-learn` against a dbt project and confirm it reports conventions rather than asking you to describe them.
4. Ask the agent to run `psql -c "drop table orders"`. The hook must deny it. This is the check that matters most, because it is the one that fails silently if the hook is misconfigured.

**In Antigravity**, repeat with `--host antigravity`, then confirm the skills appear, run `/hooks` in the CLI to see `ae-toolkit-safety` registered, and repeat the destructive-command check. Do that last check **from a subdirectory** as well as from the repository root: Antigravity resolves relative hook paths against the session directory, and a hook that fails to launch does not block the call. The installer writes absolute paths precisely to prevent this, and a subdirectory session is what would expose a regression.

If a skill is missing, the cause is almost always its `name` disagreeing with its directory name, which both hosts treat as a reason to skip the file without saying so. `python3 tests/run_tests.py` checks that before you get this far.

## Troubleshooting

### Plugin does not appear

- Confirm the final path is `~/.cursor/plugins/local/analytics-engineering-toolkit/.cursor-plugin/plugin.json`.
- Confirm the install is a real directory rather than a symlink.
- Open the **Output** panel (`Cmd+Shift+U` on macOS) and select **Cursor Plugins**; search for `rejected: symlink target` or another load warning.
- Restart Cursor or run **Developer: Reload Window**.
- Open Customize and check the correct user/workspace scope.
- Ask your administrator whether local plugin imports are allowed.
- Remove naming conflicts; a marketplace install with the same name wins.

### A workflow is missing

Re-copy and reload after changing the source repository. In Customize, confirm the skill is enabled. Use the exact slash name listed above.

### Connected tools are unavailable

This is expected when `https://mcp.analyticsengineering.com/mcp` is not deployed, reachable, authenticated, or does not advertise the requested tool. Continue with a local workflow where appropriate. Do not treat a local fallback as an official grade, submission, entitlement decision, or server result.

### A command was blocked

Read the safety-gate reason. Destructive database writes are intentionally unsupported in V1. For approved read-only work, confirm the target is local/development, narrow the query, and approve only the displayed command.

### Course state conflicts

Do not edit `.ae/exercise.json` to bypass server state. Reconnect and reconcile with the authoritative course service; preserve local work until the conflict is resolved.

## Limitations

- Connected and course features depend on a separately operated service that is not implemented in this repository.
- Static review cannot observe warehouse data, query plans, runtime behavior, hidden business rules, or production configuration unless supplied.
- Dialect and adapter coverage is best effort.
- Safety classification is conservative and pattern-based; it can block safe commands or miss obfuscated risk.
- Offline course guidance cannot grade, authorize attempts, verify enrollment, or submit work.
- Cursor and the selected model/provider have their own data handling, network, and retention controls.
- V1 has no anonymous telemetry, background monitoring, automatic remediation, or production write support.

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), keep free workflows usable without the remote service, preserve risk-based preview-and-approval boundaries, add tests for behavior changes, and update [CHANGELOG.md](CHANGELOG.md).

Security reports should follow [SECURITY.md](SECURITY.md), not a public issue.

## License

MIT © 2026 AnalyticsEngineering.com. See [LICENSE](LICENSE).
