# Contributing

Thanks for improving Analytics Engineering Toolkit.

## Principles

Every change should preserve these guarantees:

- every workflow works locally, with no account, server, or network connection;
- the toolkit ships no MCP server and no code that opens a network connection;
- workspace transfer, database access, and course submission are never automatic;
- connected actions have a specific preview and explicit approval;
- destructive or mutating database execution remains unsupported;
- Work, Learn, and Assessment behavior stays distinct, and a local self-check is never presented as an official grade;
- anonymous telemetry remains zero.

Keep workflow guidance evidence-based. Separate observed facts, defensible inferences, assumptions, and checks that still need execution.

## Set up a development install

Requirements:

- a current Cursor release with local plugin support;
- Python 3 for hooks and tests, 3.9 or newer;
- Git.

From the repository root:

```bash
mkdir -p ~/.cursor/plugins/local
rsync -a --exclude '.git' ./ ~/.cursor/plugins/local/analytics-engineering-toolkit/
```

The install directory uses the plugin name `analytics-engineering-toolkit`, which differs from the repository name `ae-toolkit`.

Use a copy, not a symlink, which Cursor can skip without an error. Restart Cursor or run **Developer: Reload Window**, then open **Customize** and verify the plugin components. [docs/INSTALL.md](docs/INSTALL.md) covers the other hosts and troubleshooting.

## Repository layout

- `.cursor-plugin/plugin.json` — Cursor Plugin manifest.
- `src/skills/` — focused analytics workflows; edit skills here.
- `skills/` — generated self-contained copies for skills-only installers. Never edit by hand.
- `commands/` — agent-executable command entry points.
- `rules/` and `agents/` — persistent and delegated guidance.
- `hooks/` — deterministic shell, MCP, and published-model gates.
- `scripts/` — read-only inspectors, target generation, and installation tooling.
- `tests/` — deterministic policy, structure, and fixture tests.
- `docs/` — installation, dbt compatibility, evaluation, and marketplace documentation.

## Make a change

1. Open an issue or focused proposal for material product or policy changes.
2. Keep changes small and scoped to one behavior.
3. Update tests for changes to commands, hooks, mode behavior, payload approval, or failure handling.
4. Update `README.md`, `PRIVACY.md`, or `SECURITY.md` when user-facing boundaries change.
5. Add a concise entry to `CHANGELOG.md`.
6. Test with no MCP server configured, and with the dbt MCP server when a change touches the MCP gate.

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

### Adding a skill

Prefer improving an existing skill. A new skill earns its place when it covers analytics-engineering work no current skill handles, not when it restates something a capable model already does. Before proposing one:

1. Write it under `src/skills/<name>/SKILL.md`, with `name` matching the folder and a description that says when it applies, within 1024 characters.
2. Run `python3 scripts/build_targets.py` to regenerate the root `skills/` and `dist/` copies. Never edit those by hand.
3. Add a workflow-contract test in `tests/` for the behavior that matters most, such as what it must refuse, when it must stop, or what evidence it must cite.
4. Describe a general professional practice. Guidance that names one repository's tables or reproduces one example's answer makes the toolkit worse elsewhere.

## Reproducing a problem without exposing data

The best reproduction is a small synthetic repository: a few models, YAML files, and docs with invented names and values that still show the mistake. If you must start from a real project, replace table, column, and business names, remove row-level data and credentials, and keep only the files the agent read. Never attach real `profiles.yml` files, warehouse logs containing credentials, or compiled SQL that embeds sensitive literals.

## Behavioral evaluation

Maintainers evaluate workflow behavior against a separate private suite, so its
prompts, expected findings, holdouts, and scoring controls cannot leak into the
guidance they test. [docs/EVALUATION.md](docs/EVALUATION.md) explains the
method and the latest results. Public contributions do not require access to
that system. Every change must still describe a general professional practice
rather than a fixture-specific answer, and maintainers may run additional
private checks before accepting behavior changes.

## Good first issues

Issues labelled `good first issue` are scoped so they need no private infrastructure. Typical examples:

- a dbt v2 feature listed as not yet supported in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md), such as interpreting `dbt check` results;
- a warehouse CLI or launcher the safety gate does not yet recognize, with test cases for the forms it must deny, hold, or allow;
- a dialect difference a skill gets wrong, with a minimal fixture;
- clearer doctor output for a misconfiguration you hit.

## Support and compatibility policy

- The latest release is supported. Security fixes are not backported to earlier releases.
- dbt v1 (Core) and dbt v2 are supported as described in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md). A feature is listed as supported only when tests exercise it.
- Python 3.9 and newer on macOS and Linux are supported. Windows is experimental.
- Cursor, VS Code, Google Antigravity, and Agent Skills hosts are supported as described in [docs/INSTALL.md](docs/INSTALL.md). Host behavior changes without notice, so a new host version that breaks loading is treated as a bug.

## Privacy review

Any new connected payload field requires:

1. a clear purpose and data-minimization rationale;
2. inclusion in the pre-send preview;
3. explicit approval before transfer;
4. documentation under the exact data classes in `PRIVACY.md`;
5. tests proving there is no automatic or background send;
6. safe offline behavior.

The toolkit does not submit course work. A change that would send it anywhere is a product decision, not a contribution.

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
3. sample the local skills and `/ae-validate` planning with no MCP server configured;
4. verify a dbt MCP warehouse tool, if you use one, asks before it runs;
5. verify cancellation sends nothing;
6. verify destructive database operations are denied;
7. verify approved read-only database operations still require an approved local/development target;
8. verify malformed `.ae/exercise.json` fails visibly and no course work is submitted.

If a helper is added under `scripts/`, document its prerequisites and run it from the plugin root. Tests must not require production credentials or a network connection.

## Pull requests

Include:

- the problem and intended user outcome;
- the components and policy boundaries affected;
- test commands and results;
- local/offline behavior;
- screenshots or sample transcripts only when scrubbed of secrets and sensitive data;
- documentation and changelog updates.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
