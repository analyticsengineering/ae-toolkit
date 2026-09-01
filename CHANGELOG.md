# Changelog

All notable changes to Analytics Engineering Toolkit are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A shared deterministic core resolves the questions every dbt-facing script used to answer for itself. `scripts/project_context.py` establishes the Git root, the active dbt project, and every configured resource path; `scripts/resource_identity.py` gives each resource a type, name, version, language, and dependency list; `scripts/artifact_inventory.py` reads build artifacts from the configured target and prior state; `scripts/git_scope.py` normalizes changes into project-relative records. A monorepo with two projects, a project below the Git root, and a project that renames `models/` were each enough to make the old literal paths wrong.
- Validation plans emit `plan_version: 2` with independent ordered `validation_steps`. A tree holding a changed Python model, a changed singular test, and a changed source freshness threshold now produces three separately bounded operations instead of collapsing into one intent and losing two of the three checks. The `intent`, `selectors`, `scope`, and `commands` fields are derived from the steps and remain for existing consumers.
- Deleted resources resolve their surviving consumers from prior dbt state when `--state` supplies it. Without that state the plan says so and asks for explicit scope rather than emitting a selector naming a model that no longer exists.
- The bundled YAML reader understands the documented dbt subset: anchors, aliases, the top-level `anchors:` property, `<<:` merge keys with correct precedence, and inline flow mappings such as `{count: 1, period: day}`. A source whose freshness arrives through an alias is now read as a freshness contract instead of the literal string `*standard_freshness`. Aliases resolve to copies, so editing one table's threshold cannot rewrite another's. What the reader still cannot represent — multi-document files, custom tags, complex keys, and an alias with no anchor — is reported by construct and path so the caller degrades to unknown rather than guessing.
- Functions are first-class resources. SQL, Python, and JavaScript definitions under `function-paths`, their YAML arguments and return types, and their overloads are indexed with typed identities; overloads share one DAG identity while each definition file remains its own evidence. Changing a function plans a bounded operation against it, and renaming or deleting one reports that arbitrary SQL callers cannot be resolved statically rather than inventing a blast radius.
- The project context infers which dbt engine a repository runs on — `core`, `fusion`, or `unknown` — from pinned dependencies or an authoritative `.ae/project.yml`, and never by executing dbt. `latest_version_pointer` resolves from explicit model config, then an explicit project flag, then the engine default, and an unknown engine stays unknown instead of asserting that no pointer relation exists.
- Crossed hostile fixtures exercise the traits that only break in combination: a Python model under a custom `model-paths` in a nested project with a package-qualified versioned ref, an unrelated sibling project dirty at the same time, and an installed package inside a renamed packages directory. Companion tests disable each new guard and confirm the original defect returns.
- Every validation step names the artifact that would prove it ran, and a verification command that reads only that artifact. `interpret_dbt_results.py` accepts `--expect-operation`, `--since`, and `--invocation-id`, and reports `verified` only when the artifact it read can be tied to the command that was supposed to produce it.
- Dataset profiles carry an `observed` view alongside the sentinel-adjusted one. A `country` column containing `NA` reports four observed categories and, separately, the conditional reading in which it has three categories and 25 percent missingness, leaving the interpretation to someone who knows whether the file means Namibia.

### Fixed

- Recognized database clients now allow only a single readable `SELECT` or `EXPLAIN`, as an approval-gated read. Anything else, including a statement supplied by file, a statement the gate cannot read, and a second statement hidden behind a semicolon, is denied. `SELECT ... INTO` is classified as a write, because it creates a relation on Postgres and T-SQL and a file on MySQL. The client list covers the warehouse CLIs an analytics engineer actually reaches for rather than a handful of spellings.
- The documentation no longer claims the gate proves a command is read-only. The test is syntactic and establishes eligibility for approval: `select cleanup_everything()` is a perfectly formed query, and only the warehouse knows what that function does. `README.md` and `SECURITY.md` now say so, and a test fails if they drift back into claiming proof.
- That claim is now enforced by counting statements rather than by listing dangerous ones. The gate splits SQL on the semicolons a database would honour, ignoring quoted text and comments, and requires exactly one allowed statement, so `select 1; create table x as select 1` and `select 1; grant select on foo to public` are denied while `select 1 -- ; drop table orders` is correctly read as one harmless query. The statement class is resolved past its prefix, so `EXPLAIN ANALYZE DELETE` and `WITH ... DELETE` are mutations. `SHOW` and `DESCRIBE` are denied, matching what the policy text always said.
- `dbt clone` and `dbt retry` require the same approval as `dbt run`. Clone writes nodes into a target schema and retry re-executes the previous invocation, so neither belonged outside the warehouse-execution gate.
- Result interpretation implements dbt's current statuses: `warn` is a warning rather than a failure, `no-op` is a success, `partial success` reports how many microbatches succeeded and which failed, and a run in which everything skipped is incomplete rather than passed. A test node that errors with "permission denied" is categorised as an operational failure, not a failed assertion.
- `run_results.json` and `sources.json` from different dbt invocations are no longer merged. An hour-old failed build could previously be reported as the outcome of a freshness check that had just passed.
- A `--state` path that does not exist is an error rather than a silent downgrade to no state, which used to produce a plan asking for the scope the user had just supplied.
- Physically blank CSV lines are skipped and counted instead of becoming all-null rows that inflated every missingness percentage in the file.
- A JSON document holding one empty array is profiled as the zero-row extract it is, naming the collection it inferred. Only competing empty arrays still require `--record-path`. Either way the wrapper object is never profiled as a single row with one column per table.
- The shell gate enforces the written policy on destructive Git rather than a subset of its spellings: force push, forced checkout and switch, branch deletion, and stash destruction are denied, through `-lc` wrappers, clustered short options, value-taking `sudo` and `env` options, and command chains, and without matching the same words quoted inside `echo`.
- The cloud gate scans payloads with the same secret detector the rest of the toolkit uses, so a token format added in one place is no longer still transmittable from the other. Previews that stop early now say how many named fields and list entries they omitted, and report the payload's shape and size, because a preview that silently truncates describes less than it is about to send.
- Dataset profiling suppresses ranges, extrema, and outlier bounds for numeric personal columns such as salary, balance, and government identifiers. A minimum and maximum salary across six rows comes close to naming the people in the file.
- Only genuinely empty values count as nulls. Sentinels such as `N/A`, `unknown`, and `-` are counted and named separately, so a column that is 50 percent sentinel is no longer reported as complete or as empty.
- Duplicate and blank CSV headers are renamed on the record, with the original name, position, and reason reported instead of columns silently overwriting each other.
- A JSON document containing more than one plausible record array names the candidates and their row counts rather than profiling whichever came first; `--record-path` selects one.
- Source freshness results are interpreted from the configured `sources.json` with per-table status, lag, and generated time, closing the loop between running a freshness check and reading its outcome.
- Adapter inference no longer treats `partition_by` and `cluster_by` as evidence, since several warehouses use both. A confident answer now requires exclusive syntax, a pinned adapter package, or profile evidence.
- Incremental warnings are strategy-aware: an `append` model needs no `unique_key`, while a `merge` model without one is still a defect.

- Convention inference reads both legacy direct and modern dbt `config:` placement for source/table `loaded_at_field` and freshness properties.
- Model-description coverage uses every project-owned SQL model as its denominator; listed YAML columns no longer imply complete output-column documentation.
- Source load fields and freshness thresholds are reported by source/table as resource contracts rather than promoted to global house conventions.
- Legacy projects with root-level final models such as `orders.sql` and `customers.sql` contribute positive evidence for unprefixed final naming.
- The safety gate tokenizes shell commands, unwraps shell launchers, and blocks split/long-form recursive deletion plus destructive `git restore`, `checkout`, `clean`, `reset`, and `switch` forms without matching quoted examples printed by `echo`.
- Validation planning scopes changed singular tests, source tests, source freshness, and source consumers; dependency-wide macro/package/project changes require explicit model scope.
- Minimum validation intent now applies even when a caller names a model; broader validation requires the existing explicit override.
- Saved-query-only projects are recognized as using dbt's Semantic Layer.

### Changed

- Correctness-critical unknown source mutation, delete, correction-timestamp, and lateness behavior may produce one focused question after local evidence is exhausted.
- Column renames route explicitly: private atomic name-only changes use `rename-model`, while published interfaces requiring compatibility or phased cutover use `migration-plan`.
- An explicit request to build an ingestion pipeline authorizes reversible local extractor, schema, and orchestration edits under the ordinary repository write rules. Running the pipeline stays separately gated: calling the API, a secret manager, a cloud, or a warehouse still needs an explicit trigger and approval.

## [1.2.1] - 2026-08-31

### Fixed

- Validation planning distinguishes formatting/comment, description-only, test-only, contract, rename/delete, and semantic/metric YAML changes so harmless metadata edits no longer select downstream models.
- Validation planning now recommends intent from the changed resource type and omits a broader warehouse command for metadata-only or test-only changes unless the caller explicitly overrides the safeguard.
- A request to skip the impact analysis, or to apply a rename mechanically, no longer downgrades a published contract change to an ordinary reversible edit. Renaming a published column now names its semantic, BI, exposure, orchestration, and external consumers and waits for approval regardless of how the request was phrased.
- Reference documents named in the always-applied rules, the reviewer and pipeline agents, and the freshness workflow now resolve on every host. They were written as bare paths such as `references/privacy.md`, which pointed at the user's own repository rather than the toolkit, so the privacy handling, severity scale, terminology, and warehouse-portability guidance were unreachable wherever those files did not happen to exist. The rule still read as enforced while the document it delegates to was missing.
- Generation retargets reference paths as well as script paths, and a test now rejects any runtime path that resolves neither beside its own document nor under the shipped toolkit root.
- The secret detector no longer reports `api_key=os.environ[...]` as a hardcoded credential. Flagging the correct way to handle a secret produced warnings on the files most deserving of trust, and the habit that builds is the real cost.
- The secret detector no longer reports an unquoted assignment from a function call, such as `token = uuid.uuid4().hex`, as a token. A literal credential written without quotes cannot contain a call, and the unquoted formats that do occur -- JWTs, hex digests, base64 keys -- have no parentheses, so quoted literals and bare high-entropy values are still caught.

### Changed

- Creation and editing workflows now report `Changed`, `Why`, `Verified`, and `Remaining uncertainty` instead of exposing Work mode or review-framework fields.
- Explicit requests authorize reversible project-owned SQL, YAML, documentation, test, and local analytics configuration edits. Renames, deletions, breaking contracts, broad migrations, infrastructure/data access, external transmission, and destructive actions retain risk-based gates.
- Convention inference is ephemeral by default; `.ae/project.yml` is persisted only when the user explicitly asks to save or share a project profile.
- Convention-dependent workflows name the inference script instead of alluding to "static convention inference", so the support counts they report come from something that actually ran.
- A repository that is not dbt is treated as a repository with its own conventions rather than one with none. Empty dbt inference now routes to repository inspection, and `ref()`, `schema.yml`, and dbt directory layout are not introduced into a project that has none.
- `/ae-build-model`, `/ae-trace`, and `/ae-learn` no longer stack the reviewer persona onto creation and explanation work; its Evidence/Risk/Recommendation/Verification framing contradicted the Changed/Why/Verified contract those commands promise. Review commands keep it.
- On Antigravity, where commands are also model-invocable, each command alias now names the canonical skill it fronts, so routing to the shorter entry cannot deliver less work than the skill it duplicates.
- `dbt-health` and `validate-dbt` now agree about `dbt parse`. The audit declines it because regenerating artifacts changes the evidence under review, not because the command is risky, and it says so instead of reading as an arbitrary rule that the other workflow ignores.
- SQL and data-model reviews collapse empty sections on small changes and keep every section for pull requests, published contracts, and explicitly requested formal reviews.
- The README states the fail-closed behavior each host actually provides. Cursor declares `failClosed`; VS Code and Antigravity expose no equivalent, so a gate that cannot launch there leaves the call ungated rather than blocking it.

### Unchanged by intent

- Renames, deletions, and published column changes remain preview-and-approval operations. No low-blast-radius auto-proceed exception was added.

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
