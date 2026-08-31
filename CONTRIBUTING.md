# Contributing

Thanks for improving Analytics Engineering Toolkit.

## Principles

Every change should preserve these V1 guarantees:

- local skills remain genuinely useful without an AnalyticsEngineering.com account or server;
- connected capabilities are described as optional and conditional, never as available merely because an MCP URL is configured;
- workspace transfer, database access, and course submission are never automatic;
- connected actions have a specific preview and explicit approval;
- destructive or mutating database execution remains unsupported;
- Work, Learn, and Assessment behavior stays distinct, while connected server policy remains authoritative;
- anonymous telemetry remains zero.

Keep workflow guidance evidence-based. Separate observed facts, defensible inferences, assumptions, and checks that still need execution.

## Set up a development install

Requirements:

- a current Cursor release with local plugin support;
- Python 3 for hooks and tests;
- Git.

From the repository root:

```bash
mkdir -p ~/.cursor/plugins/local
rsync -a --exclude '.git' ./ ~/.cursor/plugins/local/analytics-engineering-toolkit/
```

The install directory uses the plugin name `analytics-engineering-toolkit`, which differs from the repository name `ae-toolkit`.

Do not use a symlink: Cursor 3.8.11 rejects a local plugin whose symlink resolves outside the plugins directory. Restart Cursor or run **Developer: Reload Window**, then open **Customize** and verify the plugin components. On managed Teams or Enterprise installations, an administrator must allow local plugin imports. See the [Cursor Plugins guide](https://cursor.com/docs/plugins).

## Repository layout

- `.cursor-plugin/plugin.json` — Cursor Plugin manifest.
- `skills/` — focused analytics workflows.
- `commands/` — agent-executable command entry points.
- `rules/` and `agents/` — persistent and delegated guidance.
- `hooks/` — deterministic safety and connected-data gates.
- `mcp.json` — optional remote MCP configuration.
- `scripts/` — read-only inspectors, target generation, and installation tooling.
- `tests/` — deterministic policy, structure, and fixture tests.
- `docs/` — release and marketplace documentation.

## Make a change

1. Open an issue or focused proposal for material product or policy changes.
2. Keep changes small and scoped to one behavior.
3. Update tests for changes to commands, hooks, mode behavior, payload approval, or failure handling.
4. Update `README.md`, `PRIVACY.md`, or `SECURITY.md` when user-facing boundaries change.
5. Add a concise entry to `CHANGELOG.md`.
6. Test with the remote MCP server disabled as well as with any explicitly supported connected test environment.

Do not add:

- anonymous telemetry or background uploads;
- credentials, private endpoints, production data, or real learner submissions;
- a hidden dependency on the optional server for a free workflow;
- instructions that bypass course mode, rubric, attempt, or entitlement policy;
- automatic query execution, course submission, or destructive database behavior;
- claims about remote tools, retention, or availability that are not implemented and verified.

## Skill and command quality

For each workflow:

- use a unique lowercase kebab-case name;
- state when it applies and what it excludes;
- request the minimum context needed;
- distinguish Work, Learn, and Assessment output;
- define evidence and output contracts;
- preview costly, connected, or side-effecting actions;
- degrade gracefully when evidence or the remote service is unavailable;
- avoid asserting that a check ran when it was only proposed.

Keep slash-command documentation synchronized with the actual skill/command surface.

## Behavioral evaluation

Maintainers evaluate workflow behavior against a separate private suite so its
prompts, expected findings, holdouts, and scoring controls cannot leak into the
guidance they test. Public contributions do not require access to that system.
Every change must still describe a general professional practice rather than a
fixture-specific answer, and maintainers may run additional private checks
before accepting behavior changes.

## Privacy review

Any new connected payload field requires:

1. a clear purpose and data-minimization rationale;
2. inclusion in the pre-send preview;
3. explicit approval before transfer;
4. documentation under the exact data classes in `PRIVACY.md`;
5. tests proving there is no automatic or background send;
6. safe offline behavior.

Course submissions require a separate, submission-specific approval even if earlier connected requests were approved.

## Security review

Changes to hooks, shell execution, MCP configuration, database behavior, authentication, or submission behavior need focused security tests. Safety hooks must fail closed on malformed input and must not be presented as a complete sandbox. Never weaken warehouse-level least privilege or environment separation.

Report suspected vulnerabilities privately under [SECURITY.md](SECURITY.md).

## Test

From the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Then smoke-test the local plugin:

1. reload Cursor;
2. verify the manifest and expected components in Customize;
3. sample the local skills and `/ae-validate` planning with the MCP endpoint unavailable;
4. verify connected requests show destination and payload scope before approval;
5. verify cancellation sends nothing;
6. verify destructive database operations are denied;
7. verify approved read-only database operations still require an approved local/development target;
8. verify malformed `.ae/exercise.json` fails visibly and no course work is submitted.

If a helper is added under `scripts/`, document its prerequisites and run it from the plugin root. Tests must not require production credentials or the live remote service.

## Pull requests

Include:

- the problem and intended user outcome;
- the components and policy boundaries affected;
- test commands and results;
- local/offline behavior;
- screenshots or sample transcripts only when scrubbed of secrets and sensitive data;
- documentation and changelog updates.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
