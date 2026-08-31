# Changelog

All notable changes to Analytics Engineering Toolkit are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Creation and editing workflows now report `Changed`, `Why`, `Verified`, and `Remaining uncertainty` instead of exposing Work mode or review-framework fields.
- Explicit requests authorize reversible project-owned SQL, YAML, documentation, test, and local analytics configuration edits. Renames, deletions, breaking contracts, broad migrations, infrastructure/data access, external transmission, and destructive actions retain risk-based gates.
- Convention inference is ephemeral by default; `.ae/project.yml` is persisted only when the user explicitly asks to save or share a project profile.

### Fixed

- Validation planning distinguishes formatting/comment, description-only, test-only, contract, rename/delete, and semantic/metric YAML changes so harmless metadata edits no longer select downstream models.
- Validation planning now recommends intent from the changed resource type and omits a broader warehouse command for metadata-only or test-only changes unless the caller explicitly overrides the safeguard.
- A request to skip the impact analysis, or to apply a rename mechanically, no longer downgrades a published contract change to an ordinary reversible edit. Renaming a published column now names its semantic, BI, exposure, orchestration, and external consumers and waits for approval regardless of how the request was phrased.

## [1.2.0] - 2026-08-31

### Added

- Twelve auto-discovered day-to-day skills for source setup, model documentation, model tests, safe refactoring, coordinated renames, migration planning, incremental models, metric definitions, semantic layers, BI models, freshness investigations, and YAML maintenance.
- `/ae-validate` and the `validate-dbt` skill, which plan the smallest dbt selector statically, require an explicit local/development target and approval before warehouse-capable execution, interpret current dbt artifacts, and re-plan after approved repairs.
- Deterministic validation planning and result interpretation scripts. Neither script executes dbt or opens a network connection.
- Project-profile evidence for source identifiers, loaded-at fields, freshness thresholds, source filenames, incremental strategy, unique-key style, schema-change behavior, and incremental timestamps.
- Repository context detection for MetricFlow/dbt semantic files, LookML, and repository-declared orchestration, plus a content fingerprint that reports a stored profile as stale without overwriting human edits.

### Changed

- Work mode is now the silent default. Natural-language requests automatically compose the relevant analytics-engineering skills; users no longer need to select modes, agents, or slash commands for ordinary work.
- Public documentation now leads with outcomes and plain-language examples. Commands remain optional aliases rather than the primary product interface.
- Cursor, VS Code, and Antigravity now ship the same twenty-five canonical skills and seventeen optional command workflows.

### Security

- `dbt compile`, `show`, `debug`, and `docs generate` remain approval-gated because they may connect to a warehouse; `dbt deps` requires approval because it changes local packages.
- Automated validation denies `--full-refresh`, global selectors, inferred targets, and production-like targets. Static `dbt parse` and `dbt ls` remain low-friction.

## [1.1.0] - 2026-08-29

### Added

- An inference corrections section in `/ae-learn`, reported only when a human value disagrees with a counted inference and omitted entirely otherwise. When somebody edits a value the workflow inferred, that edit is a labelled example of static inference being wrong, which is the most useful defect report this project can receive, and it already exists on disk. Nothing is transmitted: the plugin has no network path, the section exists so the defect can be described accurately, and a person who chooses to share one carries it themselves. Field names, strengths, and counts identify nobody, but values can, since a source schema can name a vendor and a prefix can encode a business domain, so any value carrying that risk is flagged with a redacted form beside it.
- A test asserting that no shipped hook or script can open a network connection, making the zero-telemetry commitment in `PRIVACY.md` a property of the code rather than of anyone's intent. Imports are read with the AST rather than matched with a regex, because the distinction is a fine one: `urllib.parse` is string handling that the cloud gate legitimately needs to check an MCP host, while `urllib.request` is a transport and must never appear. The guard was verified by injecting a violation and confirming it fails.
- Support for VS Code (GitHub Copilot) and Google Antigravity alongside Cursor. The toolkit stays authored once, as a Cursor plugin, and `scripts/build_targets.py` generates the other layouts. Skills are already an open standard and travel unchanged; rules become `AGENTS.md`, and commands become prompt files on VS Code and skills on Antigravity.
- `hooks/host_contract.py`, which translates a gate decision into each host's hook reply shape and recovers the command or MCP server from each host's payload. Cursor separates shell and MCP into two events while the other hosts multiplex every tool through one `PreToolUse`, so both gates register there and each stands aside for traffic that is not its own. The rules themselves are untouched: `classify()` remains the single place a safety judgement is made, and the Cursor contract is byte-identical to before.
- `scripts/install_target.py`, which installs a generated target into a repository. It merges `AGENTS.md`, hook configuration, and MCP configuration instead of overwriting them, placing the toolkit's rules in a marked block that reinstalling updates in place, so a team's own configuration survives. It rewrites hook commands to absolute paths, and it verifies the installed gate by running a command that must be denied and confirming it was.
- Cross-checked every authored and generated skill against `skills-ref`, the Agent Skills reference implementation. All 52 skill directories validate, and each sits within the standard's recommended budgets of 500 lines and roughly 5000 tokens; the largest is 100 lines. The reference library is not taken as a dependency, since the toolkit ships standard-library Python only and the library states it is not for production use, so the rules stay encoded in our own tests and the README records how to repeat the comparison.
- Tests for the three ways VS Code silently declines to load a skill: a `name` that does not match its directory, a name outside lowercase letters, numbers, and hyphens, and a description over 1024 characters. Each failure is invisible at runtime, since the target installs, the files are present, and the workflow is simply absent, so the check has to happen at build time. All generated skills currently pass; the longest description is 255 characters.
- `python3 scripts/build_targets.py --check`, run in CI, which fails when a generated target no longer matches the source. Three hand-maintained copies would drift, and a rule tightened for Cursor while staying loose elsewhere is worse than an absent one: it is a guardrail the user still believes in.
- Convention inference. `scripts/infer_conventions.py` derives a project's naming, surrogate key, documentation, testing, source, and SQL conventions from the models it already contains, and reports each one with the number of models supporting and contradicting it. The conventions a repository states are no longer something the user has to type.
- Three workflows built on that inference: `/ae-learn` proposes a project profile, `/ae-build-model` builds a model in the team's own idiom, and `/ae-trace` follows a figure back to its source and explains what it measures.
- A confidence-gated boundary between inferring and asking, in `rules/ae-conventions.mdc`. A convention holding across at least 80 percent of at least five models is applied silently; a thin majority is applied but stated as an assumption; a tie or a genuine split becomes a question with its competing candidates attached. This replaces a judgment call with a measurement, so "don't ask what the repository can tell you" is enforceable rather than aspirational.
- A repository-write boundary in `rules/data-safety.mdc`, which previously governed only databases. Creating a file is additive and permitted; editing or deleting existing work requires a diff and approval.
- Convention inference ignores installed packages and build output, so a vendored project's style is never reported as the team's own.
- Convention inference treats a clean directory split as a question rather than a majority vote. When two patterns never share a directory, that is a migration or a legacy boundary, and counting files would hand the answer to whichever side is larger, which is usually the side being retired. A stray outlier in a large repository is still ignored.
- `references/warehouse-portability.md`, covering the places warehouses diverge quietly: surrogate key hashing, `QUALIFY` support, identifier case, semi-structured access, incremental strategies, type names, and inherited platform configuration. It also states how to behave in a project that is not dbt, and how to treat a BI or semantic layer as another hop rather than as a vendor to support. The always-applied conventions rule now forbids introducing a function, strategy, or type that appears nowhere in the project.
- Dedicated public repository at `https://github.com/analyticsengineering/ae-toolkit`, with the plugin manifest at the repository root.
- Continuous integration running the public contract, safety, package, and generated-target drift tests.

### Changed

- Nine workflows are now free and local rather than six, since convention inference, model building, and lineage tracing all run entirely from repository files.
- Install, contribution, and marketplace documentation now describe repository-root usage instead of a subdirectory of a larger project.
- Every workflow must now recompute figures it derives itself, such as counts, percentages, and ratios, and state the denominator.
- Data profiling separates profiler-computed statistics from hand-derived figures and rechecks each derived figure before it reaches the report.

### Fixed

- Shell command extraction covers both Copilot payload dialects. VS Code documents snake_case `tool_name` and `tool_input` with an object argument, while Copilot CLI documents camelCase `toolName` and `toolArgs` with the arguments encoded as a JSON string. An implementation written against either one alone would have failed to find the command on the other, and a gate that cannot find the command cannot judge it. Both are now covered and tested, and an unrecognised shape is denied rather than allowed.
- Generated targets no longer name a script they do not carry. The rules reference `scripts/redact_secrets.py` for secret inspection before any cloud transmission, but the first generator selected shipped scripts by scanning skills and commands only, and rules ship too, as `AGENTS.md`. Both hosts would have received an instruction to redact using a file that was absent, and it would have read as enforced. Script selection now covers every authored file whose text reaches a target, and bare `scripts/...` references are rewritten to the installed location, since on these hosts that path points at the user's own repository rather than at the toolkit. A test now asserts that no generated document names a missing file.
- Uppercase model names are read as a convention rather than as an absence. Layer detection compared a model's leading token against lowercase names, so a project of `STG_ORDERS` and `FCT_ORDERS` models reported no naming convention at all. Snowflake folds unquoted identifiers to upper case and many Snowflake projects are written that way, so an entire warehouse's users would have had the plugin conclude their repository was silent and then invent a lowercase default, producing a model that matched nothing around it. Matching is now case-insensitive while the prefix is reported in the casing the team uses, and a project mixing `STG_` with `stg_` reports both candidates instead of quietly picking one.
- The warehouse is identified without a committed `profiles.yml`. That file holds credentials, lives in `~/.dbt`, and is supplied by dbt Cloud, so most repositories do not contain one and the adapter was simply unknown. Detection now falls back to a pinned adapter package in `requirements.txt` or `pyproject.toml`, then to configuration keys only one warehouse accepts, and reports which signal answered. Two conflicting adapters yield no answer rather than a guess, because a wrong warehouse is more harmful than an unknown one.
- `build-model` now checks what a new model inherits from its directory's `dbt_project.yml` block. Those blocks are where platform settings live, and they differ by warehouse. A dimension written into a marts directory alongside a partitioned event fact inherited a partition on a date column the dimension did not have, which fails at run time; overriding the materialization does not clear the rest of the block.
- A required output section can no longer force a workflow to produce what the workflow forbids. `build-model` now has an explicit non-build outcome for ambiguous grain, and `project-profile` permits an empty confirmation section when the repository already settles every convention.
- `build-model` now stops at the grain step and returns a `# Grain Decision Needed` report instead of a model when two grains survive, so declining to build is an expressible success rather than an incomplete answer. A request to create files does not settle the grain, and a column list spanning a header and its lines is evidence of ambiguity rather than a decision.
- `build-model` now resolves fanout in the SQL rather than leaving a warning beside an unchanged measure. The skill names three concrete repairs and treats warning-only output as a failure.
- `rules/ae-conventions.mdc` now states that an empty question section is a finding rather than a gap across every workflow. A question invented to fill a heading asks a person to re-decide something the report just proved. The converse is stated too, so no report suppresses a real question to look complete.

### Security

- Antigravity hook commands are installed as absolute paths. Antigravity resolves a relative hook command against the directory the session started in, and a hook that fails to launch does not block the tool call it was meant to gate. A session opened from a subdirectory would therefore have run with no destructive-command gate at all, silently and while still appearing protected. `install_target.py` stamps absolute paths and then proves the gate refuses a command it must refuse, reporting failure rather than assuming success.
- Gate scripts exit non-zero without printing a decision when given an unrecognised host, so a misconfigured hook cannot be read as approval. An unrecognised payload shape is denied for the same reason: these hook APIs are young and have changed field names, and a gate that cannot find the command must not wave it through.
- Real dbt package downloads and run logs are excluded from version control so vendored code cannot be read as a team's own style.

## [1.0.0] - 2026-08-29

### Added

- Initial Cursor Plugin manifest and component structure.
- Six free, local-first workflows:
  - SQL review;
  - data profile;
  - data-model review;
  - dbt health;
  - analytics requirements;
  - explain data code.
- Work, Learn, and Assessment response modes.
- Local basic plus optional connected advanced workflows for incidents, API-pipeline architecture, and analytics pull-request review.
- Connected diagnostic, hint, grading, capstone preflight, and course integration structure.
- Optional MCP configuration for `https://mcp.analyticsengineering.com/mcp`.
- `.ae/exercise.json` course-workspace integration with server-authority and submission-approval boundaries.
- Deterministic gates for destructive shell/database behavior and connected data transfer.
- Local-install, privacy, security, contribution, testing, troubleshooting, and marketplace-submission documentation.
- MIT License.

### Security

- Database `DROP`, `TRUNCATE`, `INSERT`, `UPDATE`, `DELETE`, `MERGE`, and `ALTER` execution is denied in V1.
- Recognized read-only database commands and warehouse-executing dbt commands require explicit approval and target review.
- Connected requests and course submissions require a payload preview and explicit approval.
- Anonymous telemetry is zero in V1.

### Known limitations

- The remote MCP server is not implemented or bundled in this repository. Its configured URL indicates structural readiness only; connected capabilities depend on separately deployed server support.
- Offline operation cannot grade, authorize, or submit course work.
- Safety hooks are pattern-based defense in depth, not a security sandbox.
