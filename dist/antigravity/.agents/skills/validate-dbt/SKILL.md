---
name: validate-dbt
description: Plans and runs the smallest safe dbt validation loop for changed or named resources. Use when the user asks to validate, compile, test, build, check, or verify dbt work, or asks the agent to fix failures and recheck them, including the deprecations a dbt package upgrade brings.
---

# Validate dbt

Close the loop from static evidence to a bounded, approved dbt result. Default silently to Work mode; use Learn or Assessment only when requested or required by `.ae/exercise.json`.

## Boundary

- This is a free local workflow. Never require or call MCP.
- Static inspection and planning never contact a warehouse.
- A warehouse-capable command runs only after the exact command, selector, target, and likely side effects are previewed and approved.
- Only an explicitly confirmed local or development target is eligible. Never infer a target, use a production-like target, run globally without a selector, or use `--full-refresh`.

## Procedure

1. Read `.ae/exercise.json` and `.ae/project.yml` when present.
2. Run the static inspectors before proposing execution:
   - `python3 ".agents/ae-toolkit/scripts/inspect_dbt.py" <project-root> --pretty`
   - `python3 ".agents/ae-toolkit/scripts/inspect_git.py" <project-root> --pretty`
   - `python3 ".agents/ae-toolkit/scripts/dbt_capabilities.py" <project-root> --pretty` for the engine (dbt v1 or v2) and the evidence for it, whether JSON artifacts are written, and whether checks, static analysis, or dbt State apply. Use these answers instead of guessing from the CLI name.
3. Determine whether the user named a scope. If not, derive it only from changed dbt resources. Classify YAML changes: formatting/comments and descriptions are static; generic, unit, and source tests validate only their named resources; source freshness and loaded-at changes validate the affected source tables; contract fields, renames, and deletions include downstream consumers; semantic/metric changes resolve affected consumers before any model build. Parse `ref()` and `source()` calls in changed singular tests and select the exact test. Macro, package, or project-config changes require explicit affected model scope before warehouse work. Do not turn an unrelated dirty worktree into validation scope.
4. Run `python3 ".agents/ae-toolkit/scripts/plan_dbt_validation.py" <project-root> --intent <intent> [--model <name>] [--paths <changed-path>] [--state <prior-artifacts>] [--target <dev-target>] --pretty`.
5. Read `validation_steps`, not just `intent`. A mixed change produces several independent bounded operations, and each one is there because a different resource changed; running only the broadest of them skips the others. Review `recommended_intent` and its reason rather than trusting either blindly. The planner omits an unnecessarily broad warehouse command for metadata-only or test-only changes unless `--allow-broader-intent` is deliberately supplied. Confirm every selected node exists, YAML changes map to the reported models, renamed resources include downstream consumers, and the scope is not global.
6. Check `excluded_changes`, `unsupported_yaml`, and `unresolvable_deletions` before executing. A file excluded as belonging to another project in the same repository is not validated here; a YAML construct the reader cannot interpret makes that file's contribution unknown rather than absent; a deleted resource with no prior state needs explicit downstream scope, which `--state` can often supply instead.
7. Run static `dbt parse` and `dbt ls` steps one at a time when useful. Stop if selector resolution differs from the plan.
8. Before `compile`, `show`, `test`, `run`, `build`, `debug`, `docs generate`, `source freshness`, or `freshness`, however dbt is launched (`dbt`, `dbtf`, `python -m dbt`, or through `uv`, `pipx`, `conda`, and similar runners), show one exact command and state:
   - why this is the smallest sufficient command;
   - the explicit target and evidence it is local/development;
   - resources and materializations in scope;
   - whether warehouse objects may be created or replaced.
9. Obtain approval, then run exactly that command, including its `--log-format-file json --log-path` arguments. Do not batch a second dbt command into the same shell call. Where the plan lists several warehouse steps, approve and run them one at a time, in order. Note the UTC time immediately before each command; the artifact it writes is only evidence if it is newer than that.
10. Read the resulting artifacts with each step's `verification_command`, or equivalently `python3 ".agents/ae-toolkit/scripts/interpret_dbt_results.py" --project-dir <project-root> --expect-operation <step operation> --invocation-log <step log_path> --since <timestamp taken before the command> --command "<the exact command that ran>" [--log <path>] --pretty`. Naming the operation reads only that operation's artifact, so a leftover `run_results.json` cannot be reported as the outcome of a freshness check. dbt chooses its own invocation ID, so the step's JSON log is how that ID is recovered; the timestamp is only a fallback.
11. Treat `verified: false` as unverified, not as failure. It means the artifact could not be tied to the command that just ran, so re-run the step or state that the outcome is unproven. Read `status` using dbt's own vocabulary: `warned` is not a failure, `no_op` is a success, `partial` means inspecting `batches` for which microbatches failed, and `incomplete` means everything skipped. Under dbt State, nodes listed in `not_executed` were reused or cloned rather than run, so they are not evidence about this change, and `reused` means nothing ran at all. `not_written` means JSON artifacts were off for that command, so report its exit status and log rather than any file in the target directory. `uninterpreted` means dbt v2's `freshness.json` is current but its contents are not read; report the command's own output.
12. Read `required_evidence`, `satisfied_evidence`, and `unsatisfied_evidence` before reporting success. `artifact_verified` proves the result came from the command that just ran; it does not prove the change was validated. Honor a narrower request — `--intent test` runs the tests — but say plainly what remains open: tests passing against the relation already in the warehouse do not establish that the edited model executes.
13. If validation fails, identify the smallest repair. When the request explicitly includes fixing failures, apply reversible project-owned SQL/YAML/test edits without a second approval. Otherwise preview the repair first because validation alone does not authorize edits. Contract changes, renames, deletions, and scope expansion always require preview, blast radius, and approval.
14. Re-plan after a repair. Never broaden a selector silently. Stop after five execution attempts and report unresolved evidence rather than looping.

## Command choice

- `parse`: project structure, Jinja parsing, and graph construction.
- `ls`: prove a selector resolves the intended resources.
- `check` (dbt v2, when the project has checks): project-metadata rules, run locally without the warehouse. `dbt build` runs them first unless `--skip-checks` is passed; never add that flag to get a build through.
- `show --info <view>` (dbt v2): reads the generated Information Schema locally. `show --inline` and `show --select` run SQL in the warehouse and need approval.
- `compile`: compiled SQL is needed to resolve uncertainty; treat as warehouse-capable because adapter macros may connect.
- `test`: existing relations are current and only assertions need checking.
- `source freshness`: a source's freshness or loaded-at configuration changed; select only that source table.
- `run`: build is needed but tests are intentionally out of scope.
- `build`: models and their tests both require validation; preferred final check for new model work.

For inferred Git scope, formatting/comments and descriptions recommend static parse/selector checks; changed singular tests and test-only model/source YAML recommend `test`; source freshness/loaded-at changes recommend source-specific freshness; model SQL or contract changes recommend `build`; and semantic, macro, package, and project-config changes require consumer resolution before warehouse work. These minima still apply when the caller names a model: `--allow-broader-intent` is the explicit upward override. Never override a narrower user-requested check merely because the planner recommends `build`.

Never auto-run `deps`, `seed`, `snapshot`, `run-operation`, a global command, or any command with `--full-refresh`.

## Failure interpretation

Separate compile, database, permission, dependency, selector, and test-assertion failures. A failing uniqueness test is evidence about candidate grain; it is not merely a test to weaken. A failing `not_null` on a column documented as required is evidence of missing data, even when a note explains the gap; report it and ask rather than scoping the test. A missing column may mean stale lineage, a wrong target, or a model defect. Resolve those alternatives from files and artifacts before editing.

## Package upgrades

When the request upgrades a dbt package and asks to fix what breaks, search the project being upgraded (models, macros, tests, snapshots, analyses, YAML) for every call into the package's namespace and check each macro against the target version's changelog, or the vendored copy under `dbt_packages/`, rather than memory. Major versions often remove or move whole families of macros; for example dbt_utils 1.0 moved its cross-database macros such as `datediff` to the `dbt.` namespace. Report each call you changed and each you left, with why it survives. Other projects in the same repository keep their own versions unless the request names them.

## Output

Return `# dbt Validation` with: Changed, including any repairs; Why this was the smallest scope; Verified, including target, commands run, and exit status; Remaining uncertainty. Put any `unsatisfied_evidence` in Remaining uncertainty in plain words, such as "the tests passed against the existing relation; the edited model was not executed." If execution is awaiting approval or a failure remains, state the exact next command or repair instead of exposing internal workflow state.

## Verification

- Every execution used an explicit non-production target and a non-empty selector.
- Planned and resolved selector sets agree.
- Reported pass/fail comes from the current command and artifact, not an older terminal transcript.
- Every repair was either explicitly included in the request or separately approved before application.
- No credentials, profile values, raw rows, or unbounded logs appear in output.
