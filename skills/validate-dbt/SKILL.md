---
name: validate-dbt
description: Plans and runs the smallest safe dbt validation loop for changed or named resources. Use when the user asks to validate, compile, test, build, check, or verify dbt work, or asks the agent to fix failures and recheck them.
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
   - `python3 "${CURSOR_PLUGIN_ROOT}/scripts/inspect_dbt.py" <project-root> --pretty`
   - `python3 "${CURSOR_PLUGIN_ROOT}/scripts/inspect_git.py" <project-root> --pretty`
3. Determine whether the user named a scope. If not, derive it only from changed dbt resources. Classify YAML changes: formatting/comments and descriptions are static; generic, unit, and source tests validate only their named resources; source freshness and loaded-at changes validate the affected source tables; contract fields, renames, and deletions include downstream consumers; semantic/metric changes resolve affected consumers before any model build. Parse `ref()` and `source()` calls in changed singular tests and select the exact test. Macro, package, or project-config changes require explicit affected model scope before warehouse work. Do not turn an unrelated dirty worktree into validation scope.
4. Run `python3 "${CURSOR_PLUGIN_ROOT}/scripts/plan_dbt_validation.py" <project-root> --intent <intent> [--model <name>] [--target <dev-target>] --pretty`.
5. Review `recommended_intent`, its reason, and the plan rather than trusting either blindly. The planner omits an unnecessarily broad warehouse command for metadata-only or test-only changes unless `--allow-broader-intent` is deliberately supplied. Confirm every selected node exists, YAML changes map to the reported models, renamed resources include downstream consumers, and the scope is not global.
6. Run static `dbt parse` and `dbt ls` steps one at a time when useful. Stop if selector resolution differs from the plan.
7. Before `compile`, `show`, `test`, `run`, `build`, `debug`, or `docs generate`, show one exact command and state:
   - why this is the smallest sufficient command;
   - the explicit target and evidence it is local/development;
   - resources and materializations in scope;
   - whether warehouse objects may be created or replaced.
8. Obtain approval, then run exactly that command. Do not batch a second dbt command into the same shell call.
9. Read the resulting `target/run_results.json` or bounded log with `python3 "${CURSOR_PLUGIN_ROOT}/scripts/interpret_dbt_results.py" --run-results <path> [--log <path>] --pretty`.
10. If validation fails, identify the smallest repair. When the request explicitly includes fixing failures, apply reversible project-owned SQL/YAML/test edits without a second approval. Otherwise preview the repair first because validation alone does not authorize edits. Contract changes, renames, deletions, and scope expansion always require preview, blast radius, and approval.
11. Re-plan after a repair. Never broaden a selector silently. Stop after five execution attempts and report unresolved evidence rather than looping.

## Command choice

- `parse`: project structure, Jinja parsing, and graph construction.
- `ls`: prove a selector resolves the intended resources.
- `compile`: compiled SQL is needed to resolve uncertainty; treat as warehouse-capable because adapter macros may connect.
- `test`: existing relations are current and only assertions need checking.
- `source freshness`: a source's freshness or loaded-at configuration changed; select only that source table.
- `run`: build is needed but tests are intentionally out of scope.
- `build`: models and their tests both require validation; preferred final check for new model work.

For inferred Git scope, formatting/comments and descriptions recommend static parse/selector checks; changed singular tests and test-only model/source YAML recommend `test`; source freshness/loaded-at changes recommend source-specific freshness; model SQL or contract changes recommend `build`; and semantic, macro, package, and project-config changes require consumer resolution before warehouse work. These minima still apply when the caller names a model: `--allow-broader-intent` is the explicit upward override. Never override a narrower user-requested check merely because the planner recommends `build`.

Never auto-run `deps`, `seed`, `snapshot`, `run-operation`, a global command, or any command with `--full-refresh`.

## Failure interpretation

Separate compile, database, permission, dependency, selector, and test-assertion failures. A failing uniqueness test is evidence about candidate grain; it is not merely a test to weaken. A missing column may mean stale lineage, a wrong target, or a model defect. Resolve those alternatives from files and artifacts before editing.

## Output

Return `# dbt Validation` with: Changed, including any repairs; Why this was the smallest scope; Verified, including target, commands run, and exit status; Remaining uncertainty. If execution is awaiting approval or a failure remains, state the exact next command or repair instead of exposing internal workflow state.

## Verification

- Every execution used an explicit non-production target and a non-empty selector.
- Planned and resolved selector sets agree.
- Reported pass/fail comes from the current command and artifact, not an older terminal transcript.
- Every repair was either explicitly included in the request or separately approved before application.
- No credentials, profile values, raw rows, or unbounded logs appear in output.
